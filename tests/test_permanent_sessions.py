"""Saved sign-ins remain revocable while browser cookies obey lifetime limits."""
from __future__ import annotations

from datetime import datetime, timezone

import app
import config
import core
import store
import pytest


@pytest.mark.parametrize("permanent,days", [(True, 36500), (False, 180)])
def test_default_session_expiry_respects_mode(monkeypatch, user, permanent, days):
    monkeypatch.setattr(core, "AUTH_SESSION_PERMANENT", permanent)
    monkeypatch.setattr(core, "PERMANENT_SESSION_DAYS", 36500)
    monkeypatch.setattr(core, "AUTH_SESSION_DAYS", 180)
    token = core.create_persistent_session(user["email"])
    row = store.get_auth_session(core._hash_session_token(token))
    remaining = (datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)).days
    assert days - 1 <= remaining <= days
    core.authenticate_persistent_session(token)
    row = store.get_auth_session(core._hash_session_token(token))
    remaining = (datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)).days
    assert days - 1 <= remaining <= days


def test_explicit_short_session_expiry_still_supported(user):
    token = core.create_persistent_session(user["email"], days=2)
    row = store.get_auth_session(core._hash_session_token(token))
    remaining = (datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)).days
    assert 1 <= remaining <= 2


@pytest.mark.parametrize("permanent,session_days,expected", [
    (True, 36500, 400), (False, 900, 400), (False, 7, 7),
])
def test_cookie_max_age_capped(monkeypatch, permanent, session_days, expected):
    captured = []
    monkeypatch.setattr(app, "AUTH_SESSION_PERMANENT", permanent)
    monkeypatch.setattr(app, "AUTH_SESSION_DAYS", session_days)
    monkeypatch.setattr(app.components, "html", lambda text, **_k: captured.append(text))
    monkeypatch.setattr(app.st, "session_state", {app.AUTH_COOKIE_SET_KEY: "random-token"})
    app._render_auth_cookie_updates()
    assert f"Max-Age={expected * 86400}" in captured[0]
    assert "random-token" in captured[0]


def test_cookie_clear_is_immediate(monkeypatch):
    captured = []
    monkeypatch.setattr(app.components, "html", lambda text, **_k: captured.append(text))
    monkeypatch.setattr(app.st, "session_state", {app.AUTH_COOKIE_CLEAR_KEY: True})
    app._render_auth_cookie_updates()
    assert "Max-Age=0" in captured[0]


def test_password_change_revokes_all_tokens(user):
    a = core.create_persistent_session(user["email"])
    b = core.create_persistent_session(user["email"])
    assert core.change_password(user["email"], "correct-horse", "new-good-password")[0]
    assert core.authenticate_persistent_session(a) is None
    assert core.authenticate_persistent_session(b) is None


def test_sign_out_revokes_current_token(monkeypatch, user):
    token = core.create_persistent_session(user["email"])
    monkeypatch.setattr(app, "_auth_cookie", lambda: token)
    monkeypatch.setattr(app.st, "session_state", {app.SESSION_EMAIL: user["email"]})
    app._sign_out()
    assert core.authenticate_persistent_session(token) is None
    assert app.st.session_state[app.AUTH_COOKIE_CLEAR_KEY]


def test_sign_out_everywhere_revokes_all_tokens(user):
    tokens = [core.create_persistent_session(user["email"]) for _ in range(2)]
    assert core.revoke_all_persistent_sessions(user["email"]) == 2
    assert all(core.authenticate_persistent_session(token) is None for token in tokens)


def test_registration_flow_creates_session_without_remember_checkbox():
    source = __import__("inspect").getsource(app.page_auth)
    assert "st.checkbox" not in source
    assert "core.create_persistent_session" in source
    assert "core.get_user(email)" in source
    assert "Sign in using the tab above" not in source


def test_permanent_default_is_on():
    assert config.AUTH_SESSION_PERMANENT is True
    assert config.MAX_COOKIE_DAYS == 400


def test_open_session_rechecks_revoked_token(monkeypatch, user):
    token = core.create_persistent_session(user["email"])
    monkeypatch.setattr(app.st, "session_state", {app.SESSION_EMAIL: user["email"],
                                                 app.AUTH_SESSION_TOKEN_KEY: token})
    core.revoke_persistent_session(token)
    assert app._restore_sign_in() is False
    assert app.SESSION_EMAIL not in app.st.session_state
    assert app.st.session_state[app.AUTH_COOKIE_CLEAR_KEY]
