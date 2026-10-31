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
# Small refunds add up, so these cap the totals over any 24 hours. The daily budget is an automatic
# stop: if a bug or fraud produces a flood of "valid" refunds, the damage has a ceiling.
CUSTOMER_DAILY_LIMIT_PAISE = 500_000  # Rs 5,000
DAILY_BUDGET_PAISE = 50_000_000  # Rs 5,00,000
# Above these, one person is not enough: a different second person must also approve.
SECOND_APPROVER_ABOVE_PAISE = 2_500_000  # Rs 25,000
GROUP_SECOND_APPROVER_ABOVE_PAISE = 10_000_000  # Rs 1,00,000


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

    return decide(txn, customer_id, claims_this_week(customer_id), customer_text, refunded_last_day(customer_id), refunded_last_day())


def decide(txn: dict, customer_id: str, claims: int, customer_text: str = "", customer_spent: int = 0, total_spent: int = 0) -> Decision:
    """The rules themselves, with no database access, so a whole outage can be checked at once."""
    txn_id = txn["txn_id"]
    limit = format_inr(AUTO_REFUND_LIMIT_PAISE)
    amount = txn["amount_paise"]
    untrusted = untrusted_fields(txn)
    # Totals only matter for amounts that could auto-refund, so an over-limit payment fails one rule, not three.
    small = amount <= AUTO_REFUND_LIMIT_PAISE
    customer_ok = not small or customer_spent + amount <= CUSTOMER_DAILY_LIMIT_PAISE
    budget_ok = not small or total_spent + amount <= DAILY_BUDGET_PAISE
    return Decision(
        (
            Check("belongs_to_customer", txn["customer_id"] == customer_id, f"{txn_id} belongs to this customer" if txn["customer_id"] == customer_id else f"{txn_id} does not belong to this customer"),
            Check("failed_with_debit", txn["status"] == "failed_debited", f"Status is {txn['status']}"),
            Check("within_limit", amount <= AUTO_REFUND_LIMIT_PAISE, f"Amount {txn['amount_inr']} is {'within' if amount <= AUTO_REFUND_LIMIT_PAISE else 'over'} the {limit} auto-refund limit"),
            Check("no_earlier_refund", txn["refund"] is None, "No earlier refund" if txn["refund"] is None else f"Already refunded as {txn['refund']['refund_id']}"),
            Check("under_claim_limit", claims < CLAIM_LIMIT_PER_WEEK, f"{claims} earlier claim{'' if claims == 1 else 's'} this week (limit: fewer than {CLAIM_LIMIT_PER_WEEK})"),
            Check("amount_matches_complaint", _amount_matches(customer_text, amount), _amount_detail(customer_text, txn)),
            Check("payment_data_clean", not untrusted, f"Hidden instructions found in the {' and '.join(untrusted)}" if untrusted else "No hidden instructions in the payment details"),
            Check("within_customer_daily_limit", customer_ok, f"{format_inr(customer_spent)} refunded to this customer in 24 hours (limit: {format_inr(CUSTOMER_DAILY_LIMIT_PAISE)})"),
            Check("within_daily_budget", budget_ok, f"{format_inr(total_spent)} auto-refunded in 24 hours (automatic stop at {format_inr(DAILY_BUDGET_PAISE)})"),
        )
    )


def refunded_last_day(customer_id: str | None = None) -> int:
    cutoff = to_iso(datetime.now(timezone.utc) - timedelta(days=1))
    sql = "SELECT COALESCE(SUM(r.amount_paise), 0) FROM refunds r JOIN transactions t ON t.txn_id = r.txn_id WHERE r.created_at >= ?"
    params = [cutoff]
    if customer_id:
        sql += " AND t.customer_id = ?"
        params.append(customer_id)
    with get_conn() as conn:
        return conn.execute(sql, params).fetchone()[0]


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
    """Normalised like the input, because Indian scripts can spell one letter in two byte forms.

    DOTALL so a line break cannot hide a phrase from the gaps in these patterns.
    """
    return re.compile(unicodedata.normalize("NFKC", text), re.IGNORECASE | re.DOTALL)


