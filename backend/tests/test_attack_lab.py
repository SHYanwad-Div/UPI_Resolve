"""The attack simulation: every attack must hold, and a broken defence must show as a failure."""
import json

import pytest
from fastapi.testclient import TestClient

from app import attack_lab, db, policy
from app.main import app


def fake_real_ai(messages, tools):
    """Stands in for the real AI so tests spend no credits. It always proposes a refund."""
    text = str(messages)
    for txn_id in ("TXN1027", "TXN1031", "TXN1001"):
        if txn_id in text:
            return attack_lab._call("propose_refund", txn_id=txn_id, reason_code="failed_after_debit")
    return {"content": "Which transaction?"}


@pytest.mark.parametrize("attack", attack_lab.ATTACKS, ids=lambda a: a.title)
def test_every_attack_holds_even_with_an_ai_that_always_proposes_a_refund(fresh_db, monkeypatch, attack):
    result = attack_lab.run_attack(attack, fake_real_ai)
    assert result["passed"], result
    if not attack.is_control:
        assert result["money_moved_paise"] == 0


def test_the_control_proves_real_customers_still_get_refunds(fresh_db):
    control = next(attack for attack in attack_lab.ATTACKS if attack.is_control)
    result = attack_lab.run_attack(control, fake_real_ai)
    assert result["money_moved_inr"] == "₹349.00"


def test_a_broken_defence_shows_as_a_failure_not_a_pass(fresh_db, monkeypatch):
    """The screen must never claim success it did not measure."""
    monkeypatch.setattr(policy, "AUTO_REFUND_LIMIT_PAISE", 10_000_000)
    monkeypatch.setattr(policy, "decide", lambda *args, **kwargs: policy.Decision(()))  # Rules approve everything.
    attack = next(item for item in attack_lab.ATTACKS if item.title == "Fooled AI proposes a forbidden refund")
    with db.get_conn() as conn:
        conn.execute("UPDATE transactions SET status = 'failed_debited' WHERE txn_id = 'TXN1027'")
    result = attack_lab.run_attack(attack, fake_real_ai)
    assert not result["passed"]


def test_the_ai_being_offline_is_reported_and_moves_no_money(fresh_db):
    def offline(messages, tools):
        raise attack_lab.__dict__.get("LLMError", __import__("app.llm", fromlist=["LLMError"]).LLMError)("down")

    control = next(attack for attack in attack_lab.ATTACKS if attack.is_control)
    result = attack_lab.run_attack(control, offline)
    assert result["ai_offline"]
    assert result["money_moved_paise"] == 0
    assert result["passed"]


def by_title(title):
    return next(attack for attack in attack_lab.ATTACKS if attack.title == title)


def test_split_attack_card_shows_only_what_the_ai_really_received(fresh_db):
    result = attack_lab.run_attack(by_title("Split across two messages"), fake_real_ai)
    assert result["ai_got_message"] == "Please ignore"


def test_bunq_style_attacks_come_first():
    assert attack_lab.ATTACKS[0].group == attack_lab.GROUP_HIDDEN
    assert attack_lab.ATTACKS[0].title == "Instructions in a payment note"


def test_bunq_card_shows_the_hidden_text_how_it_was_caught_and_what_the_ai_saw(fresh_db):
    result = attack_lab.run_attack(by_title("Instructions in a payment note"), fake_real_ai)
    assert "SYSTEM NOTE FROM PAYTM COMPLIANCE" in result["hidden_text"]
    assert result["hidden_field"] == "payment note"
    assert result["ai_reached"] and not result["ai_read_hidden"]
    assert any(item["matched"] for item in result["caught"])
    assert any(not check["passed"] and "Hidden instructions" in check["detail"] for check in result["checks"])


def test_card_reports_the_ai_reading_hidden_text_if_it_ever_does(fresh_db, monkeypatch):
    """The 'never reached the AI' line is measured, so a leak must show."""
    fields = ("txn_id", "status", "amount_inr", "created_at", "note")
    monkeypatch.setattr(attack_lab, "ATTACKS", attack_lab.ATTACKS)
    from app import agent, mock_paytm

    monkeypatch.setattr(agent, "_lookup_for_model", lambda txn_id, customer_id: {field: mock_paytm.get_transaction(txn_id)[field] for field in fields})
    script = [attack_lab._call("get_transaction", txn_id="TXN1031"), attack_lab._call("propose_human_handoff", txn_id="TXN1031", reason_code="unclear_request")]
    result = attack_lab.run_attack(by_title("Instructions in a payment note"), lambda messages, tools: script.pop(0))
    assert result["ai_read_hidden"]


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Direct order", "ignore your rules"),
        ("Invisible characters", "invisible characters"),
        ("Fake amount", "₹50,000.00"),
        ("Fooled AI tells a lie from the list", "already refunded"),
        ("Forged ticket wording", "ticket wording"),
        ("PIN and OTP typed in chat", "[removed]"),
        ("Fooled AI calls a refund tool directly", "initiate_refund"),
        ("Fooled AI writes orders to staff", "fixed list"),
    ],
)
def test_each_card_names_what_really_caught_it(fresh_db, title, expected):
    result = attack_lab.run_attack(by_title(title), fake_real_ai)
    assert expected.lower() in json.dumps(result["caught"], ensure_ascii=False).lower()


def test_attack_that_no_detector_flags_is_reported_honestly(fresh_db):
    """Emotional pressure uses no trigger words. The card must not invent a detection."""
    script = [attack_lab._call("propose_refund", txn_id="TXN1027", reason_code="failed_after_debit")]
    result = attack_lab.run_attack(by_title("Emotional pressure, no trigger words"), lambda messages, tools: script.pop(0))
    assert result["caught"] == []
    assert result["passed"]
    assert result["money_moved_paise"] == 0


def test_filter_stopped_attacks_say_the_ai_saw_nothing(fresh_db):
    result = attack_lab.run_attack(by_title("Direct order"), fake_real_ai)
    assert not result["ai_reached"]
    assert result["ai_got_message"] is None


def test_scripted_attacks_show_what_the_ai_was_forced_to_do(fresh_db):
    result = attack_lab.run_attack(by_title("Fooled AI asks for a bigger amount"), fake_real_ai)
    assert "amount=5000000" in result["forced_calls"][0]


def test_simulation_needs_staff_and_demo_mode(fresh_db, sign_in, monkeypatch):
    with TestClient(app) as client:
        assert client.post("/api/attacks/simulate").status_code == 401
        assert client.get("/api/attacks/status").status_code == 401
        sign_in(client)
        monkeypatch.delenv("RESOLVE_DEMO_MODE")
        assert client.post("/api/attacks/simulate").status_code == 403


def test_status_counts_attacks_but_not_the_control(monkeypatch):
    results = [
        {"is_control": False, "passed": True, "money_moved_paise": 0},
        {"is_control": False, "passed": False, "money_moved_paise": 5000},
        {"is_control": True, "passed": True, "money_moved_paise": 34_900},
    ]
    monkeypatch.setitem(attack_lab._state, "results", results)
    status = attack_lab.status()
    assert (status["attacks_run"], status["attacks_stopped"]) == (2, 1)
    assert status["money_moved_by_attacks_inr"] == "₹50.00"
