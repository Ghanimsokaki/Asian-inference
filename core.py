"""
core.py — domain logic: accounts, plans, tokens, quotas and API keys.

This module owns the *rules*. Persistence lives in :mod:`store`, configuration
in :mod:`config`. Nothing here imports Streamlit, so the whole domain layer is
testable without a browser.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

import store
from config import (
    ADMIN_EMAIL, ADMIN_PLAN, DEFAULT_PLAN, MANUAL_GRANTS_PER_HOUR_BEFORE_FLAG,
    MAX_MANUAL_GRANT, PLANS, RATE_LIMITS, SECRET_KEY, TOKENS_PER_ROW,
    is_admin, plan_for,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256  # bound the work PBKDF2 will do on attacker input
MAX_NAME_LENGTH = 80
PBKDF2_ITERATIONS = 240_000


# ─────────────────────────────────────────────────────────────────────
# ERRORS
# ─────────────────────────────────────────────────────────────────────
class PlanLimitError(RuntimeError):
    """The account has reached a slot, row or key limit for its plan."""


class StorageUnavailableError(RuntimeError):
    """Platform-managed Hugging Face storage could not be reached."""


class AuthError(RuntimeError):
    """Registration or sign-in was refused."""


# ─────────────────────────────────────────────────────────────────────
# PASSWORDS
# ─────────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 and a fresh per-user salt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _legacy_hash(password: str) -> str:
    """The original unsalted scheme, kept only to verify pre-existing accounts."""
    return hashlib.sha256((SECRET_KEY + password).encode()).hexdigest()


def verify_password(password: str, stored: str) -> tuple[bool, bool]:
    """Check a password against a stored hash.

    Returns ``(is_valid, needs_rehash)``. ``needs_rehash`` is True for accounts
    still on the legacy unsalted SHA-256 scheme, so callers can transparently
    upgrade them on next successful sign-in.
    """
    if not stored:
        return False, False
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt_hex, digest_hex = stored.split("$", 3)
            expected = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
            )
        except (ValueError, TypeError):
            return False, False
        return hmac.compare_digest(expected.hex(), digest_hex), False
    # Legacy: sha256(SECRET_KEY + password)
    return hmac.compare_digest(_legacy_hash(password), stored), True


# ─────────────────────────────────────────────────────────────────────
# RATE LIMITING
# ─────────────────────────────────────────────────────────────────────
def rate_limit(subject: str, action: str, max_per_min: int | None = None) -> bool:
    """Return False when `subject` has exceeded `action`'s per-minute budget."""
    limit = max_per_min if max_per_min is not None else RATE_LIMITS.get(action, 5)
    return store.rate_limit_hit((subject or "anonymous").strip().lower(), action, limit)


# ─────────────────────────────────────────────────────────────────────
# ACCOUNTS
# ─────────────────────────────────────────────────────────────────────
def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_registration(email: str, password: str, name: str) -> str | None:
    """Return an error message, or None when the input is acceptable."""
    if not EMAIL_RE.match(email):
        return "Enter a valid email address."
    if len(email) > 254:
        return "That email address is too long."
    if not name.strip():
        return "Please enter your name."
    if len(name) > MAX_NAME_LENGTH:
        return f"Name must be {MAX_NAME_LENGTH} characters or fewer."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return "Password is too long."
    return None


def register(email: str, password: str, name: str) -> tuple[bool, str]:
    """Create an account. Returns ``(ok, message)``."""
    email = normalise_email(email)
    name = (name or "").strip()

    problem = validate_registration(email, password, name)
    if problem:
        return False, problem
    if not rate_limit(email, "register"):
        return False, "Too many sign-up attempts. Please wait a minute."

    plan = ADMIN_PLAN if is_admin(email) else DEFAULT_PLAN
    tokens = plan_for(plan)["monthly_tokens"]

    if not store.create_user(email, name, hash_password(password), plan, tokens):
        return False, "That email is already registered."
    return True, "Account created."


def login(email: str, password: str) -> tuple[bool, str, dict | None]:
    """Authenticate. Returns ``(ok, message, user)``."""
    email = normalise_email(email)
    if not email or not password:
        return False, "Enter your email and password.", None
    if not rate_limit(email, "login"):
        return False, "Too many attempts. Please wait a minute.", None

    user = store.get_user(email)
    if user is None:
        # Spend comparable time on unknown accounts so timing does not reveal
        # which emails are registered.
        hash_password(password)
        return False, "Wrong email or password.", None

    valid, needs_rehash = verify_password(password, user["pw_hash"])
    if not valid:
        return False, "Wrong email or password.", None
    if user["flagged"] and not is_admin(email):
        return False, "Account suspended. Contact support.", None

    if needs_rehash:
        store.update_user(email, pw_hash=hash_password(password))
        user = store.get_user(email)

    return True, "Signed in.", user


