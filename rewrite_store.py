import re

with open("store.py", "r") as f:
    code = f.read()

# Replace sqlite3 with psycopg2
code = code.replace("import sqlite3", "import psycopg2\nimport psycopg2.extras")

# Remove SQLite connection handling
connect_replacement = """
def _connect():
    import config
    dsn = config.DATABASE_URL
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set for Supabase Postgres.")
    conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.DictCursor)
    conn.autocommit = True
    return conn

class PGWrapper:
    def __init__(self, conn):
        self.conn = conn
    
    def execute(self, sql, params=()):
        # Convert SQLite ? placeholders to Postgres %s
        sql = sql.replace("?", "%s")
        # Handle SQLite specific SQL
        sql = sql.replace("BEGIN IMMEDIATE", "BEGIN")
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur
        
    def executescript(self, sql):
        cur = self.conn.cursor()
        cur.execute(sql)
        return cur
        
    def close(self):
        self.conn.close()

def connection():
    ensure_db()
    conn = getattr(_local, "conn", None)
    if conn is None:
        raw_conn = _connect()
        conn = _local.conn = PGWrapper(raw_conn)
    return conn
"""
code = re.sub(r"def _connect\(\).*?return conn\n", connect_replacement, code, flags=re.DOTALL)

# Remove the PRAGMA user_version logic from ensure_db
ensure_db_replacement = """
def ensure_db() -> None:
    global _initialised
    if _initialised:
        return
    with _init_lock:
        if _initialised:
            return
        raw_conn = _connect()
        conn = PGWrapper(raw_conn)
        try:
            conn.executescript(_SCHEMA)
        finally:
            conn.close()
        _initialised = True
"""
code = re.sub(r"def ensure_db\(\) -> None:.*?_initialised = True\n", ensure_db_replacement, code, flags=re.DOTALL)

# Fix Schema
schema = re.search(r"_SCHEMA = \"\"\"(.*?)\"\"\"", code, flags=re.DOTALL).group(1)
schema = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
schema = schema.replace("INSERT OR IGNORE", "INSERT ON CONFLICT DO NOTHING") # For api_keys in legacy migration
code = re.sub(r"_SCHEMA = \"\"\"(.*?)\"\"\"", f'_SCHEMA = """{schema}"""', code, flags=re.DOTALL)

# Fix legacy migration insert or ignore
code = code.replace("INSERT OR IGNORE INTO api_keys", "INSERT INTO api_keys")
code = code.replace("VALUES (?, ?, ?, ?, ?, ?)", "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (user_email, label) DO NOTHING")

# Fix row parsing: psycopg2 DictRow doesn't have .keys() like sqlite3.Row, it acts like a dict
code = code.replace("sqlite3.Row", "psycopg2.extras.DictRow")
code = code.replace("sqlite3.IntegrityError", "psycopg2.IntegrityError")

with open("store.py", "w") as f:
    f.write(code)

