"""
store.py — the single persistence layer for the platform.

Replaces the previous split between a JSON file (``db.json``) and an unused
SQLite module. Everything is SQLite now:

* one connection per thread (Streamlit runs each session in its own thread)
* WAL journalling so readers never block the writer
* schema migrations keyed off ``PRAGMA user_version``
* every write wrapped in a transaction

Nothing in this module knows about plans, pricing or Streamlit — it is pure
storage. Business rules live in :mod:`core`.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from config import DB_PATH, LEGACY_DB_JSON

SCHEMA_VERSION = 1

_local = threading.local()
_init_lock = threading.Lock()
_initialised = False


def utcnow() -> str:
    """Timezone-aware UTC timestamp in ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─────────────────────────────────────────────────────────────────────
# CONNECTION HANDLING
# ─────────────────────────────────────────────────────────────────────
def _connect() -> sqlite3.Connection:
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def connection() -> sqlite3.Connection:
    """Return this thread's connection, creating the schema on first use."""
    ensure_db()
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _local.conn = _connect()
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Run a block inside a single write transaction."""
    conn = connection()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def close_thread_connection() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def reset_for_tests(db_path: str | Path | None = None) -> None:
    """Point the store at a fresh database. Test-support only."""
    global _initialised
    import config

    close_thread_connection()
    if db_path is not None:
        config.DB_PATH = Path(db_path)
        globals()["DB_PATH"] = Path(db_path)
    with _init_lock:
        _initialised = False


# ─────────────────────────────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    email                  TEXT PRIMARY KEY,
    name                   TEXT NOT NULL DEFAULT '',
    pw_hash                TEXT NOT NULL,
    plan                   TEXT NOT NULL DEFAULT 'starter',
    tokens                 INTEGER NOT NULL DEFAULT 0,
    flagged                INTEGER NOT NULL DEFAULT 0,
    flag_reason            TEXT NOT NULL DEFAULT '',
    platform_api_key       TEXT UNIQUE,
    traakteer_id           TEXT NOT NULL DEFAULT '',
    stripe_customer_id     TEXT,
    stripe_subscription_id TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    last_reset             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS token_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    delta      INTEGER NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    balance    INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_token_logs_user ON token_logs(user_email, created_at DESC);

CREATE TABLE IF NOT EXISTS datasets (
    id              TEXT PRIMARY KEY,
    owner           TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    rows_json       TEXT NOT NULL DEFAULT '[]',
    row_count       INTEGER NOT NULL DEFAULT 0,
    public          INTEGER NOT NULL DEFAULT 0,
    tags_json       TEXT NOT NULL DEFAULT '[]',
    downloads       INTEGER NOT NULL DEFAULT 0,
    likes           INTEGER NOT NULL DEFAULT 0,
    storage_backend TEXT NOT NULL DEFAULT 'local',
    storage_repo    TEXT,
    storage_path    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_datasets_owner  ON datasets(owner, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_datasets_public ON datasets(public, created_at DESC);

CREATE TABLE IF NOT EXISTS models (
    id          TEXT PRIMARY KEY,
    owner       TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    base_model  TEXT NOT NULL,
    hf_repo     TEXT NOT NULL DEFAULT '',
    public      INTEGER NOT NULL DEFAULT 0,
    tags_json   TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'ready',
    downloads   INTEGER NOT NULL DEFAULT 0,
    likes       INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_models_owner  ON models(owner, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_models_public ON models(public, created_at DESC);

CREATE TABLE IF NOT EXISTS api_keys (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    label      TEXT NOT NULL,
    key_value  TEXT NOT NULL,
    uses       INTEGER NOT NULL DEFAULT 0,
    last_used  TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(user_email, label)
);
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_email);

CREATE TABLE IF NOT EXISTS support_tickets (
    id          TEXT PRIMARY KEY,
    user_email  TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    subject     TEXT NOT NULL,
    message     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    admin_reply TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON support_tickets(status, created_at DESC);

CREATE TABLE IF NOT EXISTS rate_limits (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    action  TEXT NOT NULL,
    ts      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rate_limits ON rate_limits(subject, action, ts);

CREATE TABLE IF NOT EXISTS billing_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL,
    event_type TEXT NOT NULL,
    details    TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_billing_user ON billing_events(user_email, created_at DESC);

CREATE TABLE IF NOT EXISTS processed_webhooks (
    event_id   TEXT PRIMARY KEY,
    provider   TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def ensure_db() -> None:
    """Create the schema once per process."""
    global _initialised
    if _initialised:
        return
    with _init_lock:
        if _initialised:
            return
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version < SCHEMA_VERSION:
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        finally:
            conn.close()
        _initialised = True


# ─────────────────────────────────────────────────────────────────────
# ROW HELPERS
# ─────────────────────────────────────────────────────────────────────
def _loads(raw: Any, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _user_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "email": row["email"],
        "name": row["name"],
        "pw_hash": row["pw_hash"],
        "plan": row["plan"],
        "tokens": row["tokens"],
        "flagged": bool(row["flagged"]),
        "flag_reason": row["flag_reason"] or "",
        "platform_api_key": row["platform_api_key"],
        "traakteer_id": row["traakteer_id"] or "",
        "stripe_customer_id": row["stripe_customer_id"],
        "stripe_subscription_id": row["stripe_subscription_id"],
        "created": row["created_at"],
        "updated": row["updated_at"],
        "last_reset": row["last_reset"],
    }


def _dataset_row(row: sqlite3.Row | None, *, with_rows: bool = True) -> dict | None:
    if row is None:
        return None
    data = {
        "id": row["id"],
        "owner": row["owner"],
        "name": row["name"],
        "description": row["description"] or "",
        "row_count": row["row_count"],
        "public": bool(row["public"]),
        "tags": _loads(row["tags_json"], []),
        "downloads": row["downloads"],
        "likes": row["likes"],
        "storage_backend": row["storage_backend"],
        "storage_repo": row["storage_repo"],
        "storage_path": row["storage_path"],
        "created": row["created_at"],
        "updated": row["updated_at"],
    }
    if with_rows:
        data["rows"] = _loads(row["rows_json"], [])
    return data


def _model_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "owner": row["owner"],
        "name": row["name"],
        "description": row["description"] or "",
        "base_model": row["base_model"],
        "hf_repo": row["hf_repo"] or "",
        "public": bool(row["public"]),
        "tags": _loads(row["tags_json"], []),
        "status": row["status"],
        "downloads": row["downloads"],
        "likes": row["likes"],
        "created": row["created_at"],
        "updated": row["updated_at"],
    }


# ─────────────────────────────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────────────────────────────
def create_user(email: str, name: str, pw_hash: str, plan: str, tokens: int) -> bool:
    """Insert a user. Returns False when the email is already registered."""
    now = utcnow()
    try:
        with transaction() as conn:
            conn.execute(
                """INSERT INTO users (email, name, pw_hash, plan, tokens,
                                      created_at, updated_at, last_reset)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (email, name, pw_hash, plan, tokens, now, now, now),
            )
            conn.execute(
                """INSERT INTO token_logs (user_email, delta, reason, balance, created_at)
                   VALUES (?, ?, 'signup', ?, ?)""",
                (email, tokens, tokens, now),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def get_user(email: str) -> dict | None:
    if not email:
        return None
    row = connection().execute(
        "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
    ).fetchone()
    return _user_row(row)


_USER_FIELDS = {
    "name", "pw_hash", "plan", "tokens", "flagged", "flag_reason",
    "platform_api_key", "traakteer_id", "stripe_customer_id",
    "stripe_subscription_id", "last_reset",
}


def update_user(email: str, **fields: Any) -> bool:
    """Update whitelisted user columns. Unknown columns raise, never silently drop."""
    unknown = set(fields) - _USER_FIELDS
    if unknown:
        raise ValueError(f"Unknown user field(s): {', '.join(sorted(unknown))}")
    if not fields:
        return False
    fields = {k: (int(v) if isinstance(v, bool) else v) for k, v in fields.items()}
    fields["updated_at"] = utcnow()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    with transaction() as conn:
        cur = conn.execute(
            f"UPDATE users SET {assignments} WHERE email = ?",
            (*fields.values(), email.strip().lower()),
        )
    return cur.rowcount > 0


def delete_user(email: str) -> bool:
    with transaction() as conn:
        cur = conn.execute("DELETE FROM users WHERE email = ?", (email.strip().lower(),))
    return cur.rowcount > 0


def list_users() -> list[dict]:
    rows = connection().execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return [_user_row(r) for r in rows]


def count_users() -> int:
    return connection().execute("SELECT COUNT(*) FROM users").fetchone()[0]


def find_user_by_platform_key(key: str) -> dict | None:
    if not key:
        return None
    row = connection().execute(
        "SELECT * FROM users WHERE platform_api_key = ?", (key,)
    ).fetchone()
    return _user_row(row)


# ─────────────────────────────────────────────────────────────────────
# TOKENS
# ─────────────────────────────────────────────────────────────────────
def add_tokens(email: str, amount: int, reason: str) -> int:
    """Credit tokens atomically and return the new balance."""
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET tokens = tokens + ?, updated_at = ? WHERE email = ?",
            (amount, utcnow(), email),
        )
        row = conn.execute("SELECT tokens FROM users WHERE email = ?", (email,)).fetchone()
        balance = row["tokens"] if row else 0
        conn.execute(
            """INSERT INTO token_logs (user_email, delta, reason, balance, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (email, amount, reason, balance, utcnow()),
        )
    return balance


def spend_tokens(email: str, amount: int, reason: str = "usage") -> tuple[bool, int]:
    """Debit tokens atomically.

    The balance check and the update happen in one transaction, so two
    concurrent generations can never both pass a check against the same
    balance. Returns ``(succeeded, balance)``.
    """
    if amount <= 0:
        row = connection().execute(
            "SELECT tokens FROM users WHERE email = ?", (email,)
        ).fetchone()
        return True, (row["tokens"] if row else 0)

    with transaction() as conn:
        cur = conn.execute(
            """UPDATE users SET tokens = tokens - ?, updated_at = ?
               WHERE email = ? AND tokens >= ?""",
            (amount, utcnow(), email, amount),
        )
        row = conn.execute("SELECT tokens FROM users WHERE email = ?", (email,)).fetchone()
        balance = row["tokens"] if row else 0
        if cur.rowcount == 0:
            return False, balance
        conn.execute(
            """INSERT INTO token_logs (user_email, delta, reason, balance, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (email, -amount, reason, balance, utcnow()),
        )
    return True, balance


def set_tokens(email: str, amount: int, reason: str) -> int:
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET tokens = ?, updated_at = ?, last_reset = ? WHERE email = ?",
            (amount, utcnow(), utcnow(), email),
        )
        conn.execute(
            """INSERT INTO token_logs (user_email, delta, reason, balance, created_at)
               VALUES (?, 0, ?, ?, ?)""",
            (email, reason, amount, utcnow()),
        )
    return amount


