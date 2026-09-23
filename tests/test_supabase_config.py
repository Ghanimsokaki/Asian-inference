"""The Supabase banners must name exactly which setting is missing.

Both optional Supabase features are health-checked on the admin panel, and the
dashboard pills read the same state. A bare "not configured" was unactionable,
so each message now names the settings an operator has to add.
"""
from __future__ import annotations

import config
import supabase_backend
import supabase_memory


def _unset(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", "")
    monkeypatch.setattr(config, "SUPABASE_KEY", "")


def _set(monkeypatch, *, url="https://project.supabase.co", key="service-role"):
    monkeypatch.setattr(config, "SUPABASE_URL", url)
    monkeypatch.setattr(config, "SUPABASE_KEY", key)


class _Response:
    def __init__(self, ok: bool = True, status_code: int = 200):
        self.ok = ok
        self.status_code = status_code


def test_memory_banner_names_both_missing_settings(monkeypatch):
    _unset(monkeypatch)

    ok, message = supabase_memory.memory_diagnostic()

    assert ok is False
    assert "Persistent chat memory is not configured." in message
    assert "SUPABASE_URL" in message
    assert "SUPABASE_SERVICE_ROLE_KEY" in message
    assert ".streamlit/secrets.toml" in message


def test_backend_banner_names_both_missing_settings(monkeypatch):
    _unset(monkeypatch)

    ok, message = supabase_backend.health_diagnostic()

    assert ok is False
    assert "Supabase app backend is not configured." in message
    assert "SUPABASE_URL" in message
    assert "SUPABASE_SERVICE_ROLE_KEY" in message


def test_only_the_missing_setting_is_named(monkeypatch):
    _set(monkeypatch, key="")

    _, message = supabase_backend.health_diagnostic()

    assert "SUPABASE_SERVICE_ROLE_KEY" in message
    assert "SUPABASE_URL" not in message


def test_hint_disappears_once_both_settings_exist(monkeypatch):
    _set(monkeypatch)

    assert config.supabase_missing_settings() == []
    assert config.supabase_setup_hint() == ""


def test_template_placeholders_are_not_treated_as_secrets():
    assert config._is_placeholder("paste_your_service_role_key_here")
    assert config._is_placeholder("https://xxxx.supabase.co")
    assert config._is_placeholder("changeme")
    assert not config._is_placeholder("https://projectabc.supabase.co")
    assert not config._is_placeholder("sb_secret_realkey")


def test_backend_reports_connected_once_configured(monkeypatch):
    _set(monkeypatch)
    monkeypatch.setattr(config, "SUPABASE_PRIMARY_BACKEND", True)
    monkeypatch.setattr(supabase_backend, "_request", lambda *_a, **_k: _Response())

    ok, message = supabase_backend.health_diagnostic()

    assert ok is True
    assert "connected" in message
    assert "secrets" not in message  # the setup hint is gone once configured


def test_backend_points_at_the_schema_when_tables_are_missing(monkeypatch):
    _set(monkeypatch)
    monkeypatch.setattr(
        supabase_backend, "_request", lambda *_a, **_k: _Response(ok=False, status_code=404)
    )

    ok, message = supabase_backend.health_diagnostic()

    assert ok is False
    assert "supabase_schema.sql" in message


def test_memory_reports_connected_once_configured(monkeypatch):
    _set(monkeypatch)
    monkeypatch.setattr(supabase_memory.requests, "get", lambda *_a, **_k: _Response())

    ok, message = supabase_memory.memory_diagnostic()

    assert ok is True
    assert message == "Persistent chat memory is connected."


def test_memory_survives_an_unreachable_supabase(monkeypatch):
    _set(monkeypatch)

    def boom(*_a, **_k):
        raise supabase_memory.requests.RequestException("no route to host")

    monkeypatch.setattr(supabase_memory.requests, "get", boom)

    ok, message = supabase_memory.memory_diagnostic()

    assert ok is False
    assert "could not reach" in message
