import sqlite3
import json
import time
from webapp.config import DB_PATH

def _get_db():
    """Get a thread-safe SQLite connection."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db():
    """Create the tasks table on startup."""
    conn = _get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                goal TEXT DEFAULT '',
                created REAL NOT NULL,
                updated REAL DEFAULT NULL,
                result TEXT DEFAULT NULL,
                error TEXT DEFAULT NULL,
                traceback TEXT DEFAULT NULL,
                brochure_path TEXT DEFAULT NULL,
                progress TEXT DEFAULT '[]'
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _task_to_dict(row):
    """Convert a sqlite3.Row to a plain dict, parsing JSON result field."""
    if row is None:
        return None
    d = dict(row)
    if d.get("result") and isinstance(d["result"], str):
        try:
            d["result"] = json.loads(d["result"])
        except (json.JSONDecodeError, TypeError):
            d["result"] = {}
    if d.get("result") is None:
        d["result"] = {}
    return d


def _store_task(task_id, goal):
    """Insert a new task record."""
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO tasks (id, status, goal, created) VALUES (?, ?, ?, ?)",
            (task_id, "pending", goal, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def _update_task(task_id, **fields):
    """Update arbitrary fields on a task."""
    if not fields:
        return
    fields["updated"] = time.time()
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values())
    conn = _get_db()
    try:
        # Serialize result to JSON if present
        if "result" in fields and isinstance(fields["result"], dict):
            vals[list(fields.keys()).index("result")] = json.dumps(fields["result"], ensure_ascii=False)
        conn.execute(
            f"UPDATE tasks SET {sets} WHERE id = ?",
            vals + [task_id],
        )
        conn.commit()
    finally:
        conn.close()


def _get_task(task_id):
    """Retrieve a single task by ID."""
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_to_dict(row)
    finally:
        conn.close()

# Aliases without leading underscore as requested in imports
store_task = _store_task
update_task = _update_task
get_task = _get_task
