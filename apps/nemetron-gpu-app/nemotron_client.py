"""Nemotron client that reads credentials from Streamlit secrets or environment variables."""
from __future__ import annotations

from typing import Any

import requests

from settings import secret

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = secret("OPENROUTER_MODEL", "nvidia/llama-3.1-nemotron-70b-instruct")
TIMEOUT = 120


class NemotronConfigError(RuntimeError):
    pass


class NemotronRequestError(RuntimeError):
    pass


def configured_api_key() -> str:
    key = secret("OPENROUTER_API_KEY").strip()
    if not key:
        raise NemotronConfigError(
            "OPENROUTER_API_KEY is missing. Set it in Streamlit secrets or environment variables."
        )
    return key


def generate_nemotron_reply(prompt: str, model: str | None = None,
                            system_prompt: str | None = None,
                            temperature: float = 0.4,
                            max_tokens: int = 700) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        raise NemotronRequestError("Prompt is required.")

    headers = {
        "Authorization": f"Bearer {configured_api_key()}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": [],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if system_prompt:
        payload["messages"].append({"role": "system", "content": system_prompt})
    payload["messages"].append({"role": "user", "content": prompt})

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise NemotronRequestError(f"Could not reach OpenRouter: {exc}") from exc

    if response.status_code in {401, 403}:
        raise NemotronRequestError(
            "The OpenRouter API key was rejected. Update OPENROUTER_API_KEY in Streamlit secrets or deployment secrets."
        )
    if not response.ok:
        raise NemotronRequestError(
            f"Nemotron request failed with HTTP {response.status_code}."
        )

    try:
        data = response.json()
        return str(data["choices"][0]["message"]["content"]).strip()
    except Exception as exc:  # noqa: BLE001
        raise NemotronRequestError("Nemotron returned an unreadable response.") from exc
