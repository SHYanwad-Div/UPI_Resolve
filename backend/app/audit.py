"""Append-only decision log: every step of every case, tagged SENSE, AI, SAFETY or ACT."""
import json

from app.db import get_conn, utc_now


def log(case_id: str, stage: str, event: str, detail: dict | None = None) -> None:
    payload = json.dumps(detail, ensure_ascii=False) if detail is not None else None
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (case_id, stage, event, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (case_id, stage, event, payload, utc_now()),
        )


def for_case(case_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM audit_log WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
    return [{**dict(row), "detail": json.loads(row["detail"]) if row["detail"] else None} for row in rows]