def token_history(email: str, limit: int = 100) -> list[dict]:
    rows = connection().execute(
        """SELECT delta, reason, balance, created_at FROM token_logs
           WHERE user_email = ? ORDER BY id DESC LIMIT ?""",
        (email, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def count_recent_grants(email: str, since_iso: str, needle: str) -> int:
    row = connection().execute(
        """SELECT COUNT(*) AS n FROM token_logs
           WHERE user_email = ? AND created_at >= ? AND reason LIKE ?""",
        (email, since_iso, f"%{needle}%"),
    ).fetchone()
    return row["n"]


# ─────────────────────────────────────────────────────────────────────
# DATASETS
# ─────────────────────────────────────────────────────────────────────
def insert_dataset(
    dataset_id: str, owner: str, name: str, description: str,
    rows: Sequence[dict], public: bool, tags: Sequence[str],
    storage_backend: str = "local", storage_repo: str | None = None,
    storage_path: str | None = None,
) -> None:
    now = utcnow()
    with transaction() as conn:
        conn.execute(
            """INSERT INTO datasets (id, owner, name, description, rows_json, row_count,
                                     public, tags_json, storage_backend, storage_repo,
                                     storage_path, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (dataset_id, owner, name, description, json.dumps(list(rows)), len(rows),
             int(public), json.dumps(list(tags)), storage_backend, storage_repo,
             storage_path, now, now),
        )


def get_dataset(dataset_id: str, *, with_rows: bool = True) -> dict | None:
    row = connection().execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    return _dataset_row(row, with_rows=with_rows)


def user_datasets(email: str, *, with_rows: bool = True) -> list[dict]:
    rows = connection().execute(
        "SELECT * FROM datasets WHERE owner = ? ORDER BY created_at DESC", (email,)
    ).fetchall()
    return [_dataset_row(r, with_rows=with_rows) for r in rows]


def public_datasets(*, with_rows: bool = True, limit: int = 200) -> list[dict]:
    rows = connection().execute(
        "SELECT * FROM datasets WHERE public = 1 ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_dataset_row(r, with_rows=with_rows) for r in rows]


def all_datasets(*, with_rows: bool = False) -> list[dict]:
    rows = connection().execute("SELECT * FROM datasets ORDER BY created_at DESC").fetchall()
    return [_dataset_row(r, with_rows=with_rows) for r in rows]


def count_user_datasets(email: str) -> int:
    return connection().execute(
        "SELECT COUNT(*) FROM datasets WHERE owner = ?", (email,)
    ).fetchone()[0]


def set_dataset_public(dataset_id: str, public: bool) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE datasets SET public = ?, updated_at = ? WHERE id = ?",
            (int(public), utcnow(), dataset_id),
        )


def increment_dataset_downloads(dataset_id: str) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE datasets SET downloads = downloads + 1 WHERE id = ?", (dataset_id,)
        )


def delete_dataset(dataset_id: str) -> dict | None:
    """Delete a dataset and return its row so callers can clean up remote storage."""
    dataset = get_dataset(dataset_id, with_rows=False)
    if dataset is None:
        return None
    with transaction() as conn:
        conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
    return dataset


# ─────────────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────────────
def insert_model(
    model_id: str, owner: str, name: str, description: str, base_model: str,
    hf_repo: str, public: bool, tags: Sequence[str], status: str = "ready",
) -> None:
    now = utcnow()
    with transaction() as conn:
        conn.execute(
            """INSERT INTO models (id, owner, name, description, base_model, hf_repo,
                                   public, tags_json, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (model_id, owner, name, description, base_model, hf_repo, int(public),
             json.dumps(list(tags)), status, now, now),
        )


def get_model(model_id: str) -> dict | None:
    row = connection().execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
    return _model_row(row)


def user_models(email: str) -> list[dict]:
    rows = connection().execute(
        "SELECT * FROM models WHERE owner = ? ORDER BY created_at DESC", (email,)
    ).fetchall()
    return [_model_row(r) for r in rows]


def public_models(limit: int = 200) -> list[dict]:
    rows = connection().execute(
        "SELECT * FROM models WHERE public = 1 ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_model_row(r) for r in rows]


def all_models() -> list[dict]:
    rows = connection().execute("SELECT * FROM models ORDER BY created_at DESC").fetchall()
    return [_model_row(r) for r in rows]


def count_user_models(email: str) -> int:
    return connection().execute(
        "SELECT COUNT(*) FROM models WHERE owner = ?", (email,)
    ).fetchone()[0]


def set_model_public(model_id: str, public: bool) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE models SET public = ?, updated_at = ? WHERE id = ?",
            (int(public), utcnow(), model_id),
        )


def delete_model(model_id: str) -> bool:
    with transaction() as conn:
        cur = conn.execute("DELETE FROM models WHERE id = ?", (model_id,))
    return cur.rowcount > 0


# ─────────────────────────────────────────────────────────────────────
# API KEYS (third-party credentials the user stores with us)
# ─────────────────────────────────────────────────────────────────────
def insert_api_key(email: str, label: str, key_value: str) -> bool:
    try:
        with transaction() as conn:
            conn.execute(
                """INSERT INTO api_keys (user_email, label, key_value, created_at)
                   VALUES (?, ?, ?, ?)""",
                (email, label, key_value, utcnow()),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def user_api_keys(email: str) -> list[dict]:
    rows = connection().execute(
        """SELECT label, key_value, uses, last_used, created_at FROM api_keys
           WHERE user_email = ? ORDER BY created_at DESC""",
        (email,),
    ).fetchall()
    return [dict(r) for r in rows]


def count_user_api_keys(email: str) -> int:
    return connection().execute(
        "SELECT COUNT(*) FROM api_keys WHERE user_email = ?", (email,)
    ).fetchone()[0]


def delete_api_key(email: str, label: str) -> bool:
    with transaction() as conn:
        cur = conn.execute(
            "DELETE FROM api_keys WHERE user_email = ? AND label = ?", (email, label)
        )
    return cur.rowcount > 0


# ─────────────────────────────────────────────────────────────────────
# SUPPORT TICKETS
# ─────────────────────────────────────────────────────────────────────
def insert_ticket(ticket_id: str, email: str, subject: str, message: str) -> bool:
    try:
        with transaction() as conn:
            conn.execute(
                """INSERT INTO support_tickets (id, user_email, subject, message, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (ticket_id, email, subject, message, utcnow()),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def list_tickets(status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM support_tickets"
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY created_at DESC"
    return [dict(r) for r in connection().execute(sql, params).fetchall()]


def user_tickets(email: str) -> list[dict]:
    rows = connection().execute(
        "SELECT * FROM support_tickets WHERE user_email = ? ORDER BY created_at DESC",
        (email,),
    ).fetchall()
    return [dict(r) for r in rows]


def close_ticket(ticket_id: str, reply: str) -> bool:
    with transaction() as conn:
        cur = conn.execute(
            "UPDATE support_tickets SET status = 'closed', admin_reply = ? WHERE id = ?",
            (reply, ticket_id),
        )
    return cur.rowcount > 0


def count_open_tickets() -> int:
    return connection().execute(
        "SELECT COUNT(*) FROM support_tickets WHERE status = 'open'"
    ).fetchone()[0]


# ─────────────────────────────────────────────────────────────────────
# RATE LIMITING
# ─────────────────────────────────────────────────────────────────────
def rate_limit_hit(subject: str, action: str, max_per_min: int, window: int = 60) -> bool:
    """Record an attempt. Returns False when the caller is over the limit.

    Counting and inserting happen in one transaction so a burst of parallel
    requests cannot all read the same pre-insert count.
    """
    now = time.time()
    cutoff = now - window
    with transaction() as conn:
        conn.execute("DELETE FROM rate_limits WHERE ts < ?", (now - max(window, 3600),))
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM rate_limits WHERE subject = ? AND action = ? AND ts >= ?",
            (subject, action, cutoff),
        ).fetchone()
        if row["n"] >= max_per_min:
            return False
        conn.execute(
            "INSERT INTO rate_limits (subject, action, ts) VALUES (?, ?, ?)",
            (subject, action, now),
        )
    return True


def clear_rate_limits(subject: str | None = None) -> None:
    with transaction() as conn:
        if subject:
            conn.execute("DELETE FROM rate_limits WHERE subject = ?", (subject,))
        else:
            conn.execute("DELETE FROM rate_limits")


# ─────────────────────────────────────────────────────────────────────
# BILLING
# ─────────────────────────────────────────────────────────────────────
def log_billing_event(email: str, event_type: str, details: dict | None = None) -> None:
    with transaction() as conn:
        conn.execute(
            """INSERT INTO billing_events (user_email, event_type, details, created_at)
               VALUES (?, ?, ?, ?)""",
            (email, event_type, json.dumps(details or {}, default=str), utcnow()),
        )


def billing_history(email: str, limit: int = 100) -> list[dict]:
    rows = connection().execute(
        """SELECT event_type, details, created_at FROM billing_events
           WHERE user_email = ? ORDER BY id DESC LIMIT ?""",
        (email, limit),
    ).fetchall()
    return [{**dict(r), "details": _loads(r["details"], {})} for r in rows]


def mark_webhook_processed(event_id: str, provider: str) -> bool:
    """Claim a webhook event id. Returns False when it was already handled."""
    if not event_id:
        return True
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO processed_webhooks (event_id, provider, created_at) VALUES (?, ?, ?)",
                (event_id, provider, utcnow()),
            )
        return True
    except sqlite3.IntegrityError:
        return False


# ─────────────────────────────────────────────────────────────────────
# LEGACY MIGRATION
# ─────────────────────────────────────────────────────────────────────
def migrate_legacy_json(path: Path | None = None) -> int:
    """Import a pre-SQLite ``db.json`` once. Returns the number of users imported."""
    source = Path(path or LEGACY_DB_JSON)
    if not source.exists():
        return 0

    # Claim the file with an atomic rename *before* reading it. Streamlit runs
    # every session in its own thread and each one calls bootstrap(); checking
    # exists() first and renaming last let them all pass the check, all import,
    # and every loser crash on the final rename with FileNotFoundError — which
    # took the whole app down at import time.
    claim = source.with_name(source.name + ".importing")
    try:
        source.rename(claim)
    except OSError:
        return 0  # another worker claimed it first, or it disappeared

    try:
        legacy = json.loads(claim.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0

    imported = 0
    for email, user in (legacy.get("users") or {}).items():
        email = str(email).strip().lower()
        if not email or get_user(email):
            continue
        created = str(user.get("created") or utcnow())
        try:
            with transaction() as conn:
                conn.execute(
                    """INSERT INTO users (email, name, pw_hash, plan, tokens, flagged,
                                          flag_reason, platform_api_key, traakteer_id,
                                          created_at, updated_at, last_reset)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (email, user.get("name", ""), user.get("pw_hash", ""),
                     user.get("plan", "starter"), int(user.get("tokens", 0)),
                     int(bool(user.get("flagged"))), user.get("flag_reason", "") or "",
                     user.get("platform_api_key"), user.get("traakteer_id", "") or "",
                     created, created, str(user.get("last_reset") or created)),
                )
                for entry in user.get("token_log") or []:
                    conn.execute(
                        """INSERT INTO token_logs (user_email, delta, reason, balance, created_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (email, int(entry.get("delta", 0)), str(entry.get("reason", "")),
                         int(entry.get("balance", 0)), str(entry.get("ts") or created)),
                    )
                for label, info in (user.get("api_keys") or {}).items():
                    conn.execute(
                        """INSERT OR IGNORE INTO api_keys
                           (user_email, label, key_value, uses, last_used, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (email, str(label), str(info.get("key", "")),
                         int(info.get("uses", 0)), info.get("last_used"),
                         str(info.get("created") or created)),
                    )
        except sqlite3.IntegrityError:
            continue
        imported += 1

    for did, ds in (legacy.get("datasets") or {}).items():
        owner = str(ds.get("owner", "")).strip().lower()
        if not owner or get_dataset(did, with_rows=False) or not get_user(owner):
            continue
        try:
            insert_dataset(
                did, owner, ds.get("name", "Untitled"), ds.get("description", ""),
                ds.get("rows") or [], bool(ds.get("public")), ds.get("tags") or [],
                ds.get("storage_backend", "local"), ds.get("storage_repo"),
                ds.get("storage_path"),
            )
        except sqlite3.IntegrityError:
            continue

    for mid, md in (legacy.get("models") or {}).items():
        owner = str(md.get("owner", "")).strip().lower()
        if not owner or get_model(mid) or not get_user(owner):
            continue
        try:
            insert_model(
                mid, owner, md.get("name", "Untitled"), md.get("description", ""),
                md.get("base_model", ""), md.get("hf_repo", ""), bool(md.get("public")),
                md.get("tags") or [], md.get("status", "ready"),
            )
        except sqlite3.IntegrityError:
            continue

    for ticket in legacy.get("support_tickets") or []:
        owner = str(ticket.get("user", "")).strip().lower()
        if owner and get_user(owner):
            insert_ticket(str(ticket.get("id", "")), owner,
                          ticket.get("subject", ""), ticket.get("message", ""))

    try:
        claim.replace(source.with_name(source.name + ".imported"))
    except OSError:
        pass  # the rows are already in SQLite; the marker is a nicety
    return imported
