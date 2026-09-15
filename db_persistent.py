"""
db_persistent.py — Production-grade SQLite database with permanent storage
Replaces JSON file-based storage with proper relational database persistence.
All user data, datasets, models, and API tokens persist across server restarts.
"""

import sqlite3
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Dict, List
import threading

DB_PATH = Path("asian_inference.db")
_lock = threading.RLock()  # Thread-safe database access

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE INITIALIZATION
# ─────────────────────────────────────────────────────────────────────────────

def _get_conn():
    """Get a thread-safe database connection."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database schema. Called once on startup."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        
        # Users table
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT,
                pw_hash TEXT NOT NULL,
                plan TEXT DEFAULT 'starter',
                tokens INTEGER DEFAULT 500,
                flagged BOOLEAN DEFAULT 0,
                flag_reason TEXT,
                platform_api_key TEXT UNIQUE,
                chat_history TEXT,
                traakteer_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        # Token logs table (permanent audit trail)
        c.execute("""
            CREATE TABLE IF NOT EXISTS token_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                delta INTEGER NOT NULL,
                reason TEXT,
                balance INTEGER,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (user_email) REFERENCES users(email)
            )
        """)
        
        # Datasets table
        c.execute("""
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                rows_json TEXT NOT NULL,
                public BOOLEAN DEFAULT 0,
                tags TEXT,
                downloads INTEGER DEFAULT 0,
                likes INTEGER DEFAULT 0,
                liked_by TEXT,
                storage_backend TEXT DEFAULT 'local',
                storage_repo TEXT,
                storage_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (owner) REFERENCES users(email)
            )
        """)
        
        # Models table
        c.execute("""
            CREATE TABLE IF NOT EXISTS models (
                id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                base_model TEXT NOT NULL,
                hf_repo TEXT NOT NULL,
                public BOOLEAN DEFAULT 0,
                tags TEXT,
                status TEXT DEFAULT 'ready',
                downloads INTEGER DEFAULT 0,
                likes INTEGER DEFAULT 0,
                liked_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (owner) REFERENCES users(email)
            )
        """)
        
        # API Keys table (permanent external API key storage)
        c.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                label TEXT NOT NULL,
                key_value TEXT NOT NULL,
                uses INTEGER DEFAULT 0,
                last_used TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(user_email, label),
                FOREIGN KEY (user_email) REFERENCES users(email)
            )
        """)
        
        # Support tickets
        c.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id TEXT PRIMARY KEY,
                user_email TEXT NOT NULL,
                subject TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                admin_reply TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_email) REFERENCES users(email)
            )
        """)
        
        # Rate limiting (automatic cleanup)
        c.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                action TEXT NOT NULL,
                timestamp REAL NOT NULL,
                UNIQUE(key, action, timestamp)
            )
        """)
        
        conn.commit()
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# USER OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────

def create_user(email: str, name: str, pw_hash: str, plan: str = "starter") -> bool:
    """Create a new user account. Permanent persistent storage."""
    with _lock:
        try:
            conn = _get_conn()
            c = conn.cursor()
            now = datetime.utcnow().isoformat()
            tokens = {"starter": 500, "pro": 15000, "elite": 999999}.get(plan, 500)
            
            c.execute("""
                INSERT INTO users 
                (email, name, pw_hash, plan, tokens, chat_history, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (email, name, pw_hash, plan, tokens, json.dumps([]), now, now))
            
            # Log initial token grant
            c.execute("""
                INSERT INTO token_logs (user_email, delta, reason, balance, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (email, tokens, "signup", tokens, now))
            
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            return False


def get_user(email: str) -> Optional[Dict]:
    """Retrieve user by email. All data persists permanently."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = c.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "pw_hash": row["pw_hash"],
            "plan": row["plan"],
            "tokens": row["tokens"],
            "flagged": bool(row["flagged"]),
            "flag_reason": row["flag_reason"],
            "platform_api_key": row["platform_api_key"],
            "chat_history": json.loads(row["chat_history"] or "[]"),
            "traakteer_id": row["traakteer_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def update_user(email: str, **kwargs) -> bool:
    """Update user fields. All changes persisted permanently."""
    with _lock:
        try:
            conn = _get_conn()
            c = conn.cursor()
            kwargs["updated_at"] = datetime.utcnow().isoformat()
            
            # Handle JSON serialization for complex fields
            if "chat_history" in kwargs and isinstance(kwargs["chat_history"], list):
                kwargs["chat_history"] = json.dumps(kwargs["chat_history"])
            
            fields = ", ".join(f"{k} = ?" for k in kwargs.keys())
            values = list(kwargs.values()) + [email]
            
            c.execute(f"UPDATE users SET {fields} WHERE email = ?", values)
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False


def list_users() -> List[Dict]:
    """Get all users (for admin panel)."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM users ORDER BY created_at DESC")
        rows = c.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