def change_password(email: str, current: str, new: str) -> tuple[bool, str]:
    user = store.get_user(normalise_email(email))
    if user is None:
        return False, "Account not found."
    valid, _ = verify_password(current, user["pw_hash"])
    if not valid:
        return False, "Current password is incorrect."
    if len(new) < MIN_PASSWORD_LENGTH:
        return False, f"New password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(new) > MAX_PASSWORD_LENGTH:
        return False, "New password is too long."
    store.update_user(user["email"], pw_hash=hash_password(new))
    return True, "Password updated."


def get_user(email: str) -> dict | None:
    return store.get_user(normalise_email(email))


# ─────────────────────────────────────────────────────────────────────
# USAGE SNAPSHOT
# ─────────────────────────────────────────────────────────────────────
def usage(user: dict) -> dict[str, Any]:
    """Current counts and limits for a user, read straight from the database."""
    email = user["email"]
    plan = plan_for(user["plan"])
    unlimited = is_admin(email)
    return {
        "plan": plan,
        "unlimited": unlimited,
        "datasets": store.count_user_datasets(email),
        "models": store.count_user_models(email),
        "api_keys": store.count_user_api_keys(email),
        "tokens": user.get("tokens", 0),
        "max_datasets": plan["max_datasets"],
        "max_models": plan["max_models"],
        "max_api_keys": plan["api_keys"],
        "max_tokens": plan["monthly_tokens"],
    }


def at_limit(user: dict, kind: str) -> bool:
    """True when the user cannot create another `kind` ('datasets' | 'models')."""
    if is_admin(user["email"]):
        return False
    counts = {"datasets": store.count_user_datasets, "models": store.count_user_models}
    if kind not in counts:
        raise ValueError(f"Unknown quota kind: {kind}")
    return counts[kind](user["email"]) >= plan_for(user["plan"])[f"max_{kind}"]


# ─────────────────────────────────────────────────────────────────────
# TOKENS
# ─────────────────────────────────────────────────────────────────────
def row_cost(num_rows: int) -> int:
    return max(0, int(num_rows)) * TOKENS_PER_ROW


def spend_tokens(email: str, amount: int, reason: str = "usage") -> tuple[bool, int]:
    """Atomically debit tokens. Returns ``(ok, new_balance)``."""
    return store.spend_tokens(normalise_email(email), int(amount), reason)


def refund_tokens(email: str, amount: int, reason: str = "refund") -> int:
    return store.add_tokens(normalise_email(email), max(0, int(amount)), reason)


def grant_tokens(email: str, amount: int, reason: str) -> tuple[int, bool]:
    """Admin token grant. Returns ``(new_balance, account_was_flagged)``.

    Grants are clamped and audited; more than
    ``MANUAL_GRANTS_PER_HOUR_BEFORE_FLAG`` manual grants within an hour flags
    the account for review.
    """
    email = normalise_email(email)
    amount = max(0, min(int(amount), MAX_MANUAL_GRANT))
    balance = store.add_tokens(email, amount, f"manual:{reason}"[:200])

    one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    recent = store.count_recent_grants(email, one_hour_ago, "manual")
    flagged = recent > MANUAL_GRANTS_PER_HOUR_BEFORE_FLAG
    if flagged:
        store.update_user(email, flagged=True, flag_reason="Suspicious token activity")
    return balance, flagged


def reset_monthly_tokens(email: str | None = None) -> int:
    """Top every account (or one account) back up to its plan allowance."""
    users = [store.get_user(email)] if email else store.list_users()
    count = 0
    for user in users:
        if not user:
            continue
        allowance = plan_for(user["plan"])["monthly_tokens"]
        store.set_tokens(user["email"], allowance, f"monthly_reset:{user['plan']}")
        count += 1
    return count


def set_plan(email: str, plan_id: str, *, grant_tokens_now: bool = True) -> bool:
    """Move an account to another plan, optionally topping up its allowance."""
    plan_id = (plan_id or "").lower()
    if plan_id not in PLANS:
        raise ValueError(f"Unknown plan: {plan_id}")
    email = normalise_email(email)
    if not store.update_user(email, plan=plan_id):
        return False
    if grant_tokens_now:
        store.set_tokens(email, plan_for(plan_id)["monthly_tokens"], f"plan_change:{plan_id}")
    return True


