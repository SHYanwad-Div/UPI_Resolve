import pytest

from app import db, llm, ratelimit, seed, staff


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """No test may spend API credits. Tests that need a model install a scripted fake."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("A test tried to call the real LLM")

    monkeypatch.setattr(llm, "chat", refuse)


@pytest.fixture(autouse=True)
def test_settings(monkeypatch):
    monkeypatch.setenv("RESOLVE_STAFF_PINS", "asha:1111,ravi:2222")
    monkeypatch.setenv("RESOLVE_DEMO_MODE", "1")
    staff.reset()
    ratelimit.reset()


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Every test gets its own freshly seeded database, so tests cannot affect each other."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    seed.seed_db()


@pytest.fixture
def sign_in():
    def login(client, name="asha"):
        pin = {"asha": "1111", "ravi": "2222"}[name]
        token = client.post("/api/staff/login", json={"name": name, "pin": pin}).json()["token"]
        client.headers["Authorization"] = f"Bearer {token}"

    return login
