# Resolve

An AI support teammate by Team Ghost Ops that resolves failed UPI payment complaints end to end.
Built for the Paytm Build for India AI Hackathon, Track 3: Autonomous AI Teammates.

The AI proposes, a plain Python rules engine approves, and every action is logged. No real money moves.

## Setup

Requires Python 3.13. Run from the project root:

```bash
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements.txt
```

Copy `.env.example` to `backend/.env` and add your Sarvam API key. Git ignores that file.

## Try the agent

Sends one complaint through the real model and prints every SENSE, AI, SAFETY and ACT step. Run from `backend/`:

```bash
.venv/Scripts/python -m app.cli C01 "My payment TXN1001 failed but the money was debited"
```

The first argument is the customer. Reset the demo (below) to see the cheat sheet of who owns which transaction.

## Run the backend

```bash
backend/.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000
```

Open http://127.0.0.1:8000/docs to try the APIs. The database seeds itself on first run.

Use `127.0.0.1`, not `localhost`. On Windows, `localhost` can add about 2 seconds to every call.

## Reset the demo

Reloads the 30 transactions and prints a cheat sheet of what each one should do. Safe while the server is running.

```bash
cd backend && .venv/Scripts/python -m app.seed
```

Run this just before a demo: seeded dates are relative to the moment of seeding.

## Run the tests

```bash
backend/.venv/Scripts/python -m pytest backend -q
```

## How a decision is made

1. **SENSE:** the complaint arrives. Obvious manipulation is blocked here and never reaches the model.
2. **AI:** the model can look up the customer's own transactions and propose a refund or a human handoff. No tool it can call moves money.
3. **SAFETY:** `policy.py` decides from database facts: the payment failed after debit, it is ₹2,000 or less, it has no earlier refund, the customer has fewer than 3 claims this week, it belongs to this customer, and any amount they state matches the record.
4. **ACT:** the refund or ticket is created and the customer gets a reply from fixed, reviewed text.

Every step is written to an append-only audit log.

## Mock Paytm APIs

| Function | Route | Refuses when |
| --- | --- | --- |
| `get_transaction(txn_id)` | `GET /mock-paytm/transactions/{txn_id}` | Transaction not found |
| `initiate_refund(txn_id)` | `POST /mock-paytm/transactions/{txn_id}/refund` | Not found, already refunded, or status is not `failed_debited` |
| `create_ticket(summary)` | `POST /mock-paytm/tickets` | Summary is blank, or the transaction or customer is not found |
