"""
core.py — shared DB, auth, security, plan limits
"""
import hashlib, hmac as _hmac, json, os, re, time, uuid
from datetime import datetime, timedelta
from pathlib import Path
import streamlit as st

# ── Secrets ────────────────────────────────────────────────────────
def _secret(key: str, fallback: str = "") -> str:
    try:    return st.secrets[key]
    except: return os.getenv(key, fallback)

ADMIN_EMAIL      = "emir.erningpraja@gmail.com"
HF_TOKEN         = _secret("HF_TOKEN")
TRAAKTEER_SECRET = _secret("TRAAKTEER_SECRET")
SECRET_KEY       = _secret("SECRET_KEY", "gemby-default-secret-change-me")

# ── Plan definitions ────────────────────────────────────────────────
PLANS = {
    "starter": {
        "name": "Starter",  "badge": "🆓",  "price": 0,
        "tokens": 500,      "monthly_tokens": 500,
        "max_rows": 50,     "max_models": 2,   "max_datasets": 2,
        "share": False,     "api_keys": 1,
        "color": "#64748b", "traakteer_id": "",
    },
    "pro": {
        "name": "Pro",      "badge": "⚡",  "price": 9.99,
        "tokens": 15_000,   "monthly_tokens": 15_000,
        "max_rows": 2000,   "max_models": 6,   "max_datasets": 6,
        "share": True,      "api_keys": 5,
        "color": "#7c3aed", "traakteer_id": "plan_pro_monthly",
    },
    "elite": {
        "name": "Elite",    "badge": "👑",  "price": 29.99,
        "tokens": 999_999,  "monthly_tokens": 999_999,
        "max_rows": 50_000, "max_models": 999, "max_datasets": 999,
        "share": True,      "api_keys": 999,
        "color": "#b45309", "traakteer_id": "plan_elite_monthly",
    },
}

# ── File paths ──────────────────────────────────────────────────────
DB_FILE    = Path("db.json")
RATE_FILE  = Path("rate_limits.json")

# ── DB ──────────────────────────────────────────────────────────────
def load_db() -> dict:
    if DB_FILE.exists():
        try: return json.loads(DB_FILE.read_text())
        except: pass
    return {"users": {}, "datasets": {}, "models": {}, "support_tickets": []}

def save_db(db: dict):
    DB_FILE.write_text(json.dumps(db, indent=2, default=str))

def load_rates() -> dict:
    if RATE_FILE.exists():
        try: return json.loads(RATE_FILE.read_text())
        except: pass
    return {}

def save_rates(r: dict):
    RATE_FILE.write_text(json.dumps(r, default=str))

# ── Security ────────────────────────────────────────────────────────
def hash_pw(pw: str) -> str:
    return hashlib.sha256((SECRET_KEY + pw).encode()).hexdigest()

def rate_limit(email: str, action: str, max_per_min: int = 5) -> bool:
    rates = load_rates()
    key   = f"{email}:{action}"
    now   = time.time()
    win   = [t for t in rates.get(key, []) if now - t < 60]
    if len(win) >= max_per_min:
        rates[key] = win; save_rates(rates); return False
    win.append(now); rates[key] = win; save_rates(rates); return True

def safe_add_tokens(user: dict, amount: int, reason: str) -> int:
    amount = max(0, min(int(amount), 999_999))
    user["tokens"] = max(0, user.get("tokens", 0) + amount)
    user.setdefault("token_log", []).append({
        "ts": datetime.utcnow().isoformat(), "delta": amount,
        "reason": reason, "balance": user["tokens"],
    })
    one_h = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    if sum(1 for e in user["token_log"]
           if e.get("ts","") > one_h and "manual" in e.get("reason","")) > 5:
        user["flagged"] = True
        user["flag_reason"] = "Suspicious token grants"
    return user["tokens"]

def deduct_tokens(user: dict, amount: int) -> bool:
    if user.get("tokens", 0) < amount: return False
    user["tokens"] -= amount
    user.setdefault("token_log", []).append({
        "ts": datetime.utcnow().isoformat(), "delta": -amount,
        "reason": "usage", "balance": user["tokens"],
    })
    return True