_RULES = r"\b(rules?|instructions?|polic(y|ies)|limits?|checks?|prompts?|guidelines?)\b"
_HINDI_RULES = "(नियम|निर्देश|आदेश)"
_HINDI_IGNORE = "(अनदेखा|भूल|तोड़|छोड़|नज़रअंदाज़|नजरअंदाज)"
_KANNADA_RULES = "(ನಿಯಮ|ಸೂಚನೆ|ಆದೇಶ)"
_KANNADA_IGNORE = "(ನಿರ್ಲಕ್ಷಿಸ|ಮರೆತು|ಮರೆಯಿರಿ|ಬಿಟ್ಟು|ಉಲ್ಲಂಘಿಸ)"
_STAFF = r"\b(compliance|reviewer|risk team|paytm risk|fraud team)\b"
_CLEARED = r"\b(verified|cleared|confirmed|approved?)\b"

# Both word orders count: Hindi and Kannada put the verb last, and Hinglish follows them.
_INJECTION_PATTERNS = (
    ("Asks to ignore rules or instructions", _pattern(rf"\b(ignore|disregard|forget|override|bypass|skip|break)\b.{{0,40}}{_RULES}|{_RULES}.{{0,40}}\b(ignore|disregard|override|bypass|bhool\w*|bhul\w*)\b")),
    ("Tries to change the AI's role", _pattern(r"\b(you are now|act as (a|an|if|my|the)|pretend (to be|you)|developer mode|jailbreak|new instructions)\b")),
    ("Asks about hidden instructions", _pattern(r"\b(system|hidden) (prompt|message|instructions?)\b")),
    ("Claims special authority", _pattern(r"\b(i am|i'm|this is)\b.{0,25}\b(admin|administrator|developer|your manager|paytm (staff|employee|engineer)|rbi officer)\b")),
    ("Claims prior approval", _pattern(r"\b(pre-?approved|already approved|approved by|auto-?approve)\b")),
    ("Claims to speak for our staff", _pattern(rf"{_STAFF}.{{0,40}}{_CLEARED}|{_CLEARED}.{{0,25}}{_STAFF}|\bsafe to approve\b")),
    ("Asks to ignore rules (Hindi)", _pattern(rf"{_HINDI_RULES}.{{0,40}}{_HINDI_IGNORE}|{_HINDI_IGNORE}.{{0,40}}{_HINDI_RULES}")),
    ("Asks to ignore rules (Kannada)", _pattern(rf"{_KANNADA_RULES}.{{0,40}}{_KANNADA_IGNORE}|{_KANNADA_IGNORE}.{{0,40}}{_KANNADA_RULES}")),
    ("Uses look-alike letters", _pattern(r"[Ͱ-ϿЀ-ԯ]")),  # Greek and Cyrillic.
)


# Payee names and notes are written by outsiders. Real ones are short and plain, so anything
# else is treated as a possible attack. This only decides what a human is warned about: the
# model never reads these fields, so a phrase that slips past this list still cannot steer it.
MAX_PAYMENT_TEXT = 40
_DATA_SUSPICIOUS = _pattern(r"\b(system|assistant|compliance|verified|cleared|paytm|approve\w*|ignore|instructions?|prompts?|reviewer|tool|propose_\w+|refund\w*|manzoor|manjoor|turant|manager|rbi|immediately|urgent\w*|pay\s+(now|immediately|full)|full\s+amount)\b|[:{}<>\[\]\"“”]|नियम|निर्देश|मंज़ूर|मंजूर|अनुमोद|तुरंत|ನಿಯಮ|ಸೂಚನೆ|ಅನುಮೋದ|ಮಂಜೂರ|ತಕ್ಷಣ")

# A human reads failure text too, and honest ones are longer than MAX_PAYMENT_TEXT, so this list
# decides what is shown instead. It is not part of untrusted_fields: that would flag every payment.
KNOWN_FAILURES = frozenset(
    {
        "Debited from customer; beneficiary bank timed out before credit",
        "Debited from customer; beneficiary bank unavailable",
        "Insufficient funds (Z9); no money debited",
        "Incorrect UPI PIN (ZM); no money debited",
    }
)
UNKNOWN_FAILURE = "unrecognised failure message hidden"

# The ticket's own labels. A customer has no reason to type these, so a message that does is hidden.
_TICKET_WORDING = _pattern(r"\bai\W{0,2}s?\s+reason\b|sent to a human|customer said|\bwarning\s*:")


def payment_text_is_suspicious(text: str | None) -> bool:
    if not text:
        return False
    normalised = _normalise(text)
    return len(normalised) > MAX_PAYMENT_TEXT or bool(_DATA_SUSPICIOUS.search(normalised)) or any(pattern.search(normalised) for _, pattern in _INJECTION_PATTERNS)


