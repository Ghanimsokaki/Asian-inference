"""Configuration, RLS and safe diagnostics regression tests."""
from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
import re

import pytest

import config
import supabase_backend
import supabase_memory
from scripts import check_supabase as diagnostic


@pytest.mark.parametrize("name", [
    "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY", "SUPABASE_ANON_KEY",
    "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_KEY",
])
def test_each_key_name_is_resolved(monkeypatch, name):
    for key in diagnostic.KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(name, "sb_secret_actualvalue")
    spec = importlib.util.spec_from_file_location("config_probe", config.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SUPABASE_KEY == "sb_secret_actualvalue"


@pytest.mark.parametrize("name,expected", [
    ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY"),
    ("SUPABASE_SECRET_KEY", "SUPABASE_ANON_KEY"),
    ("SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY"),
    ("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_KEY"),
])
def test_key_fallback_priority(monkeypatch, name, expected):
    for key in diagnostic.KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(name, "higher")
    monkeypatch.setenv(expected, "lower")
    spec = importlib.util.spec_from_file_location("config_probe", config.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SUPABASE_KEY == "higher"


@pytest.mark.parametrize("prefix,family", [
    ("sb_secret_abc", "service"), ("sb_publishable_abc", "anon"),
    ("unknown", "unknown"),
])
def test_key_prefix_family(prefix, family):
    assert config.supabase_key_family(prefix) == family


@pytest.mark.parametrize("role,family", [
    ("service_role", "service"), ("anon", "anon"), ("authenticated", "anon"),
    ("other", "unknown"),
])
def test_jwt_role_family(role, family):
    payload = base64.urlsafe_b64encode(json.dumps({"role": role}).encode()).decode().rstrip("=")
    assert config.supabase_key_family(f"head.{payload}.sig") == family


def test_opaque_publishable_key_uses_apikey_only(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_KEY", "sb_publishable_example")
    assert supabase_memory._headers()["apikey"] == "sb_publishable_example"
    assert "Authorization" not in supabase_backend._headers()
    assert "Authorization" not in supabase_memory._headers()


@pytest.mark.parametrize("family,fragment", [
    ("sb_publishable_abc", "row-level security"),
    ("sb_secret_abc", "connected."),
])
def test_rls_connected_caveat(monkeypatch, family, fragment):
    monkeypatch.setattr(config, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_KEY", family)
    class Response:
        ok = True
    monkeypatch.setattr(supabase_memory.requests, "get", lambda *_a, **_kw: Response())
    monkeypatch.setattr(supabase_backend, "_request", lambda *_a, **_kw: Response())
    assert fragment in supabase_memory.memory_diagnostic()[1]
    assert fragment in supabase_backend.health_diagnostic()[1]
    if family.startswith("sb_secret"):
        assert "RLS" not in supabase_memory.memory_diagnostic()[1]


@pytest.mark.parametrize("key,advice", [
    ("sb_publishable_abc", "anon/publishable"),
    ("sb_secret_abc", "secret/service-role"),
    ("not-a-jwt", "Check the key"),
])
def test_rejection_advice(monkeypatch, key, advice):
    monkeypatch.setattr(config, "SUPABASE_KEY", key)
    assert advice in config.supabase_rejection_advice()


def test_malformed_local_toml_is_named_with_line_without_value(monkeypatch, tmp_path):
    path = tmp_path / ".streamlit" / "secrets.toml"
    path.parent.mkdir()
    path.write_text('SUPABASE_KEY = "do-not-print"\nBAD = [\n')
    monkeypatch.setattr(config, "__file__", str(tmp_path / "config.py"))
    error = config._secrets_parse_error()
    assert "invalid TOML" in error and "line 2" in error
    assert "do-not-print" not in error
    monkeypatch.setattr(config, "SECRETS_TOML_ERROR", error)
    assert "line 2" in config.supabase_setup_hint()


def test_secret_still_swallows_streamlit_exceptions(monkeypatch):
    import streamlit as st
    monkeypatch.setattr(st, "secrets", object())
    monkeypatch.setenv("CONFIG_FALLBACK_PROBE", "works")
    assert config.secret("CONFIG_FALLBACK_PROBE") == "works"


def test_setting_sources_nested_and_typo(monkeypatch, tmp_path, capsys):
    path = tmp_path / "secrets.toml"
    path.write_text('SUPABASE_URL = "https://do-not-print"\n[other]\nSUPABASE_KEY = "do-not-print"\nSUPABASE_URl = "typo"\n')
    monkeypatch.setenv("SUPABASE_KEY", "secret-do-not-print")
    diagnostic.inspect_settings(path)
    text = capsys.readouterr().out
    assert f"SUPABASE_URL: {path}" in text
    assert "SUPABASE_KEY: environment" in text
    assert "nested under [other]" in text
    assert "did you mean SUPABASE_URL" in text
    assert "do-not-print" not in text


def test_write_probe_passes_when_rows_roundtrip(monkeypatch):
    rows = {}
    calls = []
    def fake(method, table, *, params=None, row=None):
        calls.append((method, table))
        ident = tuple(sorted((k, v[3:]) for k, v in (params or {}).items() if k != "select"))
        if method == "POST":
            rows[table] = row
            return [row]
        if method == "DELETE":
            found = rows.pop(table, None)
            return [found] if found else []
        found = rows.get(table)
        return [found] if found and all(found.get(k) == v for k, v in ident) else []
    monkeypatch.setattr(diagnostic, "_probe_request", fake)
    monkeypatch.setattr(config, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_KEY", "sb_secret_example")
    assert diagnostic.write_test()
    assert not rows
    assert ("POST", config.SUPABASE_CHAT_TABLE) in calls
    assert ("POST", supabase_backend._table("auth_sessions")) in calls


def test_write_probe_rejects_200_empty_and_does_not_claim_success(monkeypatch):
    monkeypatch.setattr(diagnostic, "_probe_request", lambda method, *_a, **_k: [] )
    assert not diagnostic._roundtrip("chat_memories", {"content": "random"}, {"content": "random"})


def test_write_probe_does_not_overwrite_reserved_user(monkeypatch):
    calls = []
    def fake(method, table, *, params=None, row=None):
        calls.append(method)
        return [{"email": diagnostic.ADDRESS}]
    monkeypatch.setattr(diagnostic, "_probe_request", fake)
    monkeypatch.setattr(config, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_KEY", "sb_secret_example")
    assert not diagnostic.write_test()
    assert "POST" not in calls


def test_schema_has_no_active_rls_statements():
    sql = (Path(__file__).resolve().parents[1] / "supabase_schema.sql").read_text()
    assert "Case 1" in sql and "Case 2" in sql
    active = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert not re.search(r"\b(?:enable\s+row\s+level\s+security|create\s+policy|alter\s+policy|drop\s+policy)\b", active, re.I)


def test_parse_error_is_reported_even_when_environment_supplies_settings(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_KEY", "sb_secret_example")
    monkeypatch.setattr(config, "SECRETS_TOML_ERROR", "invalid TOML at line 5")
    assert "line 5" in config.supabase_setup_hint()


def test_probe_fails_when_delete_returns_200_empty(monkeypatch):
    def fake(method, _table, *, params=None, row=None):
        if method == "GET" and params.get("select") != "*":
            return []
        if method == "DELETE":
            return []  # PostgREST filtered the row rather than deleting it.
        return [{"content": "unique"}]
    monkeypatch.setattr(diagnostic, "_probe_request", fake)
    assert not diagnostic._roundtrip("chat_memories", {"content": "unique"},
                                     {"content": "unique"})


@pytest.mark.parametrize("key,expects_bearer", [
    ("sb_secret_opaque", False), ("sb_publishable_opaque", False),
    ("eyJ.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.sig", True),
    ("eyJ.eyJyb2xlIjoiYW5vbiJ9.sig", True),
])
def test_supabase_auth_header_depends_on_format_not_name(monkeypatch, key, expects_bearer):
    monkeypatch.setattr(config, "SUPABASE_KEY", key)
    for headers in (supabase_memory._headers(), supabase_backend._headers()):
        assert headers["apikey"] == key
        assert (headers.get("Authorization") == f"Bearer {key}") is expects_bearer


@pytest.mark.parametrize("status,fragment", [
    (401, "rejected"), (403, "rejected"), (404, "table is missing"),
    (400, "HTTP 400"), (500, "HTTP 500"),
])
def test_memory_diagnostic_distinguishes_http_failures(monkeypatch, status, fragment):
    monkeypatch.setattr(config, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_KEY", "sb_secret_test")
    class Response:
        ok = False
        status_code = status
    monkeypatch.setattr(supabase_memory.requests, "get", lambda *_a, **_kw: Response())
    assert fragment in supabase_memory.memory_diagnostic()[1]


@pytest.mark.parametrize("status,fragment", [
    (401, "rejected"), (403, "rejected"), (404, "tables are missing"),
    (400, "HTTP 400"), (500, "HTTP 500"),
])
def test_backend_diagnostic_distinguishes_http_failures(monkeypatch, status, fragment):
    monkeypatch.setattr(config, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_KEY", "sb_secret_test")
    class Response:
        ok = False
        status_code = status
    monkeypatch.setattr(supabase_backend, "_request", lambda *_a, **_kw: Response())
    assert fragment in supabase_backend.health_diagnostic()[1]