# ─────────────────────────────────────────────────────────────────────
# PLATFORM API KEY (authenticates as the account)
# ─────────────────────────────────────────────────────────────────────
def new_platform_key() -> str:
    return "asi-" + secrets.token_hex(24)


def rotate_platform_key(email: str) -> str:
    key = new_platform_key()
    store.update_user(normalise_email(email), platform_api_key=key)
    return key


def user_for_platform_key(key: str) -> dict | None:
    """Resolve an ``asi-`` key to its owner, or None."""
    key = (key or "").strip()
    if not key.startswith("asi-"):
        return None
    user = store.find_user_by_platform_key(key)
    if user and user["flagged"]:
        return None
    return user


def mask_key(key: str) -> str:
    """Render a credential for display without revealing it."""
    if not key:
        return ""
    if len(key) <= 12:
        return key[:2] + "•" * 8
    return f"{key[:8]}{'•' * 8}{key[-4:]}"


# ─────────────────────────────────────────────────────────────────────
# THIRD-PARTY API KEYS
# ─────────────────────────────────────────────────────────────────────
def add_api_key(user: dict, label: str, value: str) -> tuple[bool, str]:
    label = (label or "").strip()[:60]
    value = (value or "").strip()
    if not label:
        return False, "Label required."
    if not value:
        return False, "Key value required."
    limit = plan_for(user["plan"])["api_keys"]
    if not is_admin(user["email"]) and store.count_user_api_keys(user["email"]) >= limit:
        return False, f"Your {plan_for(user['plan'])['name']} plan allows {limit} stored key(s)."
    if not store.insert_api_key(user["email"], label, value):
        return False, "You already have a key with that label."
    return True, "Key saved."


def remove_api_key(user: dict, label: str) -> bool:
    return store.delete_api_key(user["email"], label)


# ─────────────────────────────────────────────────────────────────────
# DATASETS
# ─────────────────────────────────────────────────────────────────────
def create_dataset(
    owner: str, name: str, description: str, rows: Sequence[dict],
    public: bool, tags: Sequence[str],
) -> str:
    """Persist a dataset after enforcing plan limits.

    The database is the source of truth. When a Hugging Face token is
    configured the rows are also mirrored to the platform's private Hub repo;
    if that mirror is unavailable the dataset still saves, recorded as
    ``local``. Raises :class:`PlanLimitError` when a plan limit is reached.
    """
    owner = normalise_email(owner)
    user = store.get_user(owner)
    if user is None:
        raise ValueError("Owner account not found.")

    plan = plan_for(user["plan"])
    privileged = is_admin(owner)
    if not privileged and store.count_user_datasets(owner) >= plan["max_datasets"]:
        raise PlanLimitError(
            f"Your {plan['name']} plan allows {plan['max_datasets']} datasets. "
            "Delete one or upgrade to create more."
        )
    if not privileged and len(rows) > plan["max_rows"]:
        raise PlanLimitError(
            f"Your {plan['name']} plan allows {plan['max_rows']:,} rows per dataset."
        )
    if not rows:
        raise ValueError("A dataset needs at least one row.")
    if public and not plan["share"]:
        public = False

    name = (name or "Untitled dataset").strip()[:120]
    description = (description or "").strip()[:1000]
    tags = [t.strip()[:30] for t in tags if t.strip()][:10]

    dataset_id = uuid.uuid4().hex[:10]
    backend, repo, path = mirror_to_hub(dataset_id, rows)
    store.insert_dataset(dataset_id, owner, name, description, rows, public, tags,
                         backend, repo, path)
    return dataset_id


def mirror_to_hub(dataset_id: str, rows: Sequence[dict]) -> tuple[str, str | None, str | None]:
    """Best-effort offsite copy of a dataset to the platform's private Hub repo.

    The database is the source of truth, so a missing or failing Hub connection
    never blocks a save — the dataset is simply recorded as ``local``. Returns
    ``(backend, repo, path)``.
    """
    try:
        import hf_storage

        repo = hf_storage.storage_repo()
        if not repo:
            return "local", None, None
        path = hf_storage.storage_path(dataset_id)
        if hf_storage.put_json(repo, path, list(rows)):
            return "huggingface", repo, path
        return "local", None, None
    except Exception:
        # Network, import or API problems must not cost the user their dataset.
        return "local", None, None


def storage_status() -> tuple[bool, str]:
    """``(connected, message)`` describing the offsite storage mirror."""
    try:
        import hf_storage

        return hf_storage.is_configured(), hf_storage.storage_diagnostic()
    except Exception:
        return False, "Offsite storage could not be checked."


