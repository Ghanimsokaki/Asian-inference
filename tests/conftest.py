"""Shared fixtures. Every test runs against a throwaway database."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import core  # noqa: E402
import store  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Point the store at an empty database for each test."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(store, "DB_PATH", db_path)
    store.reset_for_tests(db_path)
    store.ensure_db()
    yield db_path
    store.close_thread_connection()


@pytest.fixture
def user():
    """A registered Starter account."""
    ok, message = core.register("member@example.com", "correct-horse", "Pat Member")
    assert ok, message
    return core.get_user("member@example.com")


@pytest.fixture
def no_hub(monkeypatch):
    """Ensure tests never touch the network for Hugging Face mirroring."""
    monkeypatch.setattr(core, "mirror_to_hub", lambda *_a, **_k: ("local", None, None))
