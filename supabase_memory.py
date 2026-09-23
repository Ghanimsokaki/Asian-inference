"""Optional Supabase-backed chat memory.

This module is deliberately best-effort: the app should keep working even when
Supabase is missing, misconfigured or temporarily unreachable. In that case the
chat simply falls back to in-memory session history.
"""
from __future__ import annotations

import json
from typing import Any

import requests

import config

TIMEOUT = 20


def _configured_key() -> str:
    return config.SUPABASE_KEY or ""


def is_configured() -> bool:
    return bool(config.SUPABASE_URL and _configured_key())


def _headers(*, write: bool = False) -> dict[str, str]:
    key = _configured_key()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    if config.SUPABASE_SCHEMA and config.SUPABASE_SCHEMA != "public":
        profile = config.SUPABASE_SCHEMA
        headers["Accept-Profile"] = profile
        if write:
            headers["Content-Profile"] = profile
    if write:
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "return=minimal"
    return headers


def _endpoint() -> str:
    return f"{config.SUPABASE_URL}/rest/v1/{config.SUPABASE_CHAT_TABLE}"


def _normalise_offer(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def load_chat_history(email: str, limit: int = 50) -> list[dict]:
    """Return recent messages for `email`, oldest-first."""
    if not is_configured() or not email:
        return []
    try:
        response = requests.get(
            _endpoint(),
            headers=_headers(),
            params={
                "select": "role,content,offer,created_at",
                "user_email": f"eq.{email.strip().lower()}",
                "order": "created_at.asc,id.asc",
                "limit": str(max(1, min(int(limit), 200))),
            },
            timeout=TIMEOUT,
        )
        if not response.ok:
            return []
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError):
        return []

    messages: list[dict] = []
    for row in payload if isinstance(payload, list) else []:
        role = str(row.get("role") or "").strip().lower()
        content = str(row.get("content") or "").strip()
        if role not in {"user", "bot"} or not content:
            continue
        entry = {"role": role, "content": content}
        offer = _normalise_offer(row.get("offer"))
        if offer:
            entry["offer"] = offer
        messages.append(entry)
    return messages


def append_message(email: str, role: str, content: str, offer: dict | None = None) -> bool:
    """Persist one chat turn.

    Returns True when the write succeeded. Failures are swallowed by callers so
    the user never loses the live conversation because memory is down.
    """
    if not is_configured() or not email:
        return False
    role = (role or "").strip().lower()
    content = (content or "").strip()
    if role not in {"user", "bot"} or not content:
        return False

    payload = {
        "user_email": email.strip().lower(),
        "role": role,
        "content": content[:8000],
        "offer": offer or None,
    }
    try:
        response = requests.post(
            _endpoint(), headers=_headers(write=True), json=payload, timeout=TIMEOUT
        )
        return response.ok
    except requests.RequestException:
        return False


def clear_chat_history(email: str) -> bool:
    if not is_configured() or not email:
        return False
    try:
        response = requests.delete(
            _endpoint(),
            headers=_headers(write=True),
            params={"user_email": f"eq.{email.strip().lower()}"},
            timeout=TIMEOUT,
        )
        return response.ok
    except requests.RequestException:
        return False


def memory_diagnostic() -> tuple[bool, str]:
    if not is_configured():
        return False, config.supabase_not_configured_message(
            "Persistent chat memory is not configured."
        )
    try:
        response = requests.get(
            _endpoint(),
            headers=_headers(),
            params={"select": "id", "limit": "1"},
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return False, "Persistent chat memory could not reach Supabase."
    if response.ok:
        return True, "Persistent chat memory is connected."
    return False, "Persistent chat memory rejected the configured Supabase credentials."
