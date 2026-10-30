"""The human agent's console: escalated cases, and the decision to approve or reject them.

A human may approve what the policy engine would not, such as a Rs 15,000 refund. They still
cannot do what is impossible: the mock payment API refuses to refund a payment that never
debited the customer, or one that has already been refunded.
"""
import json

from app import agent, audit, mock_paytm, rbi
from app.db import get_conn, utc_now
from app.mock_paytm import PaytmError


def list_tickets() -> list[dict]:
    """Open tickets first, the nearest RBI deadline on top. Then decided tickets, newest first."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT k.ticket_id, k.summary, k.status, k.txn_id, k.customer_id, k.created_at,
                   c.case_id, c.resolved_at, c.refund_id, cu.name AS customer_name
            FROM tickets k
            JOIN cases c ON c.ticket_id = k.ticket_id
            JOIN customers cu ON cu.customer_id = k.customer_id
            """
        ).fetchall()

    tickets = [_with_details(dict(row)) for row in rows]
    waiting = [ticket for ticket in tickets if ticket["status"] == "open"]
    decided = [ticket for ticket in tickets if ticket["status"] != "open"]
    waiting.sort(key=lambda t: (t["rbi"] is None, t["rbi"]["deadline"] if t["rbi"] else "", t["created_at"]))
    decided.sort(key=lambda t: t["resolved_at"] or "", reverse=True)
    return waiting + decided


def approve(ticket_id: str) -> dict:
    ticket = _claim(ticket_id, "approved")
    try:
        refund = mock_paytm.initiate_refund(ticket["txn_id"] or "")
    except PaytmError:
        _release(ticket_id)  # The refund did not happen, so the case must stay in the queue.
        raise

    audit.log(ticket["case_id"], "SAFETY", f"HUMAN APPROVED: agent approved a refund on {ticket_id}")
    audit.log(ticket["case_id"], "ACT", f"Refund {refund['refund_id']} started for {refund['amount_inr']}", refund)
    facts = {"amount_inr": refund["amount_inr"], "txn_id": ticket["txn_id"], "refund_id": refund["refund_id"]}
    return _close_case(ticket, "human_approved", "refund_approved", facts, refund["refund_id"])


def reject(ticket_id: str) -> dict:
    ticket = _claim(ticket_id, "rejected")
    audit.log(ticket["case_id"], "SAFETY", f"HUMAN REJECTED: agent rejected {ticket_id}")
    return _close_case(ticket, "human_rejected", "refund_rejected", {"ticket_id": ticket_id}, None)


def _with_details(ticket: dict) -> dict:
    txn = mock_paytm.get_transaction(ticket["txn_id"]) if ticket["txn_id"] else None
    ticket["rbi"] = rbi.for_transaction(txn) if txn and ticket["status"] == "open" else None
    ticket["refund_blocked_reason"] = _refund_blocked_reason(txn)
    ticket["txn"] = {field: txn[field] for field in ("amount_inr", "payee_name", "status")} if txn else None
    return ticket


def _refund_blocked_reason(txn: dict | None) -> str | None:
    """Shown beside a disabled Approve button, so the agent knows why before clicking."""
    if txn is None:
        return "No transaction is linked to this case"
    if txn["refund"]:
        return f"Already refunded as {txn['refund']['refund_id']}"
    if txn["status"] != "failed_debited":
        return f"Payment status is {txn['status']}, so there is nothing to refund"
    return None


def _claim(ticket_id: str, new_status: str) -> dict:
    """Atomic, so a double-click or two agents cannot decide the same ticket twice."""
    with get_conn() as conn:
        claimed = conn.execute("UPDATE tickets SET status = ? WHERE ticket_id = ? AND status = 'open'", (new_status, ticket_id)).rowcount
        row = conn.execute(
            "SELECT k.ticket_id, k.txn_id, c.case_id FROM tickets k JOIN cases c ON c.ticket_id = k.ticket_id WHERE k.ticket_id = ?",
            (ticket_id,),
        ).fetchone()
    if row is None:
        raise PaytmError("ticket_not_found", f"No ticket with id {ticket_id}", 404)
    if not claimed:
        raise PaytmError("ticket_already_decided", f"{ticket_id} has already been decided", 409)
    return dict(row)


def _release(ticket_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE tickets SET status = 'open' WHERE ticket_id = ?", (ticket_id,))


def _close_case(ticket: dict, status: str, reply_key: str, facts: dict, refund_id: str | None) -> dict:
    with get_conn() as conn:
        messages = json.loads(conn.execute("SELECT messages FROM cases WHERE case_id = ?", (ticket["case_id"],)).fetchone()["messages"])
    reply = agent.reply_text(reply_key, messages, **facts)
    messages.append({"role": "assistant", "content": reply})
    with get_conn() as conn:
        conn.execute(
            "UPDATE cases SET status = ?, messages = ?, reply = ?, refund_id = ?, resolved_at = ? WHERE case_id = ?",
            (status, json.dumps(messages, ensure_ascii=False), reply, refund_id, utc_now(), ticket["case_id"]),
        )
    audit.log(ticket["case_id"], "ACT", "Reply sent to customer", {"reply": reply})
    return {"ticket_id": ticket["ticket_id"], "case_id": ticket["case_id"], "status": status, "reply": reply, "refund_id": refund_id}
