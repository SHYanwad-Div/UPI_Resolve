"""Try the agent from a terminal, run from backend/:

    python -m app.cli C01 "My payment TXN1001 failed but money was debited"
    python -m app.cli C01 "It is TXN1001" --case CASE-AB12CD
"""
import argparse
import json
import sys

from app import agent, audit, seed


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Send one complaint through Resolve and print every step.")
    parser.add_argument("customer", help="Customer id, for example C01")
    parser.add_argument("message", help="What the customer says")
    parser.add_argument("--case", help="Continue a case that is waiting for the customer")
    args = parser.parse_args()

    seed.ensure_seeded()
    result = agent.handle_message(args.customer, args.message, args.case)

    for step in audit.for_case(result["case_id"]):
        print(f"{step['created_at'][11:23]}  {step['stage']:<6}  {step['event']}")
        for check in (step["detail"] or {}).get("checks", []):
            print(f"{'':>21}{'PASS' if check['passed'] else 'FAIL'}  {check['detail']}")

    print(f"\nCase:   {result['case_id']}")
    print(f"Status: {result['status']}")
    print(f"Reply:  {result['reply']}")
    print(json.dumps({"refund_id": result["refund_id"], "ticket_id": result["ticket_id"]}))


if __name__ == "__main__":
    main()
