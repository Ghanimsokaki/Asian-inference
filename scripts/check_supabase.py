"""Safe, read-only Supabase configuration diagnostic (unless --write-test is passed).

Run from the repository: python scripts/check_supabase.py [--write-test]
Never prints keys, response bodies, probe tokens or user records.
"""
from __future__ import annotations

import argparse
import difflib
import os
from pathlib import Path
import sys
import tomllib
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import supabase_backend  # noqa: E402
import supabase_memory  # noqa: E402
import requests  # noqa: E402

KEYS = ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY", "SUPABASE_ANON_KEY",
        "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_KEY")
SETTINGS = ("SUPABASE_URL", *KEYS, "SUPABASE_SCHEMA", "SUPABASE_CHAT_TABLE",
            "SUPABASE_APP_PREFIX", "SUPABASE_PRIMARY_BACKEND")
ADDRESS = "__diagnostic__@asian-inference.invalid"
TIMEOUT = 20


def inspect_settings(path: Path) -> dict:
    """Show locations, not values. Catch nesting and probable spelling mistakes."""
    document: dict = {}
    if path.exists():
        try:
            with path.open("rb") as handle:
                document = tomllib.load(handle)
        except tomllib.TOMLDecodeError:
            print(f"{path}: {config.SECRETS_TOML_ERROR or 'invalid TOML'} (fix before testing)")
        except OSError:
            print(f"{path}: cannot read secrets file")

    def nested(obj: dict, prefix: str = "") -> None:
        for key, value in obj.items():
            location = f"{prefix}.{key}" if prefix else key
            if prefix and key in SETTINGS:
                print(f"WARNING: {location} is nested under [{prefix}]; move {key} to the top level")
            if key.upper().startswith(("SUP", "SUB")) and key not in SETTINGS:
                match = difflib.get_close_matches(key.upper(), SETTINGS, n=1, cutoff=0.75)
                print(f"WARNING: {location} is not a recognized setting" +
                      (f"; did you mean {match[0]}?" if match else ""))
            if isinstance(value, dict):
                nested(value, location)

    nested(document)
    for name in SETTINGS:
        if name in document and not isinstance(document[name], dict):
            source = str(path)
        elif name in os.environ:
            source = "environment"
        else:
            source = "default" if name not in ("SUPABASE_URL", *KEYS) else "missing"
        print(f"{name}: {source}")
    return document


def _probe_request(method: str, table: str, *, params: dict | None = None,
                   row: dict | None = None) -> list[dict] | None:
    """Require a JSON representation; 2xx with [] does not prove a write."""
    headers = supabase_backend._headers(write=method != "GET", representation=True)
    if method != "GET":
        headers["Prefer"] = "return=representation"
    try:
        response = requests.request(method, f"{config.SUPABASE_URL}/rest/v1/{table}",
                                    headers=headers, params=params, json=row, timeout=TIMEOUT)
        if not response.ok:
            return None
        data = response.json()
        return data if isinstance(data, list) else None
    except (requests.RequestException, ValueError):
        return None


def _eq(value: str) -> str:
    return f"eq.{value}"


def _roundtrip(table: str, row: dict, identity: dict[str, str]) -> bool:
    """Insert, select, then delete a unique row; always attempt cleanup."""
    existing = _probe_request("GET", table, params={**{k: _eq(v) for k, v in identity.items()},
                                                  "select": next(iter(identity))})
    if existing is None or existing:
        return False  # Never overwrite or delete a pre-existing row.
    created = _probe_request("POST", table, row=row)
    inserted = bool(created and any(all(item.get(k) == v for k, v in identity.items())
                                    for item in created))
    if not inserted:
        # A 200 [] can still have written a row hidden by RLS. The identity is
        # unique, so attempt best-effort cleanup, but never call this on a user.
        _probe_request("DELETE", table, params={k: _eq(v) for k, v in identity.items()})
        return False
    selected = _probe_request("GET", table,
                              params={**{k: _eq(v) for k, v in identity.items()}, "select": "*"})
    deleted = _probe_request("DELETE", table,
                             params={k: _eq(v) for k, v in identity.items()})
    if not deleted or not any(all(item.get(k) == v for k, v in identity.items())
                              for item in deleted):
        print(f"WARNING: cleanup for {table} was not confirmed; remove the diagnostic row manually")
        return False
    remaining = _probe_request("GET", table,
                               params={**{k: _eq(v) for k, v in identity.items()}, "select": "*"})
    return bool(selected and any(all(item.get(k) == v for k, v in identity.items())
                                 for item in selected) and remaining == [])


def write_test() -> bool:
    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        print("Write test skipped: Supabase URL or key missing")
        return False
    marker = uuid.uuid4().hex
    chat_table = config.SUPABASE_CHAT_TABLE
    chat_ok = _roundtrip(chat_table,
                         {"user_email": ADDRESS, "role": "user", "content": marker},
                         {"user_email": ADDRESS, "content": marker})
    print(f"Chat memory write/read/delete: {'passed' if chat_ok else 'failed'}")

    users = supabase_backend._table("users")
    sessions = supabase_backend._table("auth_sessions")
    # A session references users(email). Never replace an existing account at the
    # reserved address, even when the diagnostic cannot see it through RLS.
    existing = _probe_request("GET", users, params={"email": _eq(ADDRESS), "select": "email"})
    if existing is None or existing:
        print("App tables write test skipped: reserved account unavailable or already exists")
        return False
    created = _probe_request("POST", users,
                             row={"email": ADDRESS, "name": "Diagnostic probe", "pw_hash": "invalid"})
    if not created or not any(item.get("email") == ADDRESS for item in created):
        print("App tables write test failed: user insert not confirmed (possibly RLS)")
        # An unseen write may have succeeded; cleanup is best-effort.
        _probe_request("DELETE", users, params={"email": _eq(ADDRESS)})
        return False
    user_ok = False
    session_ok = False
    cleanup_ok = False
    try:
        selected = _probe_request("GET", users, params={"email": _eq(ADDRESS), "select": "email"})
        user_ok = bool(selected and any(item.get("email") == ADDRESS for item in selected))
        if user_ok:
            session_ok = _roundtrip(sessions,
                                    {"token_hash": marker, "user_email": ADDRESS},
                                    {"token_hash": marker})
    finally:
        deleted = _probe_request("DELETE", users, params={"email": _eq(ADDRESS)})
        cleanup_ok = bool(deleted and any(item.get("email") == ADDRESS for item in deleted))
        if not cleanup_ok:
            print("WARNING: cleanup for diagnostic user was not confirmed; remove it manually")
    print(f"App tables write/read/delete: {'passed' if user_ok and session_ok and cleanup_ok else 'failed'}")
    return chat_ok and user_ok and session_ok and cleanup_ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-test", action="store_true", help="probe writes, reads and cleanup")
    args = parser.parse_args(argv)
    inspect_settings(Path(__file__).resolve().parents[1] / ".streamlit/secrets.toml")
    print("Key family:", config.supabase_key_family())
    for check in (supabase_memory.memory_diagnostic, supabase_backend.health_diagnostic):
        ok, message = check()
        print(message)
    if args.write_test:
        return 0 if write_test() else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
