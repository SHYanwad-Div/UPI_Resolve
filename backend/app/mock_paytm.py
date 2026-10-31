"""Mock Paytm payment APIs. No real money moves: every action is a row in SQLite.

These three functions are the only way the rest of Resolve touches payments, so
connecting real Paytm APIs later means replacing this one file.

This layer knows what is physically possible (you cannot refund a payment that never
debited, or refund twice). What is *allowed* (the Rs 2,000 limit, repeat claims) belongs
to the policy engine, because a human agent can still approve a Rs 50,000 refund.
"""
import sqlite3
from uuid import uuid4

from app.db import get_conn, utc_now


class PaytmError(Exception):
    def __init__(self, code: str, message: str, http_status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _txn_not_found(txn_id: str) -> PaytmError:
    return PaytmError("txn_not_found", f"No transaction with id {txn_id}", 404)


def format_inr(paise: int) -> str:
    """Indian digit grouping: ₹6,38,760.00, not ₹638,760.00."""
    rupees, remainder = divmod(paise, 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while head:
            groups.insert(0, head[-2:])
            head = head[:-2]
        digits = ",".join([*groups, tail])
    return f"₹{digits}.{remainder:02d}"


def get_transaction(txn_id: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT t.*, c.name AS customer_name, c.vpa AS customer_vpa, c.language AS customer_language,
                   r.refund_id, r.created_at AS refunded_at
            FROM transactions t
            JOIN customers c ON c.customer_id = t.customer_id
            LEFT JOIN refunds r ON r.txn_id = t.txn_id
            WHERE t.txn_id = ?
            """,
            (txn_id,),
        ).fetchone()
    if row is None:
        raise _txn_not_found(txn_id)

    txn = dict(row)
    refund_id, refunded_at = txn.pop("refund_id"), txn.pop("refunded_at")
    txn["amount_inr"] = format_inr(txn["amount_paise"])
    txn["refund"] = {"refund_id": refund_id, "refunded_at": refunded_at} if refund_id else None
    return txn


def initiate_refund(txn_id: str, conn=None) -> dict:
    """Pass conn to make the refund part of a larger all-or-nothing database transaction."""
    if conn is None:
        with get_conn() as own_conn:
            return initiate_refund(txn_id, own_conn)

    refund = {"refund_id": f"RFD-{uuid4().hex[:8].upper()}", "txn_id": txn_id, "created_at": utc_now()}
    txn = conn.execute("SELECT status, amount_paise FROM transactions WHERE txn_id = ?", (txn_id,)).fetchone()
    if txn is None:
        raise _txn_not_found(txn_id)
    if txn["status"] != "failed_debited":
        raise PaytmError("not_refundable", f"{txn_id} has status {txn['status']}; only failed_debited can be refunded", 422)

    refund["amount_paise"] = txn["amount_paise"]
    refund["amount_inr"] = format_inr(txn["amount_paise"])
    # Insert and catch the UNIQUE error instead of checking first: with a check,
    # two simultaneous requests could both see "no refund yet" and both pay out.
    try:
        conn.execute(
            "INSERT INTO refunds (refund_id, txn_id, amount_paise, created_at) VALUES (?, ?, ?, ?)",
            (refund["refund_id"], txn_id, refund["amount_paise"], refund["created_at"]),
        )
    except sqlite3.IntegrityError:
        raise PaytmError("already_refunded", f"{txn_id} has already been refunded", 409) from None
    return refund


def initiate_refunds(txn_ids: list[str], conn) -> dict[str, dict]:
    """A whole approved group inside the caller's database transaction. Skips anything not refundable."""
    refunds = {}
    for txn_id in txn_ids:
        txn = conn.execute(
            "SELECT amount_paise FROM transactions WHERE txn_id = ? AND status = 'failed_debited' AND txn_id NOT IN (SELECT txn_id FROM refunds)",
            (txn_id,),
        ).fetchone()
        if txn is None:
            continue
        refund_id = f"RFD-{uuid4().hex[:8].upper()}"
        conn.execute(
            "INSERT INTO refunds (refund_id, txn_id, amount_paise, created_at) VALUES (?, ?, ?, ?)",
            (refund_id, txn_id, txn["amount_paise"], utc_now()),
        )
        refunds[txn_id] = {"refund_id": refund_id, "amount_paise": txn["amount_paise"], "amount_inr": format_inr(txn["amount_paise"])}
    return refunds


def create_ticket(summary: str, txn_id: str | None = None, customer_id: str | None = None) -> dict:
    summary = summary.strip()
    if not summary:
        raise PaytmError("empty_summary", "A ticket needs a summary", 422)

    ticket = {"ticket_id": f"TKT-{uuid4().hex[:6].upper()}", "summary": summary, "status": "open", "created_at": utc_now()}
    with get_conn() as conn:
        if txn_id:
            txn = conn.execute("SELECT customer_id FROM transactions WHERE txn_id = ?", (txn_id,)).fetchone()
            if txn is None:
                raise _txn_not_found(txn_id)
            customer_id = customer_id or txn["customer_id"]
        if customer_id and conn.execute("SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,)).fetchone() is None:
            raise PaytmError("customer_not_found", f"No customer with id {customer_id}", 404)

        ticket |= {"txn_id": txn_id, "customer_id": customer_id}
        conn.execute(
            "INSERT INTO tickets (ticket_id, summary, txn_id, customer_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ticket["ticket_id"], summary, txn_id, customer_id, ticket["status"], ticket["created_at"]),
        )
    return ticket
