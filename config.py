"""
config.py — single source of truth for secrets, plans and app constants.

Everything that used to be duplicated across ``core.py`` and
``stripe_integration.py`` lives here so a plan change never has to be made
twice.
"""
from __future__ import annotations

import base64
import json
import os
import re
import tomllib
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


def _secrets_parse_error() -> str:
    """Inspect the local file once; Streamlit otherwise hides TOML errors in secret()."""
    path = Path(__file__).resolve().parent / ".streamlit/secrets.toml"
    if not path.exists():
        return ""
    try:
        with path.open("rb") as handle:
            source = handle.read()
        tomllib.loads(source.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        # Do not echo the source line: it may contain a credential.
        line = getattr(exc, "lineno", None)
        if line is None:
            match = re.search(r"at line (\d+)", str(exc))
            line = match.group(1) if match else None
        if line is None and "at end of document" in str(exc):
            line = len(source.splitlines()) or 1
        detail = str(exc).split(" (at ", 1)[0]
        # TOML errors can quote a character from a malformed secret: redact it.
        detail = re.sub(r"(['\"])[^'\"]*\1", "<character>", detail)
        label = f"invalid TOML ({detail})"
        return f"{label} at line {line}" if line else label
    except UnicodeError:
        return "invalid TOML encoding"
    except OSError:
        return ""
    return ""


SECRETS_TOML_ERROR = _secrets_parse_error()


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
ADMIN_EMAIL = secret("ADMIN_EMAIL", "emir.erningpraja").strip().lower()

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


MODEL_PROVIDER_TOKEN = _real_secret("MODEL_PROVIDER_TOKEN") or _real_secret("HF_TOKEN")
#: Backwards-compatible alias for older deployments and tests.
HF_TOKEN = MODEL_PROVIDER_TOKEN
DEFAULT_AGENT_REPO = secret("AGENT_REPO", "Hwiiiiiiii/gemby-agent-3b")

TRAAKTEER_SECRET = _real_secret("TRAAKTEER_SECRET")
STRIPE_SECRET_KEY = _real_secret("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = _real_secret("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = _real_secret("STRIPE_WEBHOOK_SECRET")

PUBLIC_URL = secret("PUBLIC_URL", "https://asian-inference.streamlit.app").rstrip("/")
AUTH_COOKIE_NAME = secret("AUTH_COOKIE_NAME", "asian_inference_session").strip() or "asian_inference_session"
AUTH_SESSION_PERMANENT = secret_bool("AUTH_SESSION_PERMANENT", True)
MAX_COOKIE_DAYS = 400
try:
    PERMANENT_SESSION_DAYS = max(1, int(secret("PERMANENT_SESSION_DAYS", "36500")))
except ValueError:
    PERMANENT_SESSION_DAYS = 36500
try:
    AUTH_SESSION_DAYS = max(1, int(secret("AUTH_SESSION_DAYS", "180")))
except ValueError:
    AUTH_SESSION_DAYS = 180

# ── Optional Supabase chat memory ────────────────────────────────────
#: Placeholder-screened like every other external service, so leaving the
#: README template value in place is reported as "not configured" rather than
#: as an unreachable host.
SUPABASE_URL = _real_secret("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = (
    _real_secret("SUPABASE_SERVICE_ROLE_KEY")
    or _real_secret("SUPABASE_SECRET_KEY")
    or _real_secret("SUPABASE_ANON_KEY")
    or _real_secret("SUPABASE_PUBLISHABLE_KEY")
    or _real_secret("SUPABASE_KEY")
)


def supabase_key_family(key: str | None = None) -> str:
    """Classify a key for diagnostics only; never use this for authorization."""
    value = SUPABASE_KEY if key is None else key
    if value.startswith("sb_secret_"):
        return "service"
    if value.startswith("sb_publishable_"):
        return "anon"
    try:
        payload = value.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        role = claims.get("role")
        if role == "service_role":
            return "service"
        if role in {"anon", "authenticated"}:
            return "anon"
    except (IndexError, ValueError, TypeError, UnicodeError):
        pass
    return "unknown"


def supabase_rls_caveat() -> str:
    if supabase_key_family() == "anon":
        return (" Reads and writes are subject to row-level security (RLS); a 200 [] "
                "response can still mean rows were filtered or a write did not persist.")
    return ""


def supabase_rejection_advice() -> str:
    family = supabase_key_family()
    if family == "anon":
        return " Check the anon/publishable key and RLS policies for reads and writes."
    if family == "service":
        return " Check the secret/service-role key and project URL."
    return " Check the key and project URL; anon/publishable keys also require RLS policies."

SUPABASE_SCHEMA = secret("SUPABASE_SCHEMA", "public")
SUPABASE_CHAT_TABLE = secret("SUPABASE_CHAT_TABLE", "chat_memories")
SUPABASE_APP_PREFIX = secret("SUPABASE_APP_PREFIX", "ai")
SUPABASE_PRIMARY_BACKEND = secret_bool("SUPABASE_PRIMARY_BACKEND", True)


def supabase_missing_settings() -> list[str]:
    """Names of the Supabase settings the optional features still need.

    Both the URL and a key are required; either the service-role or the anon
    key works, which is why the key is reported as a choice.
    """
    missing: list[str] = []
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_SECRET_KEY, SUPABASE_ANON_KEY, SUPABASE_PUBLISHABLE_KEY, SUPABASE_KEY)")
    return missing


def supabase_setup_hint() -> str:
    """What an operator must add, or an empty string when Supabase is set up."""
    missing = supabase_missing_settings()
    problem = (f".streamlit/secrets.toml has {SECRETS_TOML_ERROR}. "
               if SECRETS_TOML_ERROR else "")
    if not missing:
        return problem.strip()
    return problem + (
        "Add " + " and ".join(missing) + " to Streamlit secrets "
        "(.streamlit/secrets.toml) or the environment, then restart the app."
    )


def supabase_not_configured_message(prefix: str) -> str:
    """Banner text for a disabled Supabase feature, naming what is missing."""
    hint = supabase_setup_hint()
    return f"{prefix} {hint}".strip()


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
    if not email:
        return False
    candidate = email.strip().lower()
    target = ADMIN_EMAIL.strip().lower()
    if not target:
        return False
    if candidate == target:
        return True
    if "@" not in target:
        return candidate.split("@", 1)[0] == target
    return False


def display_limit(value: int) -> str:
    """Render a numeric plan limit, collapsing sentinel values to 'Unlimited'."""
    return "Unlimited" if value >= UNLIMITED_THRESHOLD else f"{value:,}"