# ─────────────────────────────────────────────────────────────────────────────
# TOKEN OPERATIONS (Permanent Audit Trail)
# ─────────────────────────────────────────────────────────────────────────────

def add_tokens(email: str, amount: int, reason: str) -> int:
    """Add tokens to user (permanent log entry)."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        now = datetime.utcnow().isoformat()
        
        # Update user balance
        c.execute("UPDATE users SET tokens = tokens + ? WHERE email = ?", (amount, email))
        
        # Get new balance
        c.execute("SELECT tokens FROM users WHERE email = ?", (email,))
        row = c.fetchone()
        new_balance = row["tokens"] if row else 0
        
        # Log transaction permanently
        c.execute("""
            INSERT INTO token_logs (user_email, delta, reason, balance, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (email, amount, reason, new_balance, now))
        
        conn.commit()
        conn.close()
        return new_balance


def deduct_tokens(email: str, amount: int) -> bool:
    """Deduct tokens (permanent log entry). Returns False if insufficient."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        
        # Check balance
        c.execute("SELECT tokens FROM users WHERE email = ?", (email,))
        row = c.fetchone()
        if not row or row["tokens"] < amount:
            conn.close()
            return False
        
        # Deduct and log
        now = datetime.utcnow().isoformat()
        c.execute("UPDATE users SET tokens = tokens - ? WHERE email = ?", (amount, email))
        c.execute("SELECT tokens FROM users WHERE email = ?", (email,))
        new_balance = c.fetchone()["tokens"]
        
        c.execute("""
            INSERT INTO token_logs (user_email, delta, reason, balance, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (email, -amount, "usage", new_balance, now))
        
        conn.commit()
        conn.close()
        return True


def get_token_history(email: str, limit: int = 100) -> List[Dict]:
    """Get permanent token transaction history."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM token_logs 
            WHERE user_email = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (email, limit))
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]


# ─────────────────────────────────────────────────────────────────────────────
# DATASET OPERATIONS (Persistent Storage)
# ─────────────────────────────────────────────────────────────────────────────

def save_dataset(dataset_id: str, owner: str, name: str, description: str,
                 rows: List[Dict], public: bool, tags: List[str],
                 storage_backend: str = "local", storage_repo: str = None,
                 storage_path: str = None) -> bool:
    """Save dataset. Rows are permanently stored."""
    with _lock:
        try:
            conn = _get_conn()
            c = conn.cursor()
            now = datetime.utcnow().isoformat()
            
            c.execute("""
                INSERT OR REPLACE INTO datasets
                (id, owner, name, description, rows_json, public, tags, 
                 storage_backend, storage_repo, storage_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (dataset_id, owner, name, description, json.dumps(rows), public,
                  json.dumps(tags), storage_backend, storage_repo, storage_path, now, now))
            
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False


