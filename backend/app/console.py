"""The human agent's console: escalated cases, and the decision to approve or reject them.

A human may approve what the policy engine would not, such as a Rs 15,000 refund. They still
cannot do what is impossible: the mock payment API refuses to refund a payment that never
debited the customer, or one that has already been refunded. Every decision carries a name, and
large or flagged refunds need a second, different person.
"""
import json

from app import agent, audit, mock_paytm, policy, rbi
from app.db import get_conn, utc_now
from app.mock_paytm import PaytmError

QUOTE_LIMIT = 300


def list_tickets() -> list[dict]:
    """Open tickets first, the nearest RBI deadline on top. Then decided tickets, newest first."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT k.ticket_id, k.summary, k.status, k.txn_id, k.customer_id, k.created_at, k.first_approver, k.decided_by,
                   c.case_id, c.resolved_at, c.refund_id, c.messages, cu.name AS customer_name
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


def approve(ticket_id: str, staff: str) -> dict:
    ticket = _open_ticket(ticket_id)
    txn = mock_paytm.get_transaction(ticket["txn_id"]) if ticket["txn_id"] else None

    if txn and _needs_second_approver(txn):
        blocked = _refund_blocked_reason(txn)
        if blocked:
            raise PaytmError("not_refundable", blocked, 422)
        if ticket["first_approver"] is None:
            with get_conn() as conn:
                conn.execute("UPDATE tickets SET first_approver = ? WHERE ticket_id = ? AND first_approver IS NULL", (staff, ticket_id))
            audit.log(ticket["case_id"], "SAFETY", f"FIRST APPROVAL: {staff} approved {ticket_id}, a different person must also approve")
            return {"ticket_id": ticket_id, "case_id": ticket["case_id"], "status": "needs_second_approver", "first_approver": staff}
        if ticket["first_approver"] == staff:
            raise PaytmError("same_approver", "A different person must give the second approval", 409)

    # All or nothing: if the refund is refused, the ticket stays open and nothing is logged as done.
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _claim(conn, ticket_id, "approved", staff)
        refund = mock_paytm.initiate_refund(ticket["txn_id"] or "", conn)
        audit.log(ticket["case_id"], "SAFETY", f"HUMAN APPROVED: {staff} approved a refund on {ticket_id}", conn=conn)
        audit.log(ticket["case_id"], "ACT", f"Refund {refund['refund_id']} started for {refund['amount_inr']}", refund, conn)
        facts = {"amount_inr": refund["amount_inr"], "txn_id": ticket["txn_id"], "refund_id": refund["refund_id"]}
        return _close_case(conn, ticket, "human_approved", "refund_approved", facts, refund["refund_id"])


def reject(ticket_id: str, staff: str) -> dict:
    ticket = _open_ticket(ticket_id)
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _claim(conn, ticket_id, "rejected", staff)
        audit.log(ticket["case_id"], "SAFETY", f"HUMAN REJECTED: {staff} rejected {ticket_id}", conn=conn)
        return _close_case(conn, ticket, "human_rejected", "refund_rejected", {"ticket_id": ticket_id}, None)


def _needs_second_approver(txn: dict) -> bool:
    return txn["amount_paise"] > policy.SECOND_APPROVER_ABOVE_PAISE or bool(policy.untrusted_fields(txn))


def _with_details(ticket: dict) -> dict:
    txn = mock_paytm.get_transaction(ticket["txn_id"]) if ticket["txn_id"] else None
    ticket["rbi"] = rbi.for_transaction(txn) if txn and ticket["status"] == "open" else None
    ticket["refund_blocked_reason"] = _refund_blocked_reason(txn)
    ticket["txn"] = {"amount_inr": txn["amount_inr"], "status": txn["status"], "payee_name": policy.labelled_payee(txn["payee_name"])} if txn else None
    ticket["untrusted_fields"] = policy.untrusted_fields(txn) if txn else []
    ticket["needs_second_approver"] = bool(txn) and _needs_second_approver(txn)
    words = policy.flatten_customer_text(" ".join(message["content"] for message in json.loads(ticket.pop("messages")) if message["role"] == "user"))
    # A message that copies our own ticket labels is trying to pass as our words, so it is not shown.
    ticket["customer_words_hidden"] = policy.copies_ticket_wording(words)
    ticket["customer_words"] = "" if ticket["customer_words_hidden"] else words[:QUOTE_LIMIT] + ("..." if len(words) > QUOTE_LIMIT else "")
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


def _open_ticket(ticket_id: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT k.ticket_id, k.txn_id, k.status, k.first_approver, c.case_id FROM tickets k JOIN cases c ON c.ticket_id = k.ticket_id WHERE k.ticket_id = ?",
            (ticket_id,),
        ).fetchone()
    if row is None:
        raise PaytmError("ticket_not_found", f"No ticket with id {ticket_id}", 404)
    if row["status"] != "open":
        raise PaytmError("ticket_already_decided", f"{ticket_id} has already been decided", 409)
    return dict(row)


def _claim(conn, ticket_id: str, new_status: str, staff: str) -> None:
    """Atomic, so a double-click or two agents cannot decide the same ticket twice."""
    claimed = conn.execute("UPDATE tickets SET status = ?, decided_by = ? WHERE ticket_id = ? AND status = 'open'", (new_status, staff, ticket_id)).rowcount
    if not claimed:
        raise PaytmError("ticket_already_decided", f"{ticket_id} has already been decided", 409)


def _close_case(conn, ticket: dict, status: str, reply_key: str, facts: dict, refund_id: str | None) -> dict:
    messages = json.loads(conn.execute("SELECT messages FROM cases WHERE case_id = ?", (ticket["case_id"],)).fetchone()["messages"])
    reply = agent.reply_text(reply_key, messages, **facts)
    messages.append({"role": "assistant", "content": reply})
    conn.execute(
        "UPDATE cases SET status = ?, messages = ?, reply = ?, refund_id = ?, resolved_at = ? WHERE case_id = ?",
        (status, json.dumps(messages, ensure_ascii=False), reply, refund_id, utc_now(), ticket["case_id"]),
    )
    audit.log(ticket["case_id"], "ACT", "Reply sent to customer", {"reply": reply}, conn)
    return {"ticket_id": ticket["ticket_id"], "case_id": ticket["case_id"], "status": status, "reply": reply, "refund_id": refund_id}
