"""Supabase-backed persistence helpers.

When enabled, Streamlit keeps its UI while Supabase becomes the primary durable
backend for product data. SQLite still exists locally for fast bootstrap,
fallbacks and some transactional helpers, but core reads can come from
Supabase and writes are mirrored there immediately.
"""
from __future__ import annotations

from typing import Any

import requests

import config

TIMEOUT = 20


def is_configured() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_KEY)


def primary_enabled() -> bool:
    return bool(config.SUPABASE_PRIMARY_BACKEND and is_configured())


def _headers(*, write: bool = False, upsert: bool = False,
             representation: bool = False, count: bool = False) -> dict[str, str]:
    key = config.SUPABASE_KEY
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    if config.SUPABASE_SCHEMA and config.SUPABASE_SCHEMA != "public":
        headers["Accept-Profile"] = config.SUPABASE_SCHEMA
        if write:
            headers["Content-Profile"] = config.SUPABASE_SCHEMA
    if write:
        headers["Content-Type"] = "application/json"
        prefer: list[str] = []
        if upsert:
            prefer.append("resolution=merge-duplicates")
        prefer.append("return=representation" if representation else "return=minimal")
        headers["Prefer"] = ",".join(prefer)
    if count:
        headers["Prefer"] = (headers.get("Prefer", "") + ",count=exact").strip(",")
    return headers


def _table(name: str) -> str:
    prefix = (config.SUPABASE_APP_PREFIX or "ai").strip().strip("_") or "ai"
    return f"{prefix}_{name}"


def _endpoint(name: str) -> str:
    return f"{config.SUPABASE_URL}/rest/v1/{_table(name)}"


