"""Append-only decision log: every step of every case, tagged SENSE, AI, SAFETY or ACT."""
import json

from app.db import get_conn, utc_now


def log(case_id: str, stage: str, event: str, detail: dict | None = None, conn=None) -> None:
    """Pass conn to save this entry together with the money movement it describes."""
    payload = json.dumps(detail, ensure_ascii=False) if detail is not None else None
    sql = "INSERT INTO audit_log (case_id, stage, event, detail, created_at) VALUES (?, ?, ?, ?, ?)"
    values = (case_id, stage, event, payload, utc_now())
    if conn is not None:
        conn.execute(sql, values)
        return
    with get_conn() as own_conn:
        own_conn.execute(sql, values)


def since(after_id: int) -> dict:
    """New entries for the live log. latest_id lets the UI notice the demo was reset."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT a.*, cu.name AS customer_name
            FROM audit_log a
            JOIN cases c ON c.case_id = a.case_id
            JOIN customers cu ON cu.customer_id = c.customer_id
            WHERE a.id > ?
            ORDER BY a.id
            LIMIT 500
            """,
            (after_id,),
        ).fetchall()
        latest_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM audit_log").fetchone()[0]
    entries = [{**dict(row), "detail": json.loads(row["detail"]) if row["detail"] else None} for row in rows]
    return {"entries": entries, "latest_id": latest_id}


def for_case(case_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM audit_log WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
    return [{**dict(row), "detail": json.loads(row["detail"]) if row["detail"] else None} for row in rows]
