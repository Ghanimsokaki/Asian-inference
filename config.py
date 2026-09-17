"""
config.py — single source of truth for secrets, plans and app constants.

Everything that used to be duplicated across ``core.py`` and
``stripe_integration.py`` lives here so a plan change never has to be made
twice.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

APP_NAME = "Asian Inference"
APP_ICON = "⚡"
APP_TAGLINE = "Build AI datasets · Fine-tune models · Share with the community"

# ── Secrets ──────────────────────────────────────────────────────────
# Resolution order: Streamlit secrets → environment → fallback.
# Reading ``st.secrets`` raises when no secrets file exists, so every access is
# guarded; this module must stay importable outside a Streamlit runtime (tests,
# scripts, webhook workers).


def secret(key: str, fallback: str = "") -> str:
    """Return a secret from Streamlit secrets, the environment, or `fallback`."""
    try:
        import streamlit as st

        value = st.secrets[key]
        if value is not None:
            return str(value)
    except Exception:
        pass
    return os.getenv(key, fallback)


def secret_bool(key: str, fallback: bool = False) -> bool:
    raw = secret(key, "").strip().lower()
    if not raw:
        return fallback
    return raw in {"1", "true", "yes", "on"}


# ── Identity & crypto ────────────────────────────────────────────────
ADMIN_EMAIL = secret("ADMIN_EMAIL", "emir.erningpraja@gmail.com").strip().lower()

DEFAULT_SECRET_KEY = "asian-inference-insecure-development-key"
SECRET_KEY = secret("SECRET_KEY", DEFAULT_SECRET_KEY)

#: True when the deployment is still running on the shipped placeholder key.
#: Password hashes are salted per user, so this only weakens legacy hashes, but
#: the UI surfaces it to the admin as a configuration warning.
USING_DEFAULT_SECRET = SECRET_KEY == DEFAULT_SECRET_KEY

# ── External services ────────────────────────────────────────────────
#: Template markers from the shipped secrets example. A token still carrying
#: one of these is unfilled, and treating it as real means every call spends a
#: round-trip earning a 401 before falling back.
_PLACEHOLDER_MARKERS = ("paste", "_here", "xxxx", "your_token", "changeme")


def _is_placeholder(value: str) -> bool:
    lowered = (value or "").lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def _real_secret(key: str, fallback: str = "") -> str:
    """Read a secret, treating an unedited placeholder as absent."""
    value = secret(key, fallback)
    return "" if _is_placeholder(value) else value


HF_TOKEN = _real_secret("HF_TOKEN")
DEFAULT_AGENT_REPO = secret("AGENT_REPO", "Hwiiiiiiii/gemby-agent-3b")

TRAAKTEER_SECRET = _real_secret("TRAAKTEER_SECRET")
STRIPE_SECRET_KEY = _real_secret("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = _real_secret("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = _real_secret("STRIPE_WEBHOOK_SECRET")

PUBLIC_URL = secret("PUBLIC_URL", "https://asian-inference.streamlit.app").rstrip("/")

# ── Storage ──────────────────────────────────────────────────────────
DATA_DIR = Path(secret("DATA_DIR", ".")).expanduser()
DB_PATH = DATA_DIR / "asian_inference.db"
LEGACY_DB_JSON = DATA_DIR / "db.json"

# ── Economics ────────────────────────────────────────────────────────
TOKENS_PER_ROW = 10
MAX_MANUAL_GRANT = 100_000
MANUAL_GRANTS_PER_HOUR_BEFORE_FLAG = 5

RATE_LIMITS = {
    "login": 10,
    "register": 5,
    "generate": 3,
    "inference": 5,
    "ticket": 3,
    "api_key": 10,
}

# ── Plans ────────────────────────────────────────────────────────────
PLANS: dict[str, dict[str, Any]] = {
    "starter": {
        "id": "starter",
        "name": "Starter",
        "badge": "🆓",
        "price": 0.0,
        "monthly_tokens": 500,
        "max_rows": 50,
        "max_models": 2,
        "max_datasets": 2,
        "share": False,
        "api_keys": 1,
        "priority_queue": False,
        "traakteer_id": "",
        "stripe_price_id": secret("STRIPE_PRICE_STARTER", ""),
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "badge": "⚡",
        "price": 9.99,
        "monthly_tokens": 15_000,
        "max_rows": 2_000,
        "max_models": 6,
        "max_datasets": 6,
        "share": True,
        "api_keys": 5,
        "priority_queue": False,
        "traakteer_id": "plan_pro_monthly",
        "stripe_price_id": secret("STRIPE_PRICE_PRO", ""),
    },
    "elite": {
        "id": "elite",
        "name": "Elite",
        "badge": "👑",
        "price": 29.99,
        "monthly_tokens": 999_999,
        "max_rows": 50_000,
        "max_models": 999,
        "max_datasets": 999,
        "share": True,
        "api_keys": 999,
        "priority_queue": True,
        "traakteer_id": "plan_elite_monthly",
        "stripe_price_id": secret("STRIPE_PRICE_ELITE", ""),
    },
}

DEFAULT_PLAN = "starter"
ADMIN_PLAN = "elite"

#: Plans whose limits are displayed as "Unlimited" rather than a raw number.
UNLIMITED_THRESHOLD = 999


def plan_for(plan_id: str | None) -> dict[str, Any]:
    """Return a plan definition, falling back to Starter for unknown ids."""
    return PLANS.get((plan_id or "").lower(), PLANS[DEFAULT_PLAN])


def is_admin(email: str | None) -> bool:
    return bool(email) and email.strip().lower() == ADMIN_EMAIL


def display_limit(value: int) -> str:
    """Render a numeric plan limit, collapsing sentinel values to 'Unlimited'."""
    return "Unlimited" if value >= UNLIMITED_THRESHOLD else f"{value:,}"
