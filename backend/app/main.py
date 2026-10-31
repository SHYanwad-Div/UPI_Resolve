"""FastAPI app. Run from the project root: uvicorn app.main:app --app-dir backend"""
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import agent, audit, console, outage, ratelimit, staff, views
from app.mock_paytm import PaytmError
from app.seed import ensure_seeded


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_seeded()
    yield


app = FastAPI(title="Resolve", description="AI support teammate for failed UPI payments", lifespan=lifespan)


@app.exception_handler(PaytmError)
async def paytm_error_handler(_: Request, exc: PaytmError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content={"error": exc.code, "message": exc.message})


class ChatRequest(BaseModel):
    customer_id: str
    message: str = Field(max_length=2000)  # Keeps one message from running up the model bill.
    case_id: str | None = None


class LoginRequest(BaseModel):
    name: str
    pin: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --- Customer side. The demo has no customer login: production must prove who is asking. ---

@app.get("/api/customers")
def list_customers() -> list[dict]:
    return views.customers_with_payments()


@app.post("/api/chat")
def chat(body: ChatRequest) -> dict:
    ratelimit.check(body.customer_id)
    return agent.handle_message(body.customer_id, body.message, body.case_id)


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict:
    return views.case_status(case_id)


@app.get("/api/notifications")
def get_notifications(after: int = 0) -> dict:
    return views.notifications_since(after)


@app.get("/api/scoreboard")
def get_scoreboard() -> dict:
    return views.scoreboard()


# --- Staff side. Everything here needs a signed-in person. ---

@app.get("/api/staff")
def list_staff() -> list[str]:
    return staff.names()


@app.post("/api/staff/login")
def staff_login(body: LoginRequest) -> dict:
    return staff.login(body.name, body.pin)


@app.get("/api/audit")
def get_audit(after: int = 0, _: str = Depends(staff.current_staff)) -> dict:
    return audit.since(after)


@app.get("/api/tickets")
def list_tickets(_: str = Depends(staff.current_staff)) -> list[dict]:
    return console.list_tickets()


@app.post("/api/tickets/{ticket_id}/approve")
def approve_ticket(ticket_id: str, name: str = Depends(staff.current_staff)) -> dict:
    return console.approve(ticket_id, name)


@app.post("/api/tickets/{ticket_id}/reject")
def reject_ticket(ticket_id: str, name: str = Depends(staff.current_staff)) -> dict:
    return console.reject(ticket_id, name)


@app.post("/api/outage/simulate")
def simulate_outage(_: str = Depends(staff.current_staff)) -> dict:
    if os.environ.get("RESOLVE_DEMO_MODE") != "1":
        raise PaytmError("demo_only", "The outage simulator only runs in demo mode", 403)
    created = outage.simulate()
    return {**created, "incidents": outage.scan(outages_only=True)}


@app.post("/api/scan")
def scan_for_stuck_payments(_: str = Depends(staff.current_staff)) -> dict:
    return {"incidents": outage.scan()}


@app.get("/api/incidents")
def list_incidents(_: str = Depends(staff.current_staff)) -> list[dict]:
    return outage.list_incidents()


@app.post("/api/incidents/{incident_id}/approve")
def approve_incident(incident_id: str, name: str = Depends(staff.current_staff)) -> dict:
    return outage.approve(incident_id, name)


@app.post("/api/incidents/{incident_id}/hold")
def hold_incident(incident_id: str, name: str = Depends(staff.current_staff)) -> dict:
    return outage.hold(incident_id, name)
