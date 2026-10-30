"""The APIs behind the UI: the human console, the RBI clock, and the live feeds."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import agent, audit, db, llm, rbi, seed
from app.main import app


def tool_call(name, **arguments):
    return {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


@pytest.fixture
def client(fresh_db):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def escalate(fresh_db, monkeypatch):
    """Sends a complaint through the real agent, with a model that always proposes a refund."""

    def run(customer_id, txn_id, message=None):
        monkeypatch.setattr(llm, "chat", lambda messages, tools: {"content": None, "tool_calls": [tool_call("propose_refund", txn_id=txn_id, reason="Customer wants it back")]})
        return agent.handle_message(customer_id, message or f"{txn_id} failed")

    return run


def ticket_row(ticket_id):
    with db.get_conn() as conn:
        return conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()


def paid_refunds():
    with db.get_conn() as conn:
        return [row["txn_id"] for row in conn.execute("SELECT txn_id FROM refunds WHERE refund_id NOT LIKE 'RFD-SEED-%'")]


# --- Approve ---

def test_human_can_approve_what_policy_would_not(client, escalate):
    case = escalate("C01", "TXN1012")
    assert paid_refunds() == []

    response = client.post(f"/api/tickets/{case['ticket_id']}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "human_approved"
    assert paid_refunds() == ["TXN1012"]
    assert body["refund_id"] in body["reply"]
    assert "₹15,000.00" in body["reply"]
    assert ticket_row(case["ticket_id"])["status"] == "approved"


def test_approval_is_logged_and_the_customer_can_see_it(client, escalate):
    case = escalate("C01", "TXN1012")
    client.post(f"/api/tickets/{case['ticket_id']}/approve")

    events = [step["event"] for step in audit.for_case(case["case_id"])]
    assert any(event.startswith("HUMAN APPROVED") for event in events)
    assert any(event.startswith("Refund") for event in events)

    status = client.get(f"/api/cases/{case['case_id']}").json()
    assert status["status"] == "human_approved"
    assert status["refund_id"] in status["reply"]


def test_customer_gets_the_decision_in_their_own_language(client, escalate):
    case = escalate("C01", "TXN1012", "TXN1012 ವಿಫಲವಾಗಿದೆ")
    assert "ಅನುಮೋದಿಸಿದ್ದಾರೆ" in client.post(f"/api/tickets/{case['ticket_id']}/approve").json()["reply"]


@pytest.mark.parametrize(
    "customer_id, txn_id, why",
    [("C03", "TXN1027", "payment succeeded"), ("C01", "TXN1028", "still pending"), ("C05", "TXN1030", "no money was debited"), ("C04", "TXN1015", "already refunded")],
)
def test_human_cannot_approve_the_impossible_and_the_ticket_stays_open(client, escalate, customer_id, txn_id, why):
    case = escalate(customer_id, txn_id)

    response = client.post(f"/api/tickets/{case['ticket_id']}/approve")

    assert response.status_code in (409, 422), why
    assert paid_refunds() == []
    assert ticket_row(case["ticket_id"])["status"] == "open"
    assert client.get(f"/api/cases/{case['case_id']}").json()["status"] == "escalated"
    assert not any(step["event"].startswith("HUMAN APPROVED") for step in audit.for_case(case["case_id"]))


def test_ticket_without_a_transaction_cannot_be_approved(client, escalate):
    case = escalate("C02", "TXN1001")  # Someone else's payment, so nothing is linked.
    assert client.post(f"/api/tickets/{case['ticket_id']}/approve").status_code == 404
    assert paid_refunds() == []
    assert ticket_row(case["ticket_id"])["status"] == "open"


# --- Reject ---

def test_reject_moves_no_money_and_tells_the_customer(client, escalate):
    case = escalate("C01", "TXN1012")

    body = client.post(f"/api/tickets/{case['ticket_id']}/reject").json()

    assert body["status"] == "human_rejected"
    assert case["ticket_id"] in body["reply"]
    assert paid_refunds() == []
    assert any(step["event"].startswith("HUMAN REJECTED") for step in audit.for_case(case["case_id"]))


@pytest.mark.parametrize("first, second", [("approve", "approve"), ("approve", "reject"), ("reject", "approve"), ("reject", "reject")])
def test_a_ticket_can_only_be_decided_once(client, escalate, first, second):
    case = escalate("C01", "TXN1012")
    assert client.post(f"/api/tickets/{case['ticket_id']}/{first}").status_code == 200

    response = client.post(f"/api/tickets/{case['ticket_id']}/{second}")

    assert response.status_code == 409
    assert response.json()["error"] == "ticket_already_decided"
    assert len(paid_refunds()) == (1 if first == "approve" else 0)


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_unknown_ticket_is_404(client, action):
    assert client.post(f"/api/tickets/TKT-NOPE/{action}").status_code == 404


# --- The console list ---

def test_open_tickets_come_first_sorted_by_rbi_deadline(client, escalate):
    pending = escalate("C01", "TXN1028")  # No money stuck, so no clock.
    merchant = escalate("C07", "TXN1013")  # T+5.
    overdue = escalate("C01", "TXN1012")  # A transfer from 3 days ago: past T+1.
    decided = escalate("C03", "TXN1014")
    client.post(f"/api/tickets/{decided['ticket_id']}/reject")

    order = [ticket["ticket_id"] for ticket in client.get("/api/tickets").json()]

    assert order == [overdue["ticket_id"], merchant["ticket_id"], pending["ticket_id"], decided["ticket_id"]]


def test_console_explains_why_a_refund_is_blocked(client, escalate):
    escalate("C04", "TXN1015")
    escalate("C01", "TXN1028")
    escalate("C07", "TXN1013")
    reasons = {ticket["txn_id"]: ticket["refund_blocked_reason"] for ticket in client.get("/api/tickets").json()}
    assert "Already refunded" in reasons["TXN1015"]
    assert "pending" in reasons["TXN1028"]
    assert reasons["TXN1013"] is None


def test_ticket_shows_transaction_facts_and_summary(client, escalate):
    escalate("C07", "TXN1013")
    ticket = client.get("/api/tickets").json()[0]
    assert ticket["customer_name"] == "Neha Verma"
    assert ticket["txn"]["amount_inr"] == "₹50,000.00"
    assert "Vidya College Fees" in ticket["summary"]


def test_decided_ticket_has_no_clock_running(client, escalate):
    case = escalate("C01", "TXN1012")
    client.post(f"/api/tickets/{case['ticket_id']}/approve")
    assert client.get("/api/tickets").json()[0]["rbi"] is None


# --- The RBI clock ---

def ist(*args):
    return datetime(*args, tzinfo=rbi.IST)


@pytest.mark.parametrize(
    "paid_at, payment_type, last_day",
    [
        (ist(2026, 10, 30, 14, 0), "p2p", (2026, 10, 31)),
        (ist(2026, 10, 30, 14, 0), "p2m", (2026, 11, 4)),
        (ist(2026, 10, 30, 23, 59), "p2p", (2026, 10, 31)),  # One minute before midnight still counts as the 30th.
        (ist(2026, 10, 31, 0, 1), "p2p", (2026, 11, 1)),
        (ist(2026, 12, 31, 12, 0), "p2p", (2027, 1, 1)),  # Crosses a year.
    ],
)
def test_deadline_is_the_end_of_the_right_calendar_day(paid_at, payment_type, last_day):
    deadline = datetime.fromisoformat(rbi.reversal_deadline(db.to_iso(paid_at), payment_type)).astimezone(rbi.IST)
    assert (deadline.year, deadline.month, deadline.day) == last_day
    assert (deadline.hour, deadline.minute) == (23, 59)


def test_calendar_day_is_indian_not_utc():
    """21:00 UTC on the 30th is 02:30 on the 31st in India, so T is the 31st."""
    paid_at = datetime(2026, 10, 30, 21, 0, tzinfo=timezone.utc)
    deadline = datetime.fromisoformat(rbi.reversal_deadline(db.to_iso(paid_at), "p2p")).astimezone(rbi.IST)
    assert deadline.day == 1 and deadline.month == 11


@pytest.mark.parametrize(
    "txn",
    [
        {"status": "success", "refund": None},
        {"status": "pending", "refund": None},
        {"status": "failed_no_debit", "refund": None},
        {"status": "failed_debited", "refund": {"refund_id": "RFD-1"}},
    ],
)
def test_clock_only_runs_while_money_is_stuck(txn):
    assert rbi.for_transaction(txn) is None


def test_seed_has_an_overdue_case_and_a_transfer_and_a_merchant_payment(client):
    rent = rbi.for_transaction(client.get("/mock-paytm/transactions/TXN1012").json())
    fees = rbi.for_transaction(client.get("/mock-paytm/transactions/TXN1013").json())
    assert rent["rule"] == "T+1" and rent["kind"] == "transfer"
    assert rent["deadline"] < db.utc_now()
    assert fees["rule"] == "T+5" and fees["kind"] == "merchant payment"
    assert fees["deadline"] > db.to_iso(datetime.now(timezone.utc) + timedelta(days=1))


# --- Feeds ---

def test_customers_list_shows_only_their_own_payments(client):
    customers = client.get("/api/customers").json()
    assert len(customers) == 10
    ananya = next(customer for customer in customers if customer["customer_id"] == "C01")
    assert {payment["txn_id"] for payment in ananya["payments"]} == {t.txn_id for t in seed.TRANSACTIONS if t.customer_id == "C01"}
    assert "scenario" not in json.dumps(customers)


def test_chat_endpoint_runs_the_agent(client, monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda messages, tools: {"content": None, "tool_calls": [tool_call("propose_refund", txn_id="TXN1001", reason="x")]})
    body = client.post("/api/chat", json={"customer_id": "C01", "message": "TXN1001 failed"}).json()
    assert body["status"] == "auto_resolved"
    assert body["refund_id"]


@pytest.mark.parametrize(
    "payload, status",
    [
        ({"customer_id": "C01", "message": "x" * 2001}, 422),
        ({"customer_id": "C01", "message": "   "}, 422),
        ({"customer_id": "C99", "message": "Hello"}, 404),
        ({"message": "Hello"}, 422),
    ],
)
def test_chat_refuses_bad_input(client, payload, status):
    assert client.post("/api/chat", json=payload).status_code == status


def test_audit_feed_returns_only_new_entries(client, escalate):
    case = escalate("C01", "TXN1012")
    first = client.get("/api/audit").json()
    assert first["entries"]
    assert first["entries"][0]["customer_name"] == "Ananya Rao"
    assert first["entries"][0]["case_id"] == case["case_id"]
    assert first["latest_id"] == first["entries"][-1]["id"]
    assert client.get(f"/api/audit?after={first['latest_id']}").json()["entries"] == []


def test_audit_feed_shows_the_reset_so_the_ui_can_clear(client, escalate):
    escalate("C01", "TXN1012")
    before = client.get("/api/audit").json()["latest_id"]
    seed.seed_db()
    assert client.get(f"/api/audit?after={before}").json()["latest_id"] < before


def test_unknown_case_is_404(client):
    assert client.get("/api/cases/CASE-NOPE").status_code == 404
