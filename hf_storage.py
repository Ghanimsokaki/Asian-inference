"""
hf_storage.py — backend-managed Hugging Face Hub storage.

Users never see or manage a repository. Dataset payloads live in one private
Hub dataset repo owned by the platform token; each trained model gets its own
private model repo. The application database keeps only metadata and an opaque
object path.

Uploads use the Hub's real commit endpoint (newline-delimited JSON over
``/api/{type}s/{repo}/commit/{revision}``). The previous multipart form-post
was not an API the Hub serves, so every upload failed and no dataset could
ever be saved.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
import time
from typing import Any

import requests

import config

HF_ENDPOINT = "https://huggingface.co"
TIMEOUT = 30
_WHOAMI_TTL = 300  # seconds

_whoami_cache: dict[str, tuple[float, str | None]] = {}
_cache_lock = threading.Lock()


class HFError(RuntimeError):
    """A Hugging Face API call failed."""


def _token(token: str | None = None) -> str:
    return token or config.HF_TOKEN or ""


def _headers(token: str | None = None, content_type: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    value = _token(token)
    if value:
        headers["Authorization"] = f"Bearer {value}"
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value or "").strip("-.")
    return slug[:80] or "item"


def _token_fingerprint(token: str) -> str:
    """Cache key that never stores the token itself."""
    return hashlib.sha256(token.encode()).hexdigest()[:16] if token else "anonymous"


# ─────────────────────────────────────────────────────────────────────
# IDENTITY
# ─────────────────────────────────────────────────────────────────────
def whoami(token: str | None = None, *, use_cache: bool = True) -> str | None:
    """Return the authenticated Hub username, or None when unauthenticated.

    Cached briefly: this is called on every dataset save and model creation,
    and the answer only changes when the deployment's token changes.
    """
    active = _token(token)
    if not active:
        return None

    key = _token_fingerprint(active)
    now = time.time()
    if use_cache:
        with _cache_lock:
            cached = _whoami_cache.get(key)
        if cached and now - cached[0] < _WHOAMI_TTL:
            return cached[1]

    name: str | None = None
    try:
        response = requests.get(
            f"{HF_ENDPOINT}/api/whoami-v2", headers=_headers(token), timeout=TIMEOUT
        )
        if response.ok:
            payload = response.json()
            name = payload.get("name") or payload.get("fullname")
    except (requests.RequestException, ValueError):
        name = None

    with _cache_lock:
        _whoami_cache[key] = (now, name)
    return name


def clear_cache() -> None:
    with _cache_lock:
        _whoami_cache.clear()


def is_configured() -> bool:
    return bool(_token()) and whoami() is not None


def storage_diagnostic(token: str | None = None) -> str:
    """An actionable, non-sensitive description of the storage configuration."""
    if not _token(token):
        return (
            "Secure storage is not configured. An administrator needs to add a "
            "Hugging Face write token as HF_TOKEN in Streamlit secrets."
        )
    if not whoami(token):
        return (
            "Secure storage rejected the platform credentials. Check that HF_TOKEN "
            "is valid and has write access."
        )
    return "Secure storage is connected."


# ─────────────────────────────────────────────────────────────────────
# REPOSITORIES
# ─────────────────────────────────────────────────────────────────────
def storage_repo(token: str | None = None) -> str | None:
    """The single private dataset repo that holds every user's dataset blobs.

    The ``gemby-*`` prefix is deliberate: it keeps already-uploaded data on
    existing deployments reachable after the rename to Asian Inference.
    """
    username = whoami(token)
    if not username:
        return None
    suffix = hashlib.sha256(username.encode()).hexdigest()[:10]
    return f"{username}/gemby-platform-data-{suffix}"


def make_model_repo(user_email: str, model_key: str = "model", token: str | None = None) -> str | None:
    """Create (or reuse) a private per-model repo in the platform namespace."""
    username = whoami(token)
    if not username:
        return None
    slug = hashlib.sha256(f"{user_email}:{model_key}".encode()).hexdigest()[:16]
    repo_id = f"{username}/gemby-model-{slug}"
    return repo_id if ensure_repo(repo_id, "model", token) else None


def ensure_repo(repo_id: str, repo_type: str = "dataset", token: str | None = None) -> bool:
    """Create a private repo, treating 'already exists' as success."""
    if not repo_id or "/" not in repo_id:
        return False
    namespace, name = repo_id.split("/", 1)
    payload = {"name": name, "organization": None, "private": True, "type": repo_type}
    try:
        response = requests.post(
            f"{HF_ENDPOINT}/api/repos/create",
            headers=_headers(token, "application/json"),
            data=json.dumps(payload),
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return False
    if response.ok or response.status_code == 409:
        return True
    # The Hub answers 400 with a "already created" style message in some cases.
    return "already" in (response.text or "").lower()


def storage_path(item_id: str) -> str:
    return f"items/{_safe_slug(item_id)}.json"


# ─────────────────────────────────────────────────────────────────────
# OBJECTS
# ─────────────────────────────────────────────────────────────────────
def _commit(repo_id: str, repo_type: str, operations: list[dict],
            summary: str, token: str | None = None) -> bool:
    """Send one commit to the Hub using its newline-delimited JSON protocol."""
    lines = [json.dumps({"key": "header", "value": {"summary": summary}})]
    lines += [json.dumps(op) for op in operations]
    body = ("\n".join(lines) + "\n").encode()
    try:
        response = requests.post(
            f"{HF_ENDPOINT}/api/{repo_type}s/{repo_id}/commit/main",
            headers=_headers(token, "application/x-ndjson"),
            data=body,
            timeout=TIMEOUT,
        )
        return response.ok
    except requests.RequestException:
        return False


def put_json(repo_id: str, path: str, value: Any, token: str | None = None,
             repo_type: str = "dataset") -> bool:
    """Upload a JSON object to a private repo. Returns True on success."""
    if not repo_id or not path:
        return False
    if not ensure_repo(repo_id, repo_type, token):
        return False

    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    operation = {
        "key": "file",
        "value": {
            "path": path,
            "content": base64.b64encode(payload).decode(),
            "encoding": "base64",
        },
    }
    return _commit(repo_id, repo_type, [operation], f"Store {path}", token)


def get_json(repo_id: str, path: str, token: str | None = None,
             repo_type: str = "dataset") -> Any | None:
    """Fetch a JSON object previously written by :func:`put_json`."""
    if not repo_id or not path:
        return None
    try:
        response = requests.get(
            f"{HF_ENDPOINT}/{repo_type}s/{repo_id}/resolve/main/{path}",
            headers=_headers(token),
            timeout=TIMEOUT,
        )
        if response.ok:
            return response.json()
    except (requests.RequestException, ValueError):
        pass
    return None


def delete_file(repo_id: str, path: str, token: str | None = None,
                repo_type: str = "dataset") -> bool:
    """Delete an object via a deletion commit."""
    if not repo_id or not path:
        return False
    operation = {"key": "deletedFile", "value": {"path": path}}
    return _commit(repo_id, repo_type, [operation], f"Delete {path}", token)