def verify_hmac(payload: bytes, sig: str) -> bool:
    exp = _hmac.new(TRAAKTEER_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return _hmac.compare_digest(exp, sig)

# ── Users ───────────────────────────────────────────────────────────
def register(email: str, pw: str, name: str) -> tuple[bool, str]:
    email = email.strip().lower()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return False, "Invalid email."
    if len(pw) < 8:
        return False, "Password must be 8+ characters."
    db = load_db()
    if email in db["users"]:
        return False, "Email already registered."
    plan = "elite" if email == ADMIN_EMAIL else "starter"
    db["users"][email] = {
        "email": email, "name": name, "pw_hash": hash_pw(pw),
        "plan": plan, "tokens": PLANS[plan]["tokens"],
        "created": datetime.utcnow().isoformat(),
        "flagged": False, "flag_reason": "",
        "token_log": [{"ts": datetime.utcnow().isoformat(),
                       "delta": PLANS[plan]["tokens"],
                       "reason": "signup", "balance": PLANS[plan]["tokens"]}],
        "datasets": [], "models": [],
        "api_keys": {},          # name → key string
        "traakteer_id": "",
        "last_reset": datetime.utcnow().isoformat(),
    }
    save_db(db)
    return True, "Account created!"

def login(email: str, pw: str) -> tuple[bool, str, dict | None]:
    if not rate_limit(email, "login", 10):
        return False, "Too many attempts. Wait a minute.", None
    email = email.strip().lower()
    db = load_db()
    u  = db["users"].get(email)
    if not u or u["pw_hash"] != hash_pw(pw):
        return False, "Wrong email or password.", None
    if u.get("flagged"):
        return False, "Account suspended. Contact support.", None
    return True, "OK", u

def get_user(email: str) -> dict | None:
    return load_db()["users"].get(email)

def save_user(u: dict):
    db = load_db()
    db["users"][u["email"]] = u
    save_db(db)

# ── API key management ───────────────────────────────────────────────
def create_api_key(user: dict, label: str) -> str | None:
    plan = PLANS[user["plan"]]
    if len(user.get("api_keys", {})) >= plan["api_keys"]:
        return None
    key = "asi-" + uuid.uuid4().hex
    user.setdefault("api_keys", {})[label] = {
        "key": key, "created": datetime.utcnow().isoformat(), "uses": 0
    }
    save_user(user)
    return key

def delete_api_key(user: dict, label: str):
    user.get("api_keys", {}).pop(label, None)
    save_user(user)

# ── Dataset helpers ─────────────────────────────────────────────────
def save_dataset(owner: str, name: str, desc: str,
                 rows: list, public: bool, tags: list) -> str:
    db  = load_db()
    did = str(uuid.uuid4())[:10]
    db["datasets"][did] = {
        "id": did, "name": name, "description": desc,
        "owner": owner, "rows": rows, "public": public,
        "tags": tags, "created": datetime.utcnow().isoformat(),
        "downloads": 0, "likes": 0, "liked_by": [],
    }
    db["users"][owner].setdefault("datasets", []).append(did)
    save_db(db)
    return did

def get_public_datasets() -> list:
    return sorted(
        [d for d in load_db()["datasets"].values() if d.get("public")],
        key=lambda d: d["created"], reverse=True)

def get_user_datasets(email: str) -> list:
    db  = load_db()
    ids = db["users"].get(email, {}).get("datasets", [])
    return [db["datasets"][i] for i in ids if i in db["datasets"]]

# ── Model helpers ────────────────────────────────────────────────────
def save_model(owner: str, name: str, desc: str, base_model: str,
               hf_repo: str, colab_url: str, public: bool, tags: list,
               api_keys_used: dict) -> str:
    db  = load_db()
    mid = str(uuid.uuid4())[:10]
    db["models"][mid] = {
        "id": mid, "name": name, "description": desc,
        "owner": owner, "base_model": base_model,
        "hf_repo": hf_repo, "colab_url": colab_url,
        "public": public, "tags": tags,
        "api_keys_used": api_keys_used,   # which external keys power this model
        "created": datetime.utcnow().isoformat(),
        "downloads": 0, "likes": 0, "liked_by": [],
        "status": "ready",                # ready / training / failed
        "inference_endpoint": hf_repo,    # used by inference calls
    }
    db["users"][owner].setdefault("models", []).append(mid)
    save_db(db)
    return mid

def get_public_models() -> list:
    return sorted(
        [m for m in load_db()["models"].values() if m.get("public")],
        key=lambda m: m["created"], reverse=True)

def get_user_models(email: str) -> list:
    db  = load_db()
    ids = db["users"].get(email, {}).get("models", [])
    return [db["models"][i] for i in ids if i in db["models"]]
