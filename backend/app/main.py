"""FastAPI app. Run from the project root: uvicorn app.main:app --app-dir backend"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import mock_paytm
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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/mock-paytm/transactions/{txn_id}")
def get_transaction(txn_id: str) -> dict:
    return mock_paytm.get_transaction(txn_id)


@app.post("/mock-paytm/transactions/{txn_id}/refund", status_code=201)
def initiate_refund(txn_id: str) -> dict:
    return mock_paytm.initiate_refund(txn_id)


@app.post("/mock-paytm/tickets", status_code=201)
def create_ticket(body: TicketRequest) -> dict:
    return mock_paytm.create_ticket(body.summary, body.txn_id, body.customer_id)
