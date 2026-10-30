"""RBI's deadline for reversing a UPI payment that debited the customer but did not complete.

From circular RBI/2019-20/67, annex row 4: a transfer to a person must be reversed by T+1 and a
merchant payment by T+5, where T is the calendar date of the transaction. After that, the
customer is owed Rs 100 per day, paid without them needing to complain.
"""
from datetime import datetime, time, timedelta, timezone

from app.db import to_iso

IST = timezone(timedelta(hours=5, minutes=30))
DAYS_ALLOWED = {"p2p": 1, "p2m": 5}
COMPENSATION_PER_DAY_INR = 100


def reversal_deadline(created_at: str, payment_type: str) -> str:
    """The end of the last allowed calendar day. Calendar days are Indian ones, so this uses IST."""
    last_day = datetime.fromisoformat(created_at).astimezone(IST).date() + timedelta(days=DAYS_ALLOWED[payment_type])
    return to_iso(datetime.combine(last_day, time.max, tzinfo=IST))


def for_transaction(txn: dict) -> dict | None:
    """None unless the customer's money is actually stuck, because only then is a clock running."""
    if txn["status"] != "failed_debited" or txn["refund"]:
        return None
    return {
        "deadline": reversal_deadline(txn["created_at"], txn["payment_type"]),
        "rule": f"T+{DAYS_ALLOWED[txn['payment_type']]}",
        "kind": "transfer" if txn["payment_type"] == "p2p" else "merchant payment",
        "compensation_per_day_inr": COMPENSATION_PER_DAY_INR,
    }
