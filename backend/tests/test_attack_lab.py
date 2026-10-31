"""The attack simulation: every attack must hold, and a broken defence must show as a failure."""
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