def _request(method: str, name: str, *, params: dict[str, str] | None = None,
             json_body: Any = None, write: bool = False, upsert: bool = False,
             representation: bool = False, count: bool = False) -> requests.Response | None:
    if not is_configured():
        return None
    try:
        return requests.request(
            method,
            _endpoint(name),
            headers=_headers(write=write, upsert=upsert,
                             representation=representation, count=count),
            params=params,
            json=json_body,
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return None


def _eq(value: Any) -> str:
    return f"eq.{value}"


def _fetch(name: str, *, select: str = "*", order: str = "", limit: int | None = None,
           filters: dict[str, Any] | None = None) -> list[dict]:
    if not is_configured():
        return []
    params: dict[str, str] = {"select": select}
    if order:
        params["order"] = order
    if limit is not None:
        params["limit"] = str(limit)
    for key, value in (filters or {}).items():
        params[key] = _eq(value)
    response = _request("GET", name, params=params)
    if not response or not response.ok:
        return []
    try:
        payload = response.json()
        return payload if isinstance(payload, list) else []
    except ValueError:
        return []


def _fetch_one(name: str, *, filters: dict[str, Any], select: str = "*") -> dict | None:
    rows = _fetch(name, select=select, filters=filters, limit=1)
    return rows[0] if rows else None


def _count(name: str, *, filters: dict[str, Any] | None = None) -> int:
    params = {"select": "id"}
    for key, value in (filters or {}).items():
        params[key] = _eq(value)
    response = _request("GET", name, params=params, count=True)
    if not response or not response.ok:
        return 0
    content_range = response.headers.get("content-range", "")
    if "/" in content_range:
        try:
            return int(content_range.rsplit("/", 1)[1])
        except ValueError:
            return 0
    return 0


def _upsert(name: str, row: dict[str, Any], *, on_conflict: str) -> bool:
    if not is_configured() or not row:
        return False
    response = _request(
        "POST", name,
        params={"on_conflict": on_conflict},
        json_body=row, write=True, upsert=True,
    )
    return bool(response and response.ok)


def _insert(name: str, row: dict[str, Any]) -> bool:
    if not is_configured() or not row:
        return False
    response = _request("POST", name, json_body=row, write=True)
    return bool(response and response.ok)


def _delete(name: str, **filters: Any) -> bool:
    if not is_configured() or not filters:
        return False
    response = _request(
        "DELETE", name,
        params={key: _eq(value) for key, value in filters.items()},
        write=True,
    )
    return bool(response and response.ok)


def _user_row(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "email": row.get("email"),
        "name": row.get("name") or "",
        "pw_hash": row.get("pw_hash") or "",
        "plan": row.get("plan") or "starter",
        "tokens": int(row.get("tokens") or 0),
        "flagged": bool(row.get("flagged")),
        "flag_reason": row.get("flag_reason") or "",
        "platform_api_key": row.get("platform_api_key"),
        "traakteer_id": row.get("traakteer_id") or "",
        "stripe_customer_id": row.get("stripe_customer_id"),
        "stripe_subscription_id": row.get("stripe_subscription_id"),
        "created": row.get("created") or row.get("created_at"),
        "updated": row.get("updated") or row.get("updated_at"),
        "last_reset": row.get("last_reset"),
    }


def _dataset_row(row: dict | None, *, with_rows: bool = True) -> dict | None:
    if not row:
        return None
    data = {
        "id": row.get("id"),
        "owner": row.get("owner"),
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "row_count": int(row.get("row_count") or 0),
        "public": bool(row.get("public")),
        "tags": row.get("tags") or [],
        "downloads": int(row.get("downloads") or 0),
        "likes": int(row.get("likes") or 0),
        "storage_backend": row.get("storage_backend") or "local",
        "storage_repo": row.get("storage_repo"),
        "storage_path": row.get("storage_path"),
        "created": row.get("created") or row.get("created_at"),
        "updated": row.get("updated") or row.get("updated_at"),
    }
    if with_rows:
        data["rows"] = row.get("rows") or []
    return data


def _model_row(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": row.get("id"),
        "owner": row.get("owner"),
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "base_model": row.get("base_model") or "",
        "hf_repo": row.get("hf_repo") or "",
        "public": bool(row.get("public")),
        "tags": row.get("tags") or [],
        "status": row.get("status") or "ready",
        "downloads": int(row.get("downloads") or 0),
        "likes": int(row.get("likes") or 0),
        "created": row.get("created") or row.get("created_at"),
        "updated": row.get("updated") or row.get("updated_at"),
    }


def health_diagnostic() -> tuple[bool, str]:
    if not is_configured():
        return False, config.supabase_not_configured_message(
            "Supabase app backend is not configured."
        )
    response = _request("GET", "users", params={"select": "email", "limit": "1"})
    if response is None:
        return False, "Supabase app backend could not be reached."
    if response.ok:
        mode = "primary backend" if primary_enabled() else "mirror"
        return True, f"Supabase app backend {mode} is connected."
    if response.status_code == 404:
        return False, "Supabase app tables are missing. Run supabase_schema.sql."
    return False, "Supabase app backend rejected the configured credentials."


# ─────────────────────────────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────────────────────────────
def upsert_user(user: dict[str, Any]) -> bool:
    return _upsert(
        "users",
        {
            "email": user.get("email"),
            "name": user.get("name") or "",
            "pw_hash": user.get("pw_hash") or "",
            "plan": user.get("plan") or "starter",
            "tokens": int(user.get("tokens") or 0),
            "flagged": bool(user.get("flagged")),
            "flag_reason": user.get("flag_reason") or "",
            "platform_api_key": user.get("platform_api_key"),
            "traakteer_id": user.get("traakteer_id") or "",
            "stripe_customer_id": user.get("stripe_customer_id"),
            "stripe_subscription_id": user.get("stripe_subscription_id"),
            "created": user.get("created"),
            "updated": user.get("updated"),
            "last_reset": user.get("last_reset"),
        },
        on_conflict="email",
    )


def get_user(email: str) -> dict | None:
    return _user_row(_fetch_one("users", filters={"email": email.strip().lower()}))


def list_users() -> list[dict]:
    return [_user_row(row) for row in _fetch("users", order="created.desc")]


def count_users() -> int:
    return _count("users")


def find_user_by_platform_key(key: str) -> dict | None:
    return _user_row(_fetch_one("users", filters={"platform_api_key": key}))


def delete_user(email: str) -> bool:
    return _delete("users", email=email.strip().lower())


# ─────────────────────────────────────────────────────────────────────
# PERSISTENT AUTH SESSIONS
# ─────────────────────────────────────────────────────────────────────
def upsert_auth_session(session: dict[str, Any]) -> bool:
    return _upsert(
        "auth_sessions",
        {
            "token_hash": session.get("token_hash"),
            "user_email": (session.get("user_email") or "").strip().lower(),
            "created_at": session.get("created_at"),
            "expires_at": session.get("expires_at"),
            "last_seen_at": session.get("last_seen_at"),
        },
        on_conflict="token_hash",
    )


def get_auth_session(token_hash: str) -> dict | None:
    return _fetch_one("auth_sessions", filters={"token_hash": token_hash})


def delete_auth_session(token_hash: str) -> bool:
    return _delete("auth_sessions", token_hash=token_hash)


def delete_auth_sessions_for_user(email: str) -> bool:
    return _delete("auth_sessions", user_email=email.strip().lower())


# ─────────────────────────────────────────────────────────────────────
# TOKEN LOGS
# ─────────────────────────────────────────────────────────────────────
def append_token_log(entry: dict[str, Any]) -> bool:
    return _insert(
        "token_logs",
        {
            "user_email": entry.get("user_email"),
            "delta": int(entry.get("delta") or 0),
            "reason": entry.get("reason") or "",
            "balance": int(entry.get("balance") or 0),
            "created_at": entry.get("created_at"),
        },
    )


def token_history(email: str, limit: int = 100) -> list[dict]:
    rows = _fetch(
        "token_logs",
        select="delta,reason,balance,created_at",
        filters={"user_email": email},
        order="created_at.desc,id.desc",
        limit=limit,
    )
    return [
        {
            "delta": int(row.get("delta") or 0),
            "reason": row.get("reason") or "",
            "balance": int(row.get("balance") or 0),
            "created_at": row.get("created_at"),
        }
        for row in rows
    ]


def count_recent_grants(email: str, since_iso: str, needle: str) -> int:
    rows = _fetch(
        "token_logs",
        select="reason,created_at",
        filters={"user_email": email},
        order="created_at.desc",
        limit=500,
    )
    return sum(
        1 for row in rows
        if str(row.get("created_at") or "") >= since_iso and needle in str(row.get("reason") or "")
    )


# ─────────────────────────────────────────────────────────────────────
# DATASETS
# ─────────────────────────────────────────────────────────────────────
def upsert_dataset(dataset: dict[str, Any]) -> bool:
    return _upsert(
        "datasets",
        {
            "id": dataset.get("id"),
            "owner": dataset.get("owner"),
            "name": dataset.get("name") or "",
            "description": dataset.get("description") or "",
            "rows": dataset.get("rows") or [],
            "row_count": int(dataset.get("row_count") or 0),
            "public": bool(dataset.get("public")),
            "tags": dataset.get("tags") or [],
            "downloads": int(dataset.get("downloads") or 0),
            "likes": int(dataset.get("likes") or 0),
            "storage_backend": dataset.get("storage_backend") or "local",
            "storage_repo": dataset.get("storage_repo"),
            "storage_path": dataset.get("storage_path"),
            "created": dataset.get("created"),
            "updated": dataset.get("updated"),
        },
        on_conflict="id",
    )


def get_dataset(dataset_id: str, *, with_rows: bool = True) -> dict | None:
    select = "*" if with_rows else "id,owner,name,description,row_count,public,tags,downloads,likes,storage_backend,storage_repo,storage_path,created,updated"
    return _dataset_row(_fetch_one("datasets", filters={"id": dataset_id}, select=select), with_rows=with_rows)


def user_datasets(email: str, *, with_rows: bool = True) -> list[dict]:
    select = "*" if with_rows else "id,owner,name,description,row_count,public,tags,downloads,likes,storage_backend,storage_repo,storage_path,created,updated"
    return [
        _dataset_row(row, with_rows=with_rows)
        for row in _fetch("datasets", select=select, filters={"owner": email}, order="created.desc")
    ]


def public_datasets(*, with_rows: bool = True, limit: int = 200) -> list[dict]:
    select = "*" if with_rows else "id,owner,name,description,row_count,public,tags,downloads,likes,storage_backend,storage_repo,storage_path,created,updated"
    return [
        _dataset_row(row, with_rows=with_rows)
        for row in _fetch("datasets", select=select, filters={"public": "true"}, order="created.desc", limit=limit)
    ]


def all_datasets(*, with_rows: bool = False) -> list[dict]:
    select = "*" if with_rows else "id,owner,name,description,row_count,public,tags,downloads,likes,storage_backend,storage_repo,storage_path,created,updated"
    return [_dataset_row(row, with_rows=with_rows) for row in _fetch("datasets", select=select, order="created.desc")]


def count_user_datasets(email: str) -> int:
    return _count("datasets", filters={"owner": email})


def delete_dataset(dataset_id: str) -> bool:
    return _delete("datasets", id=dataset_id)


# ─────────────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────────────
def upsert_model(model: dict[str, Any]) -> bool:
    return _upsert(
        "models",
        {
            "id": model.get("id"),
            "owner": model.get("owner"),
            "name": model.get("name") or "",
            "description": model.get("description") or "",
            "base_model": model.get("base_model") or "",
            "hf_repo": model.get("hf_repo") or "",
            "public": bool(model.get("public")),
            "tags": model.get("tags") or [],
            "status": model.get("status") or "ready",
            "downloads": int(model.get("downloads") or 0),
            "likes": int(model.get("likes") or 0),
            "created": model.get("created"),
            "updated": model.get("updated"),
        },
        on_conflict="id",
    )


def get_model(model_id: str) -> dict | None:
    return _model_row(_fetch_one("models", filters={"id": model_id}))


def user_models(email: str) -> list[dict]:
    return [_model_row(row) for row in _fetch("models", filters={"owner": email}, order="created.desc")]


def public_models(limit: int = 200) -> list[dict]:
    return [_model_row(row) for row in _fetch("models", filters={"public": "true"}, order="created.desc", limit=limit)]


def all_models() -> list[dict]:
    return [_model_row(row) for row in _fetch("models", order="created.desc")]


def count_user_models(email: str) -> int:
    return _count("models", filters={"owner": email})


def delete_model(model_id: str) -> bool:
    return _delete("models", id=model_id)


# ─────────────────────────────────────────────────────────────────────
# API KEYS
# ─────────────────────────────────────────────────────────────────────
def upsert_api_key(user_email: str, entry: dict[str, Any]) -> bool:
    label = str(entry.get("label") or "")
    composite_id = f"{user_email.strip().lower()}::{label}"
    return _upsert(
        "api_keys",
        {
            "id": composite_id,
            "user_email": user_email.strip().lower(),
            "label": label,
            "key_value": entry.get("key_value") or "",
            "uses": int(entry.get("uses") or 0),
            "last_used": entry.get("last_used"),
            "created_at": entry.get("created_at"),
        },
        on_conflict="id",
    )


def user_api_keys(email: str) -> list[dict]:
    rows = _fetch("api_keys", filters={"user_email": email}, order="created_at.desc")
    return [
        {
            "label": row.get("label") or "",
            "key_value": row.get("key_value") or "",
            "uses": int(row.get("uses") or 0),
            "last_used": row.get("last_used"),
            "created_at": row.get("created_at"),
        }
        for row in rows
    ]


def count_user_api_keys(email: str) -> int:
    return _count("api_keys", filters={"user_email": email})


def delete_api_key(user_email: str, label: str) -> bool:
    composite_id = f"{user_email.strip().lower()}::{label}"
    return _delete("api_keys", id=composite_id)


# ─────────────────────────────────────────────────────────────────────
# SUPPORT TICKETS
# ─────────────────────────────────────────────────────────────────────
def upsert_support_ticket(ticket: dict[str, Any]) -> bool:
    return _upsert(
        "support_tickets",
        {
            "id": ticket.get("id"),
            "user_email": ticket.get("user_email"),
            "subject": ticket.get("subject") or "",
            "message": ticket.get("message") or "",
            "status": ticket.get("status") or "open",
            "admin_reply": ticket.get("admin_reply") or "",
            "created_at": ticket.get("created_at"),
        },
        on_conflict="id",
    )


def get_ticket(ticket_id: str) -> dict | None:
    return _fetch_one("support_tickets", filters={"id": ticket_id})


def list_tickets(status: str | None = None) -> list[dict]:
    filters = {"status": status} if status else None
    return _fetch("support_tickets", filters=filters, order="created_at.desc")


def user_tickets(email: str) -> list[dict]:
    return _fetch("support_tickets", filters={"user_email": email}, order="created_at.desc")


def count_open_tickets() -> int:
    return _count("support_tickets", filters={"status": "open"})


# ─────────────────────────────────────────────────────────────────────
# ANNOUNCEMENTS
# ─────────────────────────────────────────────────────────────────────
def upsert_announcement(announcement: dict[str, Any]) -> bool:
    return _upsert(
        "announcements",
        {
            "id": 1,
            "message": announcement.get("message") or "",
            "author": announcement.get("author") or "",
            "active": bool(announcement.get("active")),
            "created_at": announcement.get("created_at"),
            "updated_at": announcement.get("updated_at"),
        },
        on_conflict="id",
    )


def get_announcement() -> dict | None:
    return _fetch_one("announcements", filters={"id": 1})


# ─────────────────────────────────────────────────────────────────────
# BILLING
# ─────────────────────────────────────────────────────────────────────
def append_billing_event(email: str, event_type: str, details: dict | None, created_at: str) -> bool:
    return _insert(
        "billing_events",
        {
            "user_email": email,
            "event_type": event_type,
            "details": details or {},
            "created_at": created_at,
        },
    )


def billing_history(email: str, limit: int = 100) -> list[dict]:
    return _fetch(
        "billing_events",
        filters={"user_email": email},
        order="created_at.desc,id.desc",
        limit=limit,
    )


# ─────────────────────────────────────────────────────────────────────
# WEBHOOK CLAIMS
# ─────────────────────────────────────────────────────────────────────
def claim_processed_webhook(event_id: str, provider: str, created_at: str) -> bool:
    if not event_id:
        return True
    response = _request(
        "POST", "processed_webhooks",
        json_body={"event_id": event_id, "provider": provider, "created_at": created_at},
        write=True,
    )
    if response is None:
        return False
    if response.ok:
        return True
    if response.status_code in {409, 400}:
        return False
    return False


# ─────────────────────────────────────────────────────────────────────
# SNAPSHOT FOR LOCAL RECOVERY
# ─────────────────────────────────────────────────────────────────────
def fetch_bootstrap_snapshot() -> dict[str, list[dict] | dict | None]:
    return {
        "users": _fetch("users", order="created.asc"),
        "datasets": _fetch("datasets", order="created.asc"),
        "models": _fetch("models", order="created.asc"),
        "api_keys": _fetch("api_keys", order="created_at.asc"),
        "support_tickets": _fetch("support_tickets", order="created_at.asc"),
        "token_logs": _fetch("token_logs", order="created_at.asc,id.asc", limit=5000),
        "billing_events": _fetch("billing_events", order="created_at.asc,id.asc", limit=5000),
        "auth_sessions": _fetch("auth_sessions", order="created_at.asc", limit=5000),
        "announcement": get_announcement(),
    }
