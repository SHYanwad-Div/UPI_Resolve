"""HTTP routes for the mock payment APIs. Used by tests only.

The running app does not include these. A live refund route skipped the AI, the rules, the human
and the log, and anyone could call it. Refunds can only happen through agent, console or outage.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from app import mock_paytm

router = APIRouter(prefix="/mock-paytm")


class TicketRequest(BaseModel):
    summary: str
    txn_id: str | None = None
    customer_id: str | None = None


@router.get("/transactions/{txn_id}")
def get_transaction(txn_id: str) -> dict:
    return mock_paytm.get_transaction(txn_id)


@router.post("/transactions/{txn_id}/refund", status_code=201)
def initiate_refund(txn_id: str) -> dict:
    return mock_paytm.initiate_refund(txn_id)


@router.post("/tickets", status_code=201)
def create_ticket(body: TicketRequest) -> dict:
    return mock_paytm.create_ticket(body.summary, body.txn_id, body.customer_id)
