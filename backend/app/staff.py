"""Staff sign-in, so every human decision has a name on it and strangers cannot make one.

Demo-grade: PINs come from backend/.env and sessions live in memory. Production needs the firm's
real identity system. It fails closed: with no PINs configured, nobody can sign in.
"""
import hmac
import os
import secrets
import time

from fastapi import Header

from app.mock_paytm import PaytmError

SESSION_SECONDS = 8 * 60 * 60
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300

_sessions: dict[str, tuple[str, float]] = {}
_failures: dict[str, tuple[int, float]] = {}


def _pins() -> dict[str, str]:
    pairs = (item.split(":", 1) for item in os.environ.get("RESOLVE_STAFF_PINS", "").split(",") if ":" in item)
    return {name.strip(): pin.strip() for name, pin in pairs}


def names() -> list[str]:
    return sorted(_pins())


def login(name: str, pin: str) -> dict:
    count, locked_until = _failures.get(name, (0, 0.0))
    if time.time() < locked_until:
        raise PaytmError("locked_out", "Too many wrong PINs. Try again in a few minutes.", 429)

    # compare_digest takes the same time wherever the PINs differ, so timing reveals nothing.
    expected = _pins().get(name)
    if expected is None or not hmac.compare_digest(expected, pin):
        count += 1
        _failures[name] = (count, time.time() + LOCKOUT_SECONDS if count >= MAX_FAILURES else 0.0)
        raise PaytmError("bad_login", "Wrong name or PIN", 401)

    _failures.pop(name, None)
    token = secrets.token_urlsafe(32)
    _sessions[token] = (name, time.time() + SESSION_SECONDS)
    return {"token": token, "name": name}


def current_staff(authorization: str = Header(default="")) -> str:
    """A FastAPI dependency: any route that uses it refuses callers who are not signed in."""
    token = authorization.removeprefix("Bearer ").strip()
    session = _sessions.get(token)
    if session is None or time.time() > session[1]:
        raise PaytmError("not_signed_in", "Staff sign-in is required", 401)
    return session[0]


def reset() -> None:
    _sessions.clear()
    _failures.clear()
