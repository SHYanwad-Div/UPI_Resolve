"""Stops one customer flooding the system, which would waste AI credits and bury staff in tickets."""
import time
from collections import defaultdict, deque

from app.db import get_conn
from app.mock_paytm import PaytmError

MAX_MESSAGES_PER_MINUTE = 6
MAX_OPEN_TICKETS = 5

_recent: dict[str, deque] = defaultdict(deque)


def check(customer_id: str) -> None:
    now = time.time()
    recent = _recent[customer_id]
    while recent and now - recent[0] > 60:
        recent.popleft()
    if len(recent) >= MAX_MESSAGES_PER_MINUTE:
        raise PaytmError("too_many_messages", "Too many messages. Please wait a minute and try again.", 429)

    with get_conn() as conn:
        open_tickets = conn.execute("SELECT COUNT(*) FROM tickets WHERE customer_id = ? AND status = 'open'", (customer_id,)).fetchone()[0]
    if open_tickets >= MAX_OPEN_TICKETS:
        raise PaytmError("too_many_tickets", "Our specialists already have your open cases and will reply soon.", 429)
    recent.append(now)


def reset() -> None:
    _recent.clear()
