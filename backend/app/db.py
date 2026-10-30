"""SQLite connection and schema for Resolve."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("RESOLVE_DB_PATH", Path(__file__).resolve().parents[1] / "resolve.db"))

# Money is stored as integer paise, never float. In floating point 0.1 + 0.2 != 0.3,
# and a rule like "amount <= Rs 2,000" must not depend on rounding.
#
# refunds.txn_id is UNIQUE so the database itself refuses a second refund for the
# same transaction, even if a bug elsewhere in the code tries to issue one.
SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    vpa         TEXT NOT NULL UNIQUE,
    language    TEXT NOT NULL CHECK (language IN ('en', 'hi', 'kn'))
);

CREATE TABLE IF NOT EXISTS transactions (
    txn_id         TEXT PRIMARY KEY,
    customer_id    TEXT NOT NULL REFERENCES customers (customer_id),
    payee_name     TEXT NOT NULL,
    payee_vpa      TEXT NOT NULL,
    amount_paise   INTEGER NOT NULL CHECK (amount_paise > 0),
    status         TEXT NOT NULL CHECK (status IN ('success', 'pending', 'failed_debited', 'failed_no_debit')),
    failure_reason TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refunds (
    refund_id    TEXT PRIMARY KEY,
    txn_id       TEXT NOT NULL UNIQUE REFERENCES transactions (txn_id),
    amount_paise INTEGER NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL REFERENCES customers (customer_id),
    txn_id      TEXT NOT NULL REFERENCES transactions (txn_id),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id   TEXT PRIMARY KEY,
    summary     TEXT NOT NULL,
    txn_id      TEXT REFERENCES transactions (txn_id),
    customer_id TEXT REFERENCES customers (customer_id),
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'approved', 'rejected')),
    created_at  TEXT NOT NULL
);
"""

# Children before parents, so foreign keys stay valid while dropping.
TABLES = ("tickets", "claims", "refunds", "transactions", "customers")


def utc_now() -> str:
    """Timestamps are stored in UTC; the UI converts to IST for display."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn():
    """Yield a connection that commits on success and rolls back on any error."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite leaves foreign keys off by default.
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_schema() -> None:
    with get_conn() as conn:
        # WAL lets the UI read the decision log while the agent is writing to it.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)


def reset_schema() -> None:
    """Drop and recreate every table. Works while the server is running, unlike deleting the file."""
    with get_conn() as conn:
        for table in TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    init_schema()