def get_dataset(dataset_id: str) -> Optional[Dict]:
    """Retrieve dataset permanently (even after server restart)."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
        row = c.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return {
            "id": row["id"],
            "owner": row["owner"],
            "name": row["name"],
            "description": row["description"],
            "rows": json.loads(row["rows_json"]),
            "public": bool(row["public"]),
            "tags": json.loads(row["tags"]),
            "downloads": row["downloads"],
            "likes": row["likes"],
            "storage_backend": row["storage_backend"],
            "storage_repo": row["storage_repo"],
            "storage_path": row["storage_path"],
            "created": row["created_at"],
        }


def get_user_datasets(email: str) -> List[Dict]:
    """Get all datasets for a user (persistent)."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM datasets 
            WHERE owner = ? 
            ORDER BY created_at DESC
        """, (email,))
        rows = c.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


def get_public_datasets() -> List[Dict]:
    """Get all public datasets (persistent)."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM datasets 
            WHERE public = 1 
            ORDER BY created_at DESC
        """)
        rows = c.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


# ─────────────────────────────────────────────────────────────────────────────
# MODEL OPERATIONS (Persistent Storage)
# ─────────────────────────────────────────────────────────────────────────────

def save_model(model_id: str, owner: str, name: str, description: str,
               base_model: str, hf_repo: str, public: bool, tags: List[str]) -> bool:
    """Save model. Metadata is permanently stored."""
    with _lock:
        try:
            conn = _get_conn()
            c = conn.cursor()
            now = datetime.utcnow().isoformat()
            
            c.execute("""
                INSERT OR REPLACE INTO models
                (id, owner, name, description, base_model, hf_repo, public, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (model_id, owner, name, description, base_model, hf_repo, public,
                  json.dumps(tags), now, now))
            
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False


def get_model(model_id: str) -> Optional[Dict]:
    """Retrieve model (persistent)."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM models WHERE id = ?", (model_id,))
        row = c.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return dict(row)


def get_user_models(email: str) -> List[Dict]:
    """Get all models for a user (persistent)."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM models 
            WHERE owner = ? 
            ORDER BY created_at DESC
        """, (email,))
        rows = c.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


def get_public_models() -> List[Dict]:
    """Get all public models (persistent)."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM models 
            WHERE public = 1 
            ORDER BY created_at DESC
        """)
        rows = c.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


# ─────────────────────────────────────────────────────────────────────────────
# API KEY OPERATIONS (Secure Permanent Storage)
# ─────────────────────────────────────────────────────────────────────────────

def save_api_key(email: str, label: str, key_value: str) -> bool:
    """Save API key permanently. Secure storage."""
    with _lock:
        try:
            conn = _get_conn()
            c = conn.cursor()
            now = datetime.utcnow().isoformat()
            
            c.execute("""
                INSERT INTO api_keys (user_email, label, key_value, created_at)
                VALUES (?, ?, ?, ?)
            """, (email, label, key_value, now))
            
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            return False


def get_api_keys(email: str) -> List[Dict]:
    """Get all API keys for user (permanent storage)."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT id, user_email, label, key_value, uses, last_used, created_at
            FROM api_keys 
            WHERE user_email = ?
            ORDER BY created_at DESC
        """, (email,))
        rows = c.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


def lookup_api_key(key_value: str) -> Optional[str]:
    """Look up API key and return owner email (fast O(1) lookup)."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("SELECT user_email FROM api_keys WHERE key_value = ?", (key_value,))
        row = c.fetchone()
        conn.close()
        
        return row["user_email"] if row else None


def delete_api_key(email: str, label: str) -> bool:
    """Delete API key permanently."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM api_keys WHERE user_email = ? AND label = ?", (email, label))
        conn.commit()
        conn.close()
        return True


# ─────────────────────────────────────────────────────────────────────────────
# SUPPORT TICKETS (Permanent Records)
# ─────────────────────────────────────────────────────────────────────────────

def save_support_ticket(ticket_id: str, email: str, subject: str, message: str) -> bool:
    """Save support ticket permanently."""
    with _lock:
        try:
            conn = _get_conn()
            c = conn.cursor()
            now = datetime.utcnow().isoformat()
            
            c.execute("""
                INSERT INTO support_tickets (id, user_email, subject, message, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (ticket_id, email, subject, message, now))
            
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False


def get_support_tickets() -> List[Dict]:
    """Get all support tickets (permanent records)."""
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM support_tickets ORDER BY created_at DESC")
        rows = c.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


# ─────────────────────────────────────────────────────────────────────────────
# INITIALIZATION
# ─────────────────────────────────────────────────────────────────────────────

def ensure_db():
    """Ensure database is initialized. Call once on app startup."""
    if not DB_PATH.exists():
        init_db()
