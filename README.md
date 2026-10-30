# Resolve

An AI support teammate by Team Ghost Ops that resolves failed UPI payment complaints end to end.
Built for the Paytm Build for India AI Hackathon, Track 3: Autonomous AI Teammates.

The AI proposes, a plain Python rules engine approves, and every action is logged. No real money moves.

## Setup

Requires Python 3.13 and Node 24. Run from the project root:

```bash
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements.txt
npm --prefix frontend install
```

Copy `.env.example` to `backend/.env` and add your Sarvam API key. Git ignores that file.

## Run the app

Start these in two separate terminals, then open http://127.0.0.1:5173

```bash
backend/.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000
```

```bash
npm --prefix frontend run dev
```

Keep the page's tab in front while presenting: browsers slow down background tabs, so the live log can lag behind.

## Try the agent

Sends one complaint through the real model and prints every SENSE, AI, SAFETY and ACT step. Run from `backend/`:

```bash
.venv/Scripts/python -m app.cli C01 "My payment TXN1001 failed but the money was debited"
```

The first argument is the customer. Reset the demo (below) to see the cheat sheet of who owns which transaction.

## Try the APIs directly

With the backend running, open http://127.0.0.1:8000/docs. The database seeds itself on first run.

Use `127.0.0.1`, not `localhost`. On Windows, `localhost` can add about 2 seconds to every call.

## Reset the demo

Reloads the 30 transactions and prints a cheat sheet of what each one should do. Safe while the server is running.

```bash
cd backend && .venv/Scripts/python -m app.seed
```

Run this just before a demo, because seeded dates are relative to the moment of seeding. Then reload the page to clear the chat.

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

Anything the policy engine does not approve goes to the human console. A human may approve a refund the rules would not, such as ₹15,000, but cannot refund a payment that never debited the customer or was already refunded.

## RBI deadline clock

The console puts the most urgent case first, using RBI's rules for a UPI payment that debited the customer but did not complete (circular RBI/2019-20/67, annex row 4): a transfer must be reversed by T+1 and a merchant payment by T+5, where T is the calendar date of the transaction. After that the customer is owed ₹100 per day. The clock only runs while the customer's money is actually stuck.

The console has no login, because this is a demo.

## Mock Paytm APIs

| Function | Route | Refuses when |
| --- | --- | --- |
| `get_transaction(txn_id)` | `GET /mock-paytm/transactions/{txn_id}` | Transaction not found |
| `initiate_refund(txn_id)` | `POST /mock-paytm/transactions/{txn_id}/refund` | Not found, already refunded, or status is not `failed_debited` |
| `create_ticket(summary)` | `POST /mock-paytm/tickets` | Summary is blank, or the transaction or customer is not found |
