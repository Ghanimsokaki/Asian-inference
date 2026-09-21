"""Minimal GitHub OAuth config reader for the starter app."""
from __future__ import annotations

from settings import secret


def github_oauth_settings() -> dict[str, str]:
    return {
        "client_id": secret("GITHUB_CLIENT_ID").strip(),
        "client_secret": secret("GITHUB_CLIENT_SECRET").strip(),
        "callback_url": secret("GITHUB_CALLBACK_URL").strip(),
    }


def github_oauth_ready() -> bool:
    settings = github_oauth_settings()
    return bool(settings["client_id"] and settings["client_secret"] and settings["callback_url"])
