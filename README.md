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

The database seeds itself on first run. Staff sign in with a name and PIN from `RESOLVE_STAFF_PINS` in `backend/.env`.

Use `127.0.0.1`, not `localhost`. On Windows, `localhost` can add about 2 seconds to every call.

## Reset the demo

Reloads the 31 transactions and prints a cheat sheet of what each one should do. Safe while the server is running.

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

## Outage mode

Failed payments arrive in waves when a bank has a problem, so Resolve treats a wave as one incident instead of thousands of tickets. "Simulate bank outage" creates 303 failed payments at a fictional bank, and "Scan for stuck payments" finds any other stuck money nobody has complained about.

1. **SENSE:** plain counting spots the spike. Status is checked once per incident, not once per customer.
2. **AI:** the model sees only numbers and picks a likely cause and action from fixed lists.
3. **SAFETY:** the same policy rules sort every payment into routine or needs-a-person.
4. **ACT:** every customer is told first in their language, with a warning about fake helplines. One human approval then starts the routine refunds, and the rules run again first.

The outage is simulated, and the ₹ saved figure assumes ₹100 per human ticket and ₹10 per AI ticket.

## Protection against prompt injection

Instructions can be hidden in what a customer types, and also in data the agent reads, like a payee name or payment note. Filters can miss attacks, so Resolve limits what a fooled model can do:

- **It cannot move money.** No tool it can call does that, and the refund API takes no amount.
- **It cannot write to people.** It picks reasons from a fixed list, and customers get reviewed text.
- **It does not read outsiders' text.** Payee names and notes never reach the model.

Text that looks like instructions is also flagged: it blocks auto-refund, is hidden from staff, and shows them a warning. This is not a guarantee against every attack.

## Attack simulation

The **Simulate attacks** button opens the Prompt injection dashboard. It runs 18 attacks, plus one honest customer as a control, through the real system in about 15 seconds. Each card shows the exact injection, what caught it and the words it matched, what the AI actually received, every rule check, and the money moved. Results are measured: a defence that fails shows as a failure, and an attack no detector flagged says so.

It runs in a separate process on a throwaway database, so the dashboard and scoreboard don't change. Some attacks use the real AI. Others use a scripted AI forced to misbehave, to show the rules hold even if the AI is fully fooled. Passing shows these attacks fail, not that every possible attack will.

## Test script

Runs 10 scripted complaints through the real model, on a throwaway database, and prints how many needed no human:

```bash
backend/.venv/Scripts/python backend/tests/run_10_cases.py
```

We wrote these complaints, so the result shows the system works. It does not measure a real-world auto-resolve rate.

## RBI deadline clock

The console puts the most urgent case first, using RBI's rules for a UPI payment that debited the customer but did not complete (circular RBI/2019-20/67, annex row 4): a transfer must be reversed by T+1 and a merchant payment by T+5, where T is the calendar date of the transaction. After that the customer is owed ₹100 per day. The clock only runs while the customer's money is actually stuck.

## Money controls

We attacked our own system, found loopholes, and closed these:

- **Signed-in, named staff:** every approval records who made it. There is no public refund route.
- **Two people:** refunds over ₹25,000, flagged refunds, and groups over ₹1,00,000 need two different people.
- **Limits:** ₹5,000 per customer in 24 hours, 3 claims a week checked in one atomic step, and an automatic stop at ₹5,00,000 a day. These amounts are our demo choices.
- **Money and records together:** a refund and its log entry are saved together or not at all.
- **Secrets removed:** PINs, OTPs, card and account numbers are removed before the AI, log or staff see them.
- **Flood limits:** 6 messages a minute and 5 open tickets per customer.
- **Untrusted words shown apart:** customers' words sit outside the summary, labelled unverified.

**Not solved, and needed before real money:** real customer login (the demo's chat trusts the customer ID), the firm's real staff identity system, comparing refunds with bank records to catch double payment, a tamper-proof log (anyone with database access can still erase it), and an outside security review.

## Mock Paytm APIs

| Function | Route | Refuses when |
| --- | --- | --- |
| `get_transaction(txn_id)` | `GET /mock-paytm/transactions/{txn_id}` | Transaction not found |
| `initiate_refund(txn_id)` | `POST /mock-paytm/transactions/{txn_id}/refund` | Not found, already refunded, or status is not `failed_debited` |
| `create_ticket(summary)` | `POST /mock-paytm/tickets` | Summary is blank, or the transaction or customer is not found |
