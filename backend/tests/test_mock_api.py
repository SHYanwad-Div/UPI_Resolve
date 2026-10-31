"""Hour 1 checks: the seed data tells the stories it claims, and the mock APIs behave."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import db, mock_paytm, seed
from app.main import app


@pytest.fixture
def client(fresh_db):
    with TestClient(app) as test_client:
        yield test_client


def rows(sql: str, *params) -> list:
    with db.get_conn() as conn:
        return conn.execute(sql, params).fetchall()


# --- Seed data ---

def test_seed_has_every_kind_of_transaction(client):
    statuses = Counter(row["status"] for row in rows("SELECT status FROM transactions"))
    assert statuses == {"failed_debited": 21, "success": 6, "pending": 2, "failed_no_debit": 2}
    assert len(rows("SELECT 1 FROM customers WHERE customer_id LIKE 'C%'")) == 10


def test_seed_timeline_makes_sense(client):
    """Nothing can be claimed before it happened, or refunded before it was claimed."""
    assert not rows(
        """
        SELECT 1 FROM claims c JOIN transactions t ON t.txn_id = c.txn_id
        WHERE c.created_at < t.created_at OR c.customer_id != t.customer_id
        """
    )
    assert not rows("SELECT 1 FROM refunds r JOIN claims c ON c.txn_id = r.txn_id WHERE r.created_at < c.created_at")
    assert len(rows("SELECT 1 FROM refunds")) == len(seed.PRIOR_REFUNDS)


def test_reseeding_clears_demo_changes(client):
    client.post("/mock-paytm/transactions/TXN1001/refund")
    seed.seed_db()
    assert client.get("/mock-paytm/transactions/TXN1001").json()["refund"] is None


# --- get_transaction ---

@pytest.mark.parametrize(
    "txn_id, paise, display",
    [("TXN1004", 18_050, "₹180.50"), ("TXN1005", 200_000, "₹2,000.00"), ("TXN1011", 200_001, "₹2,000.01"), ("TXN1013", 5_000_000, "₹50,000.00")],
)
def test_money_is_exact(client, txn_id, paise, display):
    body = client.get(f"/mock-paytm/transactions/{txn_id}").json()
    assert (body["amount_paise"], body["amount_inr"]) == (paise, display)


@pytest.mark.parametrize(
    "paise, display",
    [(4500, "₹45.00"), (99_999, "₹999.99"), (200_000, "₹2,000.00"), (5_000_000, "₹50,000.00"), (63_876_000, "₹6,38,760.00"), (12_345_678_900, "₹12,34,56,789.00")],
)
def test_amounts_use_indian_digit_grouping(paise, display):
    assert mock_paytm.format_inr(paise) == display


def test_get_transaction_returns_customer_and_refund_details(client):
    body = client.get("/mock-paytm/transactions/TXN1015").json()
    assert body["customer_name"] == "Manjunath Gowda"
    assert body["customer_language"] == "kn"
    assert body["refund"]["refund_id"] == "RFD-SEED-TXN1015"


def test_unknown_transaction_is_404(client):
    response = client.get("/mock-paytm/transactions/TXN9999")
    assert response.status_code == 404
    assert response.json()["error"] == "txn_not_found"


# --- initiate_refund ---

def test_refund_then_second_refund_is_refused(client):
    first = client.post("/mock-paytm/transactions/TXN1001/refund")
    assert first.status_code == 201
    assert first.json()["amount_paise"] == 34_900
    assert client.get("/mock-paytm/transactions/TXN1001").json()["refund"]["refund_id"] == first.json()["refund_id"]

    second = client.post("/mock-paytm/transactions/TXN1001/refund")
    assert second.status_code == 409
    assert second.json()["error"] == "already_refunded"


@pytest.mark.parametrize("txn_id", ["TXN1027", "TXN1028", "TXN1030"], ids=["success", "pending", "no_debit"])
def test_only_debited_failures_can_be_refunded(client, txn_id):
    response = client.post(f"/mock-paytm/transactions/{txn_id}/refund")
    assert response.status_code == 422
    assert response.json()["error"] == "not_refundable"
    assert not rows("SELECT 1 FROM refunds WHERE txn_id = ?", txn_id)


def test_refund_of_unknown_transaction_is_404(client):
    assert client.post("/mock-paytm/transactions/TXN9999/refund").status_code == 404


def test_amount_limit_is_not_enforced_here(client):
    """The Rs 2,000 limit is policy, not physics: a human can still approve this refund."""
    assert client.post("/mock-paytm/transactions/TXN1013/refund").status_code == 201


def test_simultaneous_refunds_pay_out_only_once(client):
    def attempt(_):
        try:
            mock_paytm.initiate_refund("TXN1002")
            return "paid"
        except mock_paytm.PaytmError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = Counter(pool.map(attempt, range(8)))

    assert results == {"paid": 1, "already_refunded": 7}
    assert len(rows("SELECT 1 FROM refunds WHERE txn_id = 'TXN1002'")) == 1


# --- create_ticket ---

def test_ticket_takes_its_customer_from_the_transaction(client):
    response = client.post("/mock-paytm/tickets", json={"summary": "  High-value failure, needs review. ", "txn_id": "TXN1012"})
    assert response.status_code == 201
    body = response.json()
    assert body["ticket_id"].startswith("TKT-")
    assert body["status"] == "open"
    assert body["customer_id"] == "C01"
    assert body["summary"] == "High-value failure, needs review."


def test_ticket_works_with_only_a_summary(client):
    """Matches the brief's create_ticket(summary), for complaints with no transaction id."""
    assert client.post("/mock-paytm/tickets", json={"summary": "Customer gave no transaction id."}).status_code == 201


@pytest.mark.parametrize(
    "payload, status, error",
    [
        ({"summary": "   "}, 422, "empty_summary"),
        ({"summary": "x", "txn_id": "TXN9999"}, 404, "txn_not_found"),
        ({"summary": "x", "customer_id": "C99"}, 404, "customer_not_found"),
    ],
)
def test_bad_tickets_are_refused(client, payload, status, error):
    response = client.post("/mock-paytm/tickets", json=payload)
    assert response.status_code == status
    assert response.json()["error"] == error
    assert not rows("SELECT 1 FROM tickets")
