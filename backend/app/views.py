"""Read-only data the UI needs that does not belong to any one part of the agent."""
from app.db import get_conn
from app.mock_paytm import PaytmError, format_inr
from app.policy import payment_text_is_suspicious, safe_payee


def customers_with_payments() -> list[dict]:
    """Each customer and their payments, newest first, like the history screen in a payments app."""
    with get_conn() as conn:
        customers = conn.execute("SELECT customer_id, name, language FROM customers WHERE customer_id LIKE 'C%' ORDER BY customer_id").fetchall()
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


def notifications_since(after_id: int) -> dict:
    """Messages sent unasked, for the demo's named customers. Bulk recipients have no chat open."""
    with get_conn() as conn:
        rows = conn.execute("SELECT id, customer_id, kind, text FROM notifications WHERE id > ? AND customer_id LIKE 'C%' ORDER BY id", (after_id,)).fetchall()
        latest_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM notifications").fetchone()[0]
    return {"entries": [dict(row) for row in rows], "latest_id": latest_id}


HUMAN_TICKET_COST_INR = 100  # Assumptions from the pitch, not measured Paytm figures.
AI_TICKET_COST_INR = 10


def scoreboard() -> dict:
    with get_conn() as conn:
        chat_resolved = conn.execute("SELECT COUNT(*) FROM cases WHERE status = 'auto_resolved'").fetchone()[0]
        group_refunds = conn.execute("SELECT COUNT(*) FROM incident_items WHERE refund_id IS NOT NULL").fetchone()[0]
        escalated = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        average = conn.execute("SELECT AVG((julianday(resolved_at) - julianday(created_at)) * 86400) FROM cases WHERE status = 'auto_resolved'").fetchone()[0]
        told_first = conn.execute("SELECT COUNT(DISTINCT customer_id) FROM notifications WHERE kind = 'outage_alert'").fetchone()[0]
        attacks = conn.execute("SELECT COUNT(*) FROM audit_log WHERE stage = 'SAFETY' AND (event LIKE 'BLOCKED: suspicious%' OR detail LIKE '%Hidden instructions found in%')").fetchone()[0]
        attacks += sum(1 for row in conn.execute("SELECT note FROM transactions WHERE txn_id IN (SELECT txn_id FROM incident_items)") if payment_text_is_suspicious(row["note"]))

    auto_resolved = chat_resolved + group_refunds
    return {
        "auto_resolved": auto_resolved,
        "escalated": escalated,
        "average_seconds": round(average, 1) if average is not None else None,
        "rupees_saved": auto_resolved * (HUMAN_TICKET_COST_INR - AI_TICKET_COST_INR),
        "told_first": told_first,
        "attacks_blocked": attacks,
    }


def case_status(case_id: str) -> dict:
    """The chat polls this, so a customer sees a human's decision without refreshing."""
    with get_conn() as conn:
        row = conn.execute("SELECT case_id, status, reply, ticket_id, refund_id FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if row is None:
        raise PaytmError("case_not_found", f"No case with id {case_id}", 404)
    return dict(row)
