import pytest

from app import db, llm, seed


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """No test may spend API credits. Tests that need a model install a scripted fake."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("A test tried to call the real LLM")

    monkeypatch.setattr(llm, "chat", refuse)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Every test gets its own freshly seeded database, so tests cannot affect each other."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    seed.seed_db()