def untrusted_fields(txn: dict) -> list[str]:
    fields = (("payee name", "payee_name"), ("payment note", "note"))
    return [label for label, field in fields if payment_text_is_suspicious(txn.get(field))]


def safe_payee(payee_name: str) -> str:
    return "[suspicious payee name hidden]" if payment_text_is_suspicious(payee_name) else payee_name


# People type secrets into support chats. These must never reach the AI company or be stored.
_SECRET_PATTERNS = (
    re.compile(r"((?:upi\s*)?m?pin|पिन|ಪಿನ್|otp|ओटीपी|ಒಟಿಪಿ|cvv|password|पासवर्ड|ಪಾಸ್‌?ವರ್ಡ್)(\D{0,15})\d{3,8}", re.IGNORECASE),
    re.compile(r"(?<![\d-])(?:\d[ -]?){12,19}(?![\d-])"),  # Card, Aadhaar and long account numbers.
    re.compile(r"(account|a/c|खाता|ಖಾತೆ)(\D{0,15})\d{8,}", re.IGNORECASE),
)


def redact_secrets(text: str) -> tuple[str, bool]:
    """Returns the text with secrets removed, and whether anything was removed.

    Transaction ids are set aside first, so "my PIN for TXN1001" keeps its id,
    while "PIN for TXN1001 is 4821" still loses the PIN.
    """
    ids = []

    def set_aside(match: re.Match) -> str:
        ids.append(match[0])
        return ""

    cleaned = _TXN_ID.sub(set_aside, text)
    cleaned = _SECRET_PATTERNS[0].sub(r"\1\2[removed]", cleaned)
    cleaned = _SECRET_PATTERNS[2].sub(r"\1\2[removed]", cleaned)
    cleaned = _SECRET_PATTERNS[1].sub("[number removed]", cleaned)
    for txn_id in ids:
        cleaned = cleaned.replace("", txn_id, 1)
    return cleaned, cleaned != text


def labelled_payee(payee_name: str) -> str:
    """For staff. Payees pick their own names, so one that passes the screen must still read as theirs."""
    safe = safe_payee(payee_name)
    return f'payee "{safe}" (name unverified)' if safe == payee_name else safe


def safe_failure_reason(text: str) -> str:
    return text if text in KNOWN_FAILURES else UNKNOWN_FAILURE


def copies_ticket_wording(text: str) -> bool:
    return bool(_TICKET_WORDING.search(_normalise(text)))


def flatten_customer_text(text: str) -> str:
    """One plain line with no double quotes, so customer words cannot end the quote around them."""
    return re.sub(r'["“”„‟«»]', "'", " ".join(_normalise(text).split()))


def first_txn_id(text: str) -> str | None:
    match = _TXN_ID.search(_normalise(text))
    return f"TXN{match[1]}" if match else None


def detect_injection(text: str, customer_id: str) -> list[str]:
    """Flags manipulation attempts. This is the first filter, not the safety guarantee.

    A clever attack can get past these patterns. It still cannot get money: the refund API
    takes no amount, and evaluate_refund checks the real transaction whatever the model says.

    Only the customer's own payments are compared with what they demand. Anyone else's is treated
    like an id that does not exist, so a guess cannot reveal another customer's amount.
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
            if recorded["customer_id"] == customer_id and not _amount_matches(normalised, recorded["amount_paise"]):
                flags.append(f"Demands {format_inr(max(demanded))} but {txn_id} is for {recorded['amount_inr']}")
    return flags


def _normalise(text: str) -> str:
    """Stops invisible characters and look-alike letters from hiding a phrase like 'ignore'."""
    return "".join(char for char in unicodedata.normalize("NFKC", text) if unicodedata.category(char) != "Cf")


def _mentioned_amounts(text: str) -> list[int]:
    return [int(Decimal((match[1] or match[2]).replace(",", "")) * 100) for match in _AMOUNT.finditer(text)]


def _amount_matches(text: str, amount_paise: int) -> bool:
    """True if no amount is mentioned, or any mentioned amount is close to the recorded one."""
    mentioned = _mentioned_amounts(_normalise(text))
    return not mentioned or any(abs(value - amount_paise) <= AMOUNT_TOLERANCE_PAISE for value in mentioned)
