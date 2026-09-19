import re

with open("store.py", "r") as f:
    content = f.read()

# Replace imports
content = content.replace("import sqlite3", "import psycopg2\nimport psycopg2.extras\nimport sqlite3")

# Replace connection logic
connect_logic = """
def _connect():
    import config
    if config.DATABASE_URL:
        conn = psycopg2.connect(config.DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
        conn.autocommit = True
        return conn
    else:
        path = Path(config.DB_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn
"""
content = re.sub(r"def _connect\(\).*?return conn\n", connect_logic.strip() + "\n", content, flags=re.DOTALL)

# Replace execute to handle psycopg2 cursor vs sqlite3 connection
# Wait, a better approach is to wrap psycopg2 connection to mimic sqlite3.Connection.execute