def delete_dataset(dataset_id: str, requester: str) -> tuple[bool, str]:
    """Delete a dataset if `requester` owns it (or is the admin)."""
    dataset = store.get_dataset(dataset_id, with_rows=False)
    if dataset is None:
        return False, "Dataset not found."
    if dataset["owner"] != normalise_email(requester) and not is_admin(requester):
        return False, "You do not have permission to delete that dataset."

    store.delete_dataset(dataset_id)
    if dataset.get("storage_backend") == "huggingface" and dataset.get("storage_path"):
        try:
            import hf_storage

            hf_storage.delete_file(dataset["storage_repo"], dataset["storage_path"])
        except Exception:
            # The row is already gone; an orphaned remote blob is not worth
            # failing the user's delete over.
            pass
    return True, "Dataset deleted."


def set_dataset_visibility(dataset_id: str, requester: str, public: bool) -> tuple[bool, str]:
    dataset = store.get_dataset(dataset_id, with_rows=False)
    if dataset is None:
        return False, "Dataset not found."
    requester = normalise_email(requester)
    if dataset["owner"] != requester and not is_admin(requester):
        return False, "You do not have permission to change that dataset."
    owner = store.get_user(dataset["owner"])
    if public and owner and not plan_for(owner["plan"])["share"] and not is_admin(requester):
        return False, "Public sharing is available on Pro and Elite."
    store.set_dataset_public(dataset_id, public)
    return True, "Visibility updated."


# ─────────────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────────────
def create_model(
    owner: str, name: str, description: str, base_model: str,
    hf_repo: str, public: bool, tags: Sequence[str],
) -> str:
    owner = normalise_email(owner)
    user = store.get_user(owner)
    if user is None:
        raise ValueError("Owner account not found.")

    plan = plan_for(user["plan"])
    if not is_admin(owner) and store.count_user_models(owner) >= plan["max_models"]:
        raise PlanLimitError(
            f"Your {plan['name']} plan allows {plan['max_models']} models. "
            "Delete one or upgrade to create more."
        )
    if not (name or "").strip():
        raise ValueError("Model name is required.")
    if not (base_model or "").strip():
        raise ValueError("Base model is required.")
    if public and not plan["share"]:
        public = False

    model_id = uuid.uuid4().hex[:10]
    store.insert_model(
        model_id, owner, name.strip()[:120], (description or "").strip()[:1000],
        base_model.strip(), (hf_repo or "").strip(), public,
        [t.strip()[:30] for t in tags if t.strip()][:10],
    )
    return model_id


def delete_model(model_id: str, requester: str) -> tuple[bool, str]:
    model = store.get_model(model_id)
    if model is None:
        return False, "Model not found."
    if model["owner"] != normalise_email(requester) and not is_admin(requester):
        return False, "You do not have permission to delete that model."
    store.delete_model(model_id)
    return True, "Model deleted."


def set_model_visibility(model_id: str, requester: str, public: bool) -> tuple[bool, str]:
    model = store.get_model(model_id)
    if model is None:
        return False, "Model not found."
    requester = normalise_email(requester)
    if model["owner"] != requester and not is_admin(requester):
        return False, "You do not have permission to change that model."
    owner = store.get_user(model["owner"])
    if public and owner and not plan_for(owner["plan"])["share"] and not is_admin(requester):
        return False, "Public sharing is available on Pro and Elite."
    store.set_model_public(model_id, public)
    return True, "Visibility updated."


# ─────────────────────────────────────────────────────────────────────
# SUPPORT
# ─────────────────────────────────────────────────────────────────────
def submit_ticket(user: dict, subject: str, message: str) -> tuple[bool, str]:
    message = (message or "").strip()
    if not message:
        return False, "Please describe your issue."
    if len(message) > 5000:
        return False, "Message is too long (5,000 characters max)."
    if not rate_limit(user["email"], "ticket"):
        return False, "You've sent several tickets already — please wait a minute."
    ticket_id = uuid.uuid4().hex[:8]
    if not store.insert_ticket(ticket_id, user["email"], subject, message):
        return False, "Could not submit the ticket. Please try again."
    return True, ticket_id


# ─────────────────────────────────────────────────────────────────────
# BOOTSTRAP
# ─────────────────────────────────────────────────────────────────────
def bootstrap() -> None:
    """Prepare the database and import any pre-SQLite data. Idempotent."""
    store.ensure_db()
    store.migrate_legacy_json()
