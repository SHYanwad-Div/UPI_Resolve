"""Read-only data the UI needs that does not belong to any one part of the agent."""
from app.db import get_conn
from app.mock_paytm import PaytmError, format_inr
from app.policy import safe_payee


def customers_with_payments() -> list[dict]:
    """Each customer and their payments, newest first, like the history screen in a payments app."""
    with get_conn() as conn:
        customers = conn.execute("SELECT customer_id, name, language FROM customers ORDER BY customer_id").fetchall()
        payments = conn.execute("SELECT txn_id, customer_id, payee_name, amount_paise, status FROM transactions ORDER BY created_at DESC").fetchall()
    return [
        {
            **dict(customer),
            "payments": [
                {"txn_id": p["txn_id"], "payee_name": safe_payee(p["payee_name"]), "amount_inr": format_inr(p["amount_paise"]), "status": p["status"]}
                for p in payments
                if p["customer_id"] == customer["customer_id"]
            ],
        }
        for customer in customers
    ]


def case_status(case_id: str) -> dict:
    """The chat polls this, so a customer sees a human's decision without refreshing."""
    with get_conn() as conn:
        row = conn.execute("SELECT case_id, status, reply, ticket_id, refund_id FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if row is None:
        raise PaytmError("case_not_found", f"No case with id {case_id}", 404)
    return dict(row)
