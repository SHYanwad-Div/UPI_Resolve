"""FastAPI app. Run from the project root: uvicorn app.main:app --app-dir backend"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import agent, audit, console, mock_paytm, outage, views
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


class TicketRequest(BaseModel):
    summary: str
    txn_id: str | None = None
    customer_id: str | None = None


class ChatRequest(BaseModel):
    customer_id: str
    message: str = Field(max_length=2000)  # Keeps one message from running up the model bill.
    case_id: str | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --- Mock Paytm APIs ---

@app.get("/mock-paytm/transactions/{txn_id}")
def get_transaction(txn_id: str) -> dict:
    return mock_paytm.get_transaction(txn_id)


@app.post("/mock-paytm/transactions/{txn_id}/refund", status_code=201)
def initiate_refund(txn_id: str) -> dict:
    return mock_paytm.initiate_refund(txn_id)


@app.post("/mock-paytm/tickets", status_code=201)
def create_ticket(body: TicketRequest) -> dict:
    return mock_paytm.create_ticket(body.summary, body.txn_id, body.customer_id)


# --- What the React UI calls ---

@app.get("/api/customers")
def list_customers() -> list[dict]:
    return views.customers_with_payments()


@app.post("/api/chat")
def chat(body: ChatRequest) -> dict:
    return agent.handle_message(body.customer_id, body.message, body.case_id)


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict:
    return views.case_status(case_id)


@app.get("/api/audit")
def get_audit(after: int = 0) -> dict:
    return audit.since(after)


@app.get("/api/tickets")
def list_tickets() -> list[dict]:
    return console.list_tickets()


@app.post("/api/tickets/{ticket_id}/approve")
def approve_ticket(ticket_id: str) -> dict:
    return console.approve(ticket_id)


@app.post("/api/tickets/{ticket_id}/reject")
def reject_ticket(ticket_id: str) -> dict:
    return console.reject(ticket_id)


@app.post("/api/outage/simulate")
def simulate_outage() -> dict:
    created = outage.simulate()
    return {**created, "incidents": outage.scan(outages_only=True)}


@app.post("/api/scan")
def scan_for_stuck_payments() -> dict:
    return {"incidents": outage.scan()}


@app.get("/api/incidents")
def list_incidents() -> list[dict]:
    return outage.list_incidents()


@app.post("/api/incidents/{incident_id}/approve")
def approve_incident(incident_id: str) -> dict:
    return outage.approve(incident_id)


@app.post("/api/incidents/{incident_id}/hold")
def hold_incident(incident_id: str) -> dict:
    return outage.hold(incident_id)


@app.get("/api/notifications")
def get_notifications(after: int = 0) -> dict:
    return views.notifications_since(after)


@app.get("/api/scoreboard")
def get_scoreboard() -> dict:
    return views.scoreboard()
