"""The policy engine: plain Python that decides, using only facts from the database.

The LLM proposes and this file disposes. Nothing here reads what the LLM claims about a
transaction, so a confused or manipulated model can only ever cause a handoff to a human.
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app import mock_paytm
from app.db import get_conn, to_iso
from app.mock_paytm import PaytmError, format_inr

AUTO_REFUND_LIMIT_PAISE = 200_000  # Rs 2,000, inclusive.
CLAIM_LIMIT_PER_WEEK = 3  # A customer with this many earlier claims goes to a human.
CLAIM_WINDOW = timedelta(days=7)
AMOUNT_TOLERANCE_PAISE = 100  # People round: "Rs 350" for a Rs 349 payment is not suspicious.


@dataclass(frozen=True)
class Check:
    rule: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Decision:
    checks: tuple[Check, ...]

    @property
    def approved(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failed_reasons(self) -> list[str]:
        return [check.detail for check in self.checks if not check.passed]


def evaluate_refund(txn_id: str, customer_id: str, customer_text: str = "") -> Decision:
    """Runs every rule rather than stopping at the first failure, so a human sees all the reasons."""
    try:
        txn = mock_paytm.get_transaction(txn_id)
    except PaytmError:
        return Decision((Check("transaction_exists", False, f"No transaction with id {txn_id}"),))

    limit = format_inr(AUTO_REFUND_LIMIT_PAISE)
    amount = txn["amount_paise"]
    claims = claims_this_week(customer_id)
    return Decision(
        (
            Check("belongs_to_customer", txn["customer_id"] == customer_id, f"{txn_id} belongs to this customer" if txn["customer_id"] == customer_id else f"{txn_id} does not belong to this customer"),
            Check("failed_with_debit", txn["status"] == "failed_debited", f"Status is {txn['status']}"),
            Check("within_limit", amount <= AUTO_REFUND_LIMIT_PAISE, f"Amount {txn['amount_inr']} is {'within' if amount <= AUTO_REFUND_LIMIT_PAISE else 'over'} the {limit} auto-refund limit"),
            Check("no_earlier_refund", txn["refund"] is None, "No earlier refund" if txn["refund"] is None else f"Already refunded as {txn['refund']['refund_id']}"),
            Check("under_claim_limit", claims < CLAIM_LIMIT_PER_WEEK, f"{claims} earlier claim{'' if claims == 1 else 's'} this week (limit: fewer than {CLAIM_LIMIT_PER_WEEK})"),
            Check("amount_matches_complaint", _amount_matches(customer_text, amount), _amount_detail(customer_text, txn)),
        )
    )


def _amount_detail(customer_text: str, txn: dict) -> str:
    if not _mentioned_amounts(_normalise(customer_text)):
        return "Customer did not state an amount"
    matches = _amount_matches(customer_text, txn["amount_paise"])
    return f"Customer's stated amount {'matches' if matches else 'does not match'} the recorded {txn['amount_inr']}"


def claims_this_week(customer_id: str) -> int:
    cutoff = to_iso(datetime.now(timezone.utc) - CLAIM_WINDOW)
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM claims WHERE customer_id = ? AND created_at >= ?", (customer_id, cutoff)).fetchone()[0]


# --- Reading the customer's text ---

_TXN_ID = re.compile(r"\bTXN[\s-]*(\d+)\b", re.IGNORECASE)

_CURRENCY = r"(?:₹|rs\.?|inr|rupees?|रुपये|रुपए|रु\.?|ರೂಪಾಯಿ(?:ಗಳು)?|ರೂ\.?)"
_NUMBER = r"(\d[\d,]*(?:\.\d{1,2})?)"
# The lookbehinds stop "TXN1001 Rs" reading as Rs 1001, and "hers 500" as Rs 500.
_AMOUNT = re.compile(rf"(?<![a-z0-9]){_CURRENCY}\s*{_NUMBER}|(?<![a-z0-9]){_NUMBER}\s*{_CURRENCY}", re.IGNORECASE)

# Narrow on purpose: "I tried to pay Rs 5,000" and "my transfer failed" are honest complaints.
_DEMAND = re.compile(r"\b(refund|return|credit)\b|\b(send|give|pay)\s+me\b|\btransfer\b.{0,30}\bto\s+(me|my)\b|वापस|रिफंड|ಮರುಪಾವತಿ|ಹಿಂದಿರುಗಿಸ|ವಾಪಸ್", re.IGNORECASE)


def _pattern(text: str) -> re.Pattern:
    """Normalised like the input, because Indian scripts can spell one letter in two byte forms."""
    return re.compile(unicodedata.normalize("NFKC", text), re.IGNORECASE)


_INJECTION_PATTERNS = (
    ("Asks to ignore rules or instructions", _pattern(r"\b(ignore|disregard|forget|override|bypass|skip|break)\b.{0,40}\b(rules?|instructions?|polic(y|ies)|limits?|checks?|prompts?|guidelines?)\b")),
    ("Tries to change the AI's role", _pattern(r"\b(you are now|act as (a|an|if|my|the)|pretend (to be|you)|developer mode|jailbreak|new instructions)\b")),
    ("Asks about hidden instructions", _pattern(r"\b(system|hidden) (prompt|message|instructions?)\b")),
    ("Claims special authority", _pattern(r"\b(i am|i'm|this is)\b.{0,25}\b(admin|administrator|developer|your manager|paytm (staff|employee|engineer)|rbi officer)\b")),
    ("Claims prior approval", _pattern(r"\b(pre-?approved|already approved|approved by|auto-?approve)\b")),
    ("Asks to ignore rules (Hindi)", _pattern(r"(नियम|निर्देश).{0,40}(अनदेखा|भूल|तोड़|छोड़|नज़रअंदाज़|नजरअंदाज)")),
    ("Asks to ignore rules (Kannada)", _pattern(r"(ನಿಯಮ|ಸೂಚನೆ).{0,40}(ನಿರ್ಲಕ್ಷಿಸ|ಮರೆತು|ಮರೆಯಿರಿ|ಬಿಟ್ಟು|ಉಲ್ಲಂಘಿಸ)")),
)


def first_txn_id(text: str) -> str | None:
    match = _TXN_ID.search(_normalise(text))
    return f"TXN{match[1]}" if match else None


def detect_injection(text: str) -> list[str]:
    """Flags manipulation attempts. This is the first filter, not the safety guarantee.

    A clever attack can get past these patterns. It still cannot get money: the refund API
    takes no amount, and evaluate_refund checks the real transaction whatever the model says.
    """
    normalised = _normalise(text)
    flags = [label for label, pattern in _INJECTION_PATTERNS if pattern.search(normalised)]

    demanded = _mentioned_amounts(normalised)
    if demanded and _DEMAND.search(normalised):
        txn_ids = [f"TXN{number}" for number in _TXN_ID.findall(normalised)]
        if not txn_ids and max(demanded) > AUTO_REFUND_LIMIT_PAISE:
            flags.append(f"Demands {format_inr(max(demanded))} without naming a transaction")
        for txn_id in txn_ids:
            try:
                recorded = mock_paytm.get_transaction(txn_id)
            except PaytmError:
                continue
            if not _amount_matches(normalised, recorded["amount_paise"]):
                flags.append(f"Demands {format_inr(max(demanded))} but {txn_id} is for {recorded['amount_inr']}")
    return flags


def _normalise(text: str) -> str:
    """Stops invisible characters and look-alike letters from hiding a phrase like 'ignore'."""
    return re.sub(r"[​-‍⁠﻿]", "", unicodedata.normalize("NFKC", text))


def _mentioned_amounts(text: str) -> list[int]:
    return [int(Decimal((match[1] or match[2]).replace(",", "")) * 100) for match in _AMOUNT.finditer(text)]


def _amount_matches(text: str, amount_paise: int) -> bool:
    """True if no amount is mentioned, or any mentioned amount is close to the recorded one."""
    mentioned = _mentioned_amounts(_normalise(text))
    return not mentioned or any(abs(value - amount_paise) <= AMOUNT_TOLERANCE_PAISE for value in mentioned)
