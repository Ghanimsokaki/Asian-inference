"""Backend-managed Hugging Face Hub storage.

The Streamlit UI never needs to know where large dataset files live. Only
small metadata and opaque storage paths are kept in the app database.
"""
import hashlib
import json
import re
from typing import Any

import requests

from core import HF_TOKEN

HF_API = "https://huggingface.co"
_TIMEOUT = 30


def _headers(token: str | None = None) -> dict[str, str]:
    value = token or HF_TOKEN
    return {"Authorization": f"Bearer {value}"} if value else {}


def _safe_slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-")
    return value[:80] or "item"


def whoami(token: str | None = None) -> str | None:
    """Return the authenticated HF username without exposing the token."""
    try:
        response = requests.get(f"{HF_API}/api/whoami-v2", headers=_headers(token), timeout=_TIMEOUT)
        if response.ok:
            return response.json().get("name") or response.json().get("fullname")
    except requests.RequestException:
        pass
    return None


def storage_repo(token: str | None = None) -> str | None:
    """Return the single private dataset repository used by the platform."""
    username = whoami(token)
    if not username:
        return None
    suffix = hashlib.sha256(username.encode()).hexdigest()[:10]
    return f"{username}/gemby-platform-data-{suffix}"


def storage_diagnostic(token: str | None = None) -> str:
    """Return an actionable, non-sensitive configuration message."""
    active_token = token or HF_TOKEN
    if not active_token:
        return "The platform storage connection is not configured. An administrator must add HF_TOKEN to Streamlit Secrets."
    if not whoami(active_token):
        return "The platform storage connection was rejected. Check that HF_TOKEN is valid and has write access."
    return "The platform storage connection is ready."


def ensure_repo(repo_id: str, repo_type: str = "dataset", token: str | None = None) -> bool:
    payload = {"name": repo_id.split("/", 1)[-1], "private": True, "type": repo_type}
    try:
        response = requests.post(f"{HF_API}/api/repos/create", headers=_headers(token), json=payload, timeout=_TIMEOUT)
        return response.ok or response.status_code == 409
    except requests.RequestException:
        return False


def put_json(repo_id: str, path: str, value: Any, token: str | None = None) -> bool:
    """Upload JSON into a private HF dataset repo."""
    if not repo_id or not ensure_repo(repo_id, "dataset", token):
        return False
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    try:
        response = requests.post(
            f"{HF_API}/api/datasets/{repo_id}/commit/main",
            headers=_headers(token),
            data={"summary": f"Store {path}"},
            files={"file": (path, payload, "application/json")},
            timeout=_TIMEOUT,
        )
        return response.ok
    except requests.RequestException:
        return False


def get_json(repo_id: str, path: str, token: str | None = None) -> Any | None:
    if not repo_id or not path:
        return None
    try:
        response = requests.get(f"{HF_API}/datasets/{repo_id}/resolve/main/{path}", headers=_headers(token), timeout=_TIMEOUT)
        if response.ok:
            return response.json()
    except (requests.RequestException, ValueError):
        pass
    return None


def delete_file(repo_id: str, path: str, token: str | None = None) -> bool:
    if not repo_id or not path:
        return False
    try:
        response = requests.delete(
            f"{HF_API}/api/datasets/{repo_id}/delete",
            headers=_headers(token), json={"path": path}, timeout=_TIMEOUT,
        )
        return response.ok
    except requests.RequestException:
        return False


def make_model_repo(user_email: str, model_key: str = "model", token: str | None = None) -> str | None:
    """Create an opaque model repo in the platform HF namespace."""
    username = whoami(token)
    if not username:
        return None
    slug = hashlib.sha256(f"{user_email}:{model_key}".encode()).hexdigest()[:16]
    repo_id = f"{username}/gemby-model-{slug}"
    return repo_id if ensure_repo(repo_id, "model", token) else None


def storage_path(item_id: str) -> str:
    return f"items/{_safe_slug(item_id)}.json"
