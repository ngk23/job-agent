"""
Database layer for Job Agent.
Supports SQLite (default, zero-config) and PostgreSQL (via DATABASE_URL env var).
Uses a driver-agnostic adapter pattern so all function signatures remain sync and identical.
"""

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import get_env

# ── Driver Selection ──────────────────────────────────────────────────────────

DATABASE_URL = get_env("DATABASE_URL", "").strip()
_use_postgres = bool(DATABASE_URL and DATABASE_URL.startswith("postgres"))

if _use_postgres:
    from urllib.parse import urlparse

    import psycopg2
    import psycopg2.extras
    import psycopg2.pool

    _pool = None
    _pool_lock = threading.Lock()

    def _get_pool():
        """Create or return a thread-safe psycopg2 connection pool."""
        global _pool
        if _pool is None:
            with _pool_lock:
                if _pool is None:
                    parsed = urlparse(DATABASE_URL)
                    _pool = psycopg2.pool.ThreadedConnectionPool(
                        minconn=2,
                        maxconn=20,
                        host=parsed.hostname or "localhost",
                        port=parsed.port or 5432,
                        dbname=parsed.path.lstrip("/") or "job_agent",
                        user=parsed.username or "postgres",
                        password=parsed.password or "",
                    )
        return _pool

    _local = threading.local()

    def get_db():
        """Get a thread-local PostgreSQL connection from the pool."""
        if not hasattr(_local, "conn") or _local.conn is None or _local.conn.closed:
            pool = _get_pool()
            _local.conn = pool.getconn()
            _local.conn.autocommit = False
        return _local.conn

    def _cursor(conn):
        """Get a RealDictCursor for PostgreSQL."""
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def close_db_connection():
        """Return the thread-local PostgreSQL connection to the pool.

        Call this from Flask's teardown_appcontext or FastAPI's shutdown
        event to prevent connection leaks. Thread-local connections are
        automatically cleaned up when threads exit, but calling this
        explicitly ensures prompt return to the pool.
        """
        if hasattr(_local, "conn") and _local.conn is not None:
            pool = _get_pool()
            try:
                if not _local.conn.closed:
                    _local.conn.rollback()  # abort any uncommitted work
                    pool.putconn(_local.conn)
            except Exception:
                try:
                    pool.putconn(_local.conn, close=True)
                except Exception:
                    pass
            _local.conn = None

    def _lastrowid(cursor, conn) -> int:
        """Get last inserted ID from PostgreSQL (requires RETURNING clause)."""
        row = cursor.fetchone()
        conn.commit()
        return row["id"] if row else 0

    def _init_schema():
        """Initialize PostgreSQL schema."""
        conn = get_db()
        cur = _cursor(conn)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                api_key TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                password_changed INTEGER DEFAULT 1,
                resend_api_key TEXT DEFAULT '',
                gmail_user TEXT DEFAULT '',
                gmail_app_password TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS applications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                timestamp TEXT,
                title TEXT,
                company TEXT,
                url TEXT,
                platform TEXT DEFAULT '',
                location TEXT DEFAULT '',
                ai_score INTEGER DEFAULT 0,
                matching_skills TEXT DEFAULT '[]',
                concerns TEXT DEFAULT '[]',
                cover_letter TEXT DEFAULT '',
                job_description TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_applications_user ON applications(user_id);
            CREATE INDEX IF NOT EXISTS idx_applications_score ON applications(ai_score);

            CREATE TABLE IF NOT EXISTS applied_jobs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, url)
            );
            CREATE INDEX IF NOT EXISTS idx_applied_user ON applied_jobs(user_id);

            CREATE TABLE IF NOT EXISTS saved_jobs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, application_id)
            );
            CREATE INDEX IF NOT EXISTS idx_saved_user ON saved_jobs(user_id);

            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_reset_token ON password_reset_tokens(token);

            CREATE TABLE IF NOT EXISTS login_logs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                email TEXT NOT NULL,
                ip_address TEXT DEFAULT '',
                user_agent TEXT DEFAULT '',
                success INTEGER DEFAULT 0,
                details TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_login_logs_user ON login_logs(user_id);
            CREATE INDEX IF NOT EXISTS idx_login_logs_time ON login_logs(created_at);

            CREATE TABLE IF NOT EXISTS activity_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                email TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT DEFAULT '',
                ip_address TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_log(user_id);
            CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_log(created_at);

            CREATE TABLE IF NOT EXISTS job_feedback (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                application_id INTEGER,
                job_title TEXT DEFAULT '',
                company TEXT DEFAULT '',
                rating INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_user ON job_feedback(user_id);
            CREATE INDEX IF NOT EXISTS idx_feedback_rating ON job_feedback(rating);
        """
        )
        conn.commit()

else:
    # ── SQLite Driver ─────────────────────────────────────────────────────────
    import sqlite3

    _hf_space = bool(get_env("SPACE_ID") or get_env("HF_SPACE", "").lower() == "true")
    DB_DIR = get_env("DATA_DIR", "/data" if _hf_space else ".")
    DB_PATH = str(Path(DB_DIR) / "job_agent.db")

    _local = threading.local()

    def get_db() -> sqlite3.Connection:
        """Get a thread-local SQLite connection."""
        if not hasattr(_local, "conn") or _local.conn is None:
            _local.conn = sqlite3.connect(DB_PATH)
            _local.conn.row_factory = sqlite3.Row
            _local.conn.execute("PRAGMA journal_mode=WAL")
            _local.conn.execute("PRAGMA foreign_keys=ON")
        return _local.conn

    def _cursor(conn):
        """Get a cursor for SQLite."""
        return conn.cursor()

    def close_db_connection():
        """No-op for SQLite (connections are per-thread, no pool to return)."""
        pass

    def _lastrowid(cursor, conn) -> int:
        """Get last inserted row ID from SQLite."""
        return cursor.lastrowid

    def _init_schema():
        """Initialize SQLite schema."""
        conn = get_db()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                api_key TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                timestamp TEXT,
                title TEXT,
                company TEXT,
                url TEXT,
                platform TEXT DEFAULT '',
                location TEXT DEFAULT '',
                ai_score INTEGER DEFAULT 0,
                matching_skills TEXT DEFAULT '[]',
                concerns TEXT DEFAULT '[]',
                cover_letter TEXT DEFAULT '',
                job_description TEXT DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_applications_user ON applications(user_id);
            CREATE INDEX IF NOT EXISTS idx_applications_score ON applications(ai_score);

            CREATE TABLE IF NOT EXISTS applied_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, url)
            );

            CREATE INDEX IF NOT EXISTS idx_applied_user ON applied_jobs(user_id);

            CREATE TABLE IF NOT EXISTS saved_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                application_id INTEGER NOT NULL,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
                UNIQUE(user_id, application_id)
            );

            CREATE INDEX IF NOT EXISTS idx_saved_user ON saved_jobs(user_id);
        """
        )
        conn.commit()

        # Migration: add columns for databases created before these features
        _migrate_add_column("users", "status", "TEXT DEFAULT 'active'")
        _migrate_add_column("users", "password_changed", "INTEGER DEFAULT 1")
        _migrate_add_column("users", "resend_api_key", "TEXT DEFAULT ''")
        _migrate_add_column("users", "gmail_user", "TEXT DEFAULT ''")
        _migrate_add_column("users", "gmail_app_password", "TEXT DEFAULT ''")

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_reset_token ON password_reset_tokens(token);

            CREATE TABLE IF NOT EXISTS login_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                email TEXT NOT NULL,
                ip_address TEXT DEFAULT '',
                user_agent TEXT DEFAULT '',
                success INTEGER DEFAULT 0,
                details TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_login_logs_user ON login_logs(user_id);
            CREATE INDEX IF NOT EXISTS idx_login_logs_time ON login_logs(created_at);

            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                email TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT DEFAULT '',
                ip_address TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_log(user_id);
            CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_log(created_at);

            CREATE TABLE IF NOT EXISTS job_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                application_id INTEGER,
                job_title TEXT DEFAULT '',
                company TEXT DEFAULT '',
                rating INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_user ON job_feedback(user_id);
            CREATE INDEX IF NOT EXISTS idx_feedback_rating ON job_feedback(rating);
        """
        )
        conn.commit()


# ── Shared: Schema Init ───────────────────────────────────────────────────────


def init_db():
    """Initialize database schema — creates tables if they don't exist."""
    _init_schema()


# ── SQLite Migration Helper (SQLite only) ─────────────────────────────────────


def _migrate_add_column(table: str, column: str, col_def: str):
    """Add a column to an SQLite table if it doesn't already exist."""
    if _use_postgres:
        return  # PostgreSQL includes all columns in CREATE TABLE IF NOT EXISTS
    conn = get_db()
    try:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        cols = {r[1] for r in cursor.fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
            conn.commit()
            logger = __import__("logging").getLogger(__name__)
            logger.info(f"Added column '{column}' to '{table}' table")
    except Exception as e:
        logger = __import__("logging").getLogger(__name__)
        logger.warning(f"Migration failed for {table}.{column}: {e}")


# ── Shared: Row parser ────────────────────────────────────────────────────────


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a database row to a plain dict regardless of driver."""
    if isinstance(row, dict):
        return row
    return dict(row)


# ── User Operations ───────────────────────────────────────────────────────────


def create_user(
    email: str,
    password_hash: str,
    name: str,
    role: str = "user",
    api_key: str = "",
    status: str = "pending",
) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cur = _cursor(conn)
    try:
        if _use_postgres:
            cur.execute(
                "INSERT INTO users (email, password_hash, name, role, api_key, status) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (email, password_hash, name, role, api_key, status),
            )
            user_id = _lastrowid(cur, conn)
            return get_user_by_id(user_id)
        else:
            cur.execute(
                "INSERT INTO users (email, password_hash, name, role, api_key, status) VALUES (?, ?, ?, ?, ?, ?)",
                (email, password_hash, name, role, api_key, status),
            )
            conn.commit()
            return get_user_by_id(cur.lastrowid)
    except Exception:
        conn.rollback() if _use_postgres else None
        return None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "SELECT * FROM users WHERE id = %s"
            if _use_postgres
            else "SELECT * FROM users WHERE id = ?"
        ),
        (user_id,),
    )
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "SELECT * FROM users WHERE LOWER(email) = LOWER(%s)"
            if _use_postgres
            else "SELECT * FROM users WHERE LOWER(email) = LOWER(?)"
        ),
        (email,),
    )
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_all_users() -> List[Dict[str, Any]]:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        "SELECT id, email, name, role, status, password_changed, created_at FROM users ORDER BY created_at DESC"
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def approve_user(user_id: int) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "UPDATE users SET status = 'active', role = 'user' WHERE id = %s AND status = 'pending'"
            if _use_postgres
            else "UPDATE users SET status = 'active', role = 'user' WHERE id = ? AND status = 'pending'"
        ),
        (user_id,),
    )
    conn.commit()
    return cur.rowcount > 0


def reject_user(user_id: int) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "DELETE FROM users WHERE id = %s AND status = 'pending'"
            if _use_postgres
            else "DELETE FROM users WHERE id = ? AND status = 'pending'"
        ),
        (user_id,),
    )
    conn.commit()
    return cur.rowcount > 0


def get_pending_users() -> List[Dict[str, Any]]:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        "SELECT id, email, name, created_at FROM users WHERE status = 'pending' ORDER BY created_at ASC"
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def update_user_api_key(user_id: int, api_key: str):
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "UPDATE users SET api_key = %s WHERE id = %s"
            if _use_postgres
            else "UPDATE users SET api_key = ? WHERE id = ?"
        ),
        (api_key, user_id),
    )
    conn.commit()


def update_user_resend_key(user_id: int, resend_key: str):
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "UPDATE users SET resend_api_key = %s WHERE id = %s"
            if _use_postgres
            else "UPDATE users SET resend_api_key = ? WHERE id = ?"
        ),
        (resend_key, user_id),
    )
    conn.commit()
    return True


def update_gmail_credentials(user_id: int, gmail_user: str, gmail_app_password: str):
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "UPDATE users SET gmail_user = %s, gmail_app_password = %s WHERE id = %s"
            if _use_postgres
            else "UPDATE users SET gmail_user = ?, gmail_app_password = ? WHERE id = ?"
        ),
        (gmail_user, gmail_app_password, user_id),
    )
    conn.commit()
    return True


def update_user_role(user_id: int, role: str) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "UPDATE users SET role = %s WHERE id = %s"
            if _use_postgres
            else "UPDATE users SET role = ? WHERE id = ?"
        ),
        (role, user_id),
    )
    conn.commit()
    return cur.rowcount > 0


def update_user_status(user_id: int, status: str) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "UPDATE users SET status = %s WHERE id = %s"
            if _use_postgres
            else "UPDATE users SET status = ? WHERE id = ?"
        ),
        (status, user_id),
    )
    conn.commit()
    return cur.rowcount > 0


def delete_user(user_id: int):
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "DELETE FROM users WHERE id = %s"
            if _use_postgres
            else "DELETE FROM users WHERE id = ?"
        ),
        (user_id,),
    )
    conn.commit()


def update_user_password(user_id: int, password_hash: str) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "UPDATE users SET password_hash = %s WHERE id = %s"
            if _use_postgres
            else "UPDATE users SET password_hash = ? WHERE id = ?"
        ),
        (password_hash, user_id),
    )
    conn.commit()
    return cur.rowcount > 0


def update_user_email(user_id: int, email: str) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    try:
        cur.execute(
            (
                "UPDATE users SET email = %s WHERE id = %s"
                if _use_postgres
                else "UPDATE users SET email = ? WHERE id = ?"
            ),
            (email, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        conn.rollback() if _use_postgres else None
        return False


def update_user_name(user_id: int, name: str) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "UPDATE users SET name = %s WHERE id = %s"
            if _use_postgres
            else "UPDATE users SET name = ? WHERE id = ?"
        ),
        (name, user_id),
    )
    conn.commit()
    return cur.rowcount > 0


# ── Password Changed Tracking ─────────────────────────────────────────────────


def mark_password_changed(user_id: int) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "UPDATE users SET password_changed = 1 WHERE id = %s"
            if _use_postgres
            else "UPDATE users SET password_changed = 1 WHERE id = ?"
        ),
        (user_id,),
    )
    conn.commit()
    return cur.rowcount > 0


def mark_password_needs_change(user_id: int) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "UPDATE users SET password_changed = 0 WHERE id = %s"
            if _use_postgres
            else "UPDATE users SET password_changed = 0 WHERE id = ?"
        ),
        (user_id,),
    )
    conn.commit()
    return cur.rowcount > 0


def needs_password_change(user_id: int) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "SELECT password_changed FROM users WHERE id = %s"
            if _use_postgres
            else "SELECT password_changed FROM users WHERE id = ?"
        ),
        (user_id,),
    )
    row = cur.fetchone()
    if row is None:
        return False
    d = _row_to_dict(row)
    return d.get("password_changed", 1) == 0


# ── Activity Tracking ─────────────────────────────────────────────────────────


def log_activity(
    user_id: int, email: str, action: str, details: str = "", ip_address: str = ""
):
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "INSERT INTO activity_log (user_id, email, action, details, ip_address) VALUES (%s, %s, %s, %s, %s)"
            if _use_postgres
            else "INSERT INTO activity_log (user_id, email, action, details, ip_address) VALUES (?, ?, ?, ?, ?)"
        ),
        (user_id, email, action, details, ip_address),
    )
    conn.commit()


def get_user_activity(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "SELECT * FROM activity_log WHERE user_id = %s ORDER BY created_at DESC LIMIT %s"
            if _use_postgres
            else "SELECT * FROM activity_log WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"
        ),
        (user_id, limit),
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_all_recent_activity(limit: int = 100) -> List[Dict[str, Any]]:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "SELECT a.*, u.name as user_name FROM activity_log a LEFT JOIN users u ON a.user_id = u.id ORDER BY a.created_at DESC LIMIT %s"
            if _use_postgres
            else "SELECT a.*, u.name as user_name FROM activity_log a LEFT JOIN users u ON a.user_id = u.id ORDER BY a.created_at DESC LIMIT ?"
        ),
        (limit,),
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_user_activity_stats(user_id: int) -> Dict[str, Any]:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "SELECT COUNT(*) as c FROM activity_log WHERE user_id = %s AND action = 'login'"
            if _use_postgres
            else "SELECT COUNT(*) as c FROM activity_log WHERE user_id = ? AND action = 'login'"
        ),
        (user_id,),
    )
    logins = _row_to_dict(cur.fetchone())["c"]
    cur.execute(
        (
            "SELECT COUNT(*) as c FROM activity_log WHERE user_id = %s AND action = 'save_job'"
            if _use_postgres
            else "SELECT COUNT(*) as c FROM activity_log WHERE user_id = ? AND action = 'save_job'"
        ),
        (user_id,),
    )
    saves = _row_to_dict(cur.fetchone())["c"]
    cur.execute(
        (
            "SELECT created_at FROM activity_log WHERE user_id = %s ORDER BY created_at DESC LIMIT 1"
            if _use_postgres
            else "SELECT created_at FROM activity_log WHERE user_id = ? ORDER BY created_at DESC LIMIT 1"
        ),
        (user_id,),
    )
    last_row = cur.fetchone()
    return {
        "total_logins": logins,
        "jobs_saved": saves,
        "last_active": _row_to_dict(last_row)["created_at"] if last_row else None,
    }


def get_active_users_count(minutes: int = 30) -> int:
    from datetime import datetime, timedelta

    conn = get_db()
    cur = _cursor(conn)
    cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
    cur.execute(
        (
            "SELECT COUNT(DISTINCT user_id) as c FROM activity_log WHERE created_at > %s"
            if _use_postgres
            else "SELECT COUNT(DISTINCT user_id) as c FROM activity_log WHERE created_at > ?"
        ),
        (cutoff,),
    )
    row = cur.fetchone()
    return _row_to_dict(row)["c"] if row else 0


# ── Job Feedback ───────────────────────────────────────────────────────────────


def save_feedback(
    user_id: int,
    rating: int,
    job_title: str = "",
    company: str = "",
    application_id: int = None,
):
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "INSERT INTO job_feedback (user_id, application_id, job_title, company, rating) VALUES (%s, %s, %s, %s, %s)"
            if _use_postgres
            else "INSERT INTO job_feedback (user_id, application_id, job_title, company, rating) VALUES (?, ?, ?, ?, ?)"
        ),
        (user_id, application_id, job_title, company, rating),
    )
    conn.commit()


def get_feedback_summary() -> Dict[str, Any]:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute("SELECT COUNT(*) as c FROM job_feedback")
    total = _row_to_dict(cur.fetchone())["c"]
    cur.execute("SELECT COUNT(*) as c FROM job_feedback WHERE rating = 1")
    up = _row_to_dict(cur.fetchone())["c"]
    cur.execute("SELECT COUNT(*) as c FROM job_feedback WHERE rating = -1")
    down = _row_to_dict(cur.fetchone())["c"]
    return {
        "total": total,
        "thumbs_up": up,
        "thumbs_down": down,
        "positivity_rate": round(up / total * 100, 1) if total > 0 else 0,
    }


# ── Password Reset Tokens ─────────────────────────────────────────────────────


def create_password_reset_token(user_id: int) -> Optional[str]:
    import secrets
    from datetime import datetime, timedelta

    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "DELETE FROM password_reset_tokens WHERE user_id = %s AND used = 0"
            if _use_postgres
            else "DELETE FROM password_reset_tokens WHERE user_id = ? AND used = 0"
        ),
        (user_id,),
    )
    conn.commit()
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    cur.execute(
        (
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)"
            if _use_postgres
            else "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)"
        ),
        (user_id, token, expires_at),
    )
    conn.commit()
    return token


def get_user_by_reset_token(token: str) -> Optional[Dict[str, Any]]:
    from datetime import datetime

    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "SELECT user_id FROM password_reset_tokens WHERE token = %s AND used = 0 AND expires_at > %s"
            if _use_postgres
            else "SELECT user_id FROM password_reset_tokens WHERE token = ? AND used = 0 AND expires_at > ?"
        ),
        (token, datetime.utcnow().isoformat()),
    )
    row = cur.fetchone()
    if not row:
        return None
    return get_user_by_id(_row_to_dict(row)["user_id"])


def use_password_reset_token(token: str) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "UPDATE password_reset_tokens SET used = 1 WHERE token = %s"
            if _use_postgres
            else "UPDATE password_reset_tokens SET used = 1 WHERE token = ?"
        ),
        (token,),
    )
    conn.commit()
    return cur.rowcount > 0


def cleanup_expired_tokens():
    from datetime import datetime

    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "DELETE FROM password_reset_tokens WHERE expires_at < %s"
            if _use_postgres
            else "DELETE FROM password_reset_tokens WHERE expires_at < ?"
        ),
        (datetime.utcnow().isoformat(),),
    )
    conn.commit()


# ── Login Logs ───────────────────────────────────────────────────────────────


def log_login_attempt(
    email: str,
    success: bool,
    user_id: Optional[int] = None,
    ip_address: str = "",
    user_agent: str = "",
    details: str = "",
):
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "INSERT INTO login_logs (user_id, email, ip_address, user_agent, success, details) VALUES (%s, %s, %s, %s, %s, %s)"
            if _use_postgres
            else "INSERT INTO login_logs (user_id, email, ip_address, user_agent, success, details) VALUES (?, ?, ?, ?, ?, ?)"
        ),
        (user_id, email, ip_address, user_agent, 1 if success else 0, details),
    )
    conn.commit()


def get_login_logs(limit: int = 200) -> List[Dict[str, Any]]:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "SELECT l.*, u.name as user_name, u.role as user_role FROM login_logs l LEFT JOIN users u ON l.user_id = u.id ORDER BY l.created_at DESC LIMIT %s"
            if _use_postgres
            else "SELECT l.*, u.name as user_name, u.role as user_role FROM login_logs l LEFT JOIN users u ON l.user_id = u.id ORDER BY l.created_at DESC LIMIT ?"
        ),
        (limit,),
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_login_logs_for_user(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "SELECT * FROM login_logs WHERE user_id = %s ORDER BY created_at DESC LIMIT %s"
            if _use_postgres
            else "SELECT * FROM login_logs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"
        ),
        (user_id, limit),
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


# ── Application Operations ────────────────────────────────────────────────────


def save_application(user_id: int, app_data: Dict[str, Any]) -> int:
    conn = get_db()
    cur = _cursor(conn)
    skills_json = json.dumps(app_data.get("matching_skills", []))
    concerns_json = json.dumps(app_data.get("concerns", []))
    if _use_postgres:
        cur.execute(
            """INSERT INTO applications 
               (user_id, timestamp, title, company, url, platform, location, 
                ai_score, matching_skills, concerns, cover_letter, job_description)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                user_id,
                app_data.get("timestamp", ""),
                app_data.get("title", "Unknown"),
                app_data.get("company", "Unknown"),
                app_data.get("url", ""),
                app_data.get("platform", ""),
                app_data.get("location", ""),
                app_data.get("ai_score", 0),
                skills_json,
                concerns_json,
                app_data.get("cover_letter", ""),
                app_data.get("job_description", ""),
            ),
        )
        return _lastrowid(cur, conn)
    else:
        cur.execute(
            """INSERT INTO applications 
               (user_id, timestamp, title, company, url, platform, location, 
                ai_score, matching_skills, concerns, cover_letter, job_description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                app_data.get("timestamp", ""),
                app_data.get("title", "Unknown"),
                app_data.get("company", "Unknown"),
                app_data.get("url", ""),
                app_data.get("platform", ""),
                app_data.get("location", ""),
                app_data.get("ai_score", 0),
                skills_json,
                concerns_json,
                app_data.get("cover_letter", ""),
                app_data.get("job_description", ""),
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_user_applications(
    user_id: int, min_score: int = 0, limit: int = 200
) -> List[Dict[str, Any]]:
    conn = get_db()
    cur = _cursor(conn)
    if _use_postgres:
        if min_score > 0:
            cur.execute(
                "SELECT * FROM applications WHERE user_id = %s AND ai_score >= %s ORDER BY timestamp DESC LIMIT %s",
                (user_id, min_score, limit),
            )
        else:
            cur.execute(
                "SELECT * FROM applications WHERE user_id = %s ORDER BY timestamp DESC LIMIT %s",
                (user_id, limit),
            )
    else:
        if min_score > 0:
            cur.execute(
                "SELECT * FROM applications WHERE user_id = ? AND ai_score >= ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, min_score, limit),
            )
        else:
            cur.execute(
                "SELECT * FROM applications WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit),
            )
    return [_parse_app_row(_row_to_dict(r)) for r in cur.fetchall()]


def get_all_applications(limit: int = 500) -> List[Dict[str, Any]]:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "SELECT a.*, u.email as user_email, u.name as user_name FROM applications a JOIN users u ON a.user_id = u.id ORDER BY a.timestamp DESC LIMIT %s"
            if _use_postgres
            else "SELECT a.*, u.email as user_email, u.name as user_name FROM applications a JOIN users u ON a.user_id = u.id ORDER BY a.timestamp DESC LIMIT ?"
        ),
        (limit,),
    )
    return [_parse_app_row(_row_to_dict(r)) for r in cur.fetchall()]


def delete_application(application_id: int) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "DELETE FROM applications WHERE id = %s"
            if _use_postgres
            else "DELETE FROM applications WHERE id = ?"
        ),
        (application_id,),
    )
    conn.commit()
    return cur.rowcount > 0


def clear_user_applications(user_id: int):
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "DELETE FROM applications WHERE user_id = %s"
            if _use_postgres
            else "DELETE FROM applications WHERE user_id = ?"
        ),
        (user_id,),
    )
    cur.execute(
        (
            "DELETE FROM saved_jobs WHERE user_id = %s"
            if _use_postgres
            else "DELETE FROM saved_jobs WHERE user_id = ?"
        ),
        (user_id,),
    )
    cur.execute(
        (
            "DELETE FROM applied_jobs WHERE user_id = %s"
            if _use_postgres
            else "DELETE FROM applied_jobs WHERE user_id = ?"
        ),
        (user_id,),
    )
    conn.commit()


def clear_all_applications():
    conn = get_db()
    cur = _cursor(conn)
    cur.execute("DELETE FROM applications")
    cur.execute("DELETE FROM saved_jobs")
    cur.execute("DELETE FROM applied_jobs")
    conn.commit()


def _parse_app_row(d: Dict[str, Any]) -> Dict[str, Any]:
    for field in ["matching_skills", "concerns"]:
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = []
    return d


# ── Applied Jobs Operations ──────────────────────────────────────────────────


def mark_applied(user_id: int, url: str) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    try:
        cur.execute(
            (
                "INSERT INTO applied_jobs (user_id, url) VALUES (%s, %s)"
                if _use_postgres
                else "INSERT INTO applied_jobs (user_id, url) VALUES (?, ?)"
            ),
            (user_id, url),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback() if _use_postgres else None
        return False


def get_applied_urls(user_id: int) -> set:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "SELECT url FROM applied_jobs WHERE user_id = %s"
            if _use_postgres
            else "SELECT url FROM applied_jobs WHERE user_id = ?"
        ),
        (user_id,),
    )
    return {_row_to_dict(r)["url"] for r in cur.fetchall()}


# ── Saved Jobs Operations ─────────────────────────────────────────────────────


def save_job_with_data(user_id: int, job_data: Dict[str, Any]) -> Optional[int]:
    app_id = save_application(user_id, job_data)
    if not app_id:
        return None
    conn = get_db()
    cur = _cursor(conn)
    try:
        cur.execute(
            (
                "INSERT INTO saved_jobs (user_id, application_id) VALUES (%s, %s)"
                if _use_postgres
                else "INSERT INTO saved_jobs (user_id, application_id) VALUES (?, ?)"
            ),
            (user_id, app_id),
        )
        conn.commit()
        return app_id
    except Exception:
        conn.rollback() if _use_postgres else None
        return app_id


def get_saved_applications(user_id: int) -> List[Dict[str, Any]]:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "SELECT a.*, s.saved_at FROM saved_jobs s JOIN applications a ON s.application_id = a.id WHERE s.user_id = %s ORDER BY s.saved_at DESC"
            if _use_postgres
            else "SELECT a.*, s.saved_at FROM saved_jobs s JOIN applications a ON s.application_id = a.id WHERE s.user_id = ? ORDER BY s.saved_at DESC"
        ),
        (user_id,),
    )
    return [_parse_app_row(_row_to_dict(r)) for r in cur.fetchall()]


def cleanup_old_saved_jobs(days: int = 7):
    from datetime import datetime, timedelta

    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "SELECT s.application_id FROM saved_jobs s WHERE s.saved_at < %s"
            if _use_postgres
            else "SELECT s.application_id FROM saved_jobs s WHERE s.saved_at < ?"
        ),
        (cutoff,),
    )
    app_ids = [_row_to_dict(r)["application_id"] for r in cur.fetchall()]
    if not app_ids:
        return 0
    # Delete saved_jobs entries first
    cur.execute(
        (
            "DELETE FROM saved_jobs WHERE saved_at < %s"
            if _use_postgres
            else "DELETE FROM saved_jobs WHERE saved_at < ?"
        ),
        (cutoff,),
    )
    # Batch-delete applications using IN clause
    placeholders = ",".join(["%s" if _use_postgres else "?"] * len(app_ids))
    cur.execute(
        f"DELETE FROM applications WHERE id IN ({placeholders})",
        tuple(app_ids),
    )
    conn.commit()
    logger = __import__("logging").getLogger(__name__)
    logger.info(f"Cleaned up {len(app_ids)} saved job(s) older than {days} days")
    return len(app_ids)


def save_job(user_id: int, application_id: int) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    try:
        cur.execute(
            (
                "INSERT INTO saved_jobs (user_id, application_id) VALUES (%s, %s)"
                if _use_postgres
                else "INSERT INTO saved_jobs (user_id, application_id) VALUES (?, ?)"
            ),
            (user_id, application_id),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback() if _use_postgres else None
        return False


def unsave_job(user_id: int, application_id: int) -> bool:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "DELETE FROM saved_jobs WHERE user_id = %s AND application_id = %s"
            if _use_postgres
            else "DELETE FROM saved_jobs WHERE user_id = ? AND application_id = ?"
        ),
        (user_id, application_id),
    )
    conn.commit()
    return cur.rowcount > 0


def get_saved_application_ids(user_id: int) -> set:
    conn = get_db()
    cur = _cursor(conn)
    cur.execute(
        (
            "SELECT application_id FROM saved_jobs WHERE user_id = %s"
            if _use_postgres
            else "SELECT application_id FROM saved_jobs WHERE user_id = ?"
        ),
        (user_id,),
    )
    return {_row_to_dict(r)["application_id"] for r in cur.fetchall()}


def get_stats(user_id: Optional[int] = None) -> Dict[str, Any]:
    conn = get_db()
    cur = _cursor(conn)
    if user_id:
        cur.execute(
            (
                "SELECT COUNT(*) as c FROM applications WHERE user_id = %s"
                if _use_postgres
                else "SELECT COUNT(*) as c FROM applications WHERE user_id = ?"
            ),
            (user_id,),
        )
        total = _row_to_dict(cur.fetchone())["c"]
        cur.execute(
            (
                "SELECT COALESCE(AVG(ai_score), 0) as a FROM applications WHERE user_id = %s AND ai_score > 0"
                if _use_postgres
                else "SELECT COALESCE(AVG(ai_score), 0) as a FROM applications WHERE user_id = ? AND ai_score > 0"
            ),
            (user_id,),
        )
        avg = _row_to_dict(cur.fetchone())["a"]
        cur.execute(
            (
                "SELECT COUNT(*) as c FROM applications WHERE user_id = %s AND ai_score >= 80"
                if _use_postgres
                else "SELECT COUNT(*) as c FROM applications WHERE user_id = ? AND ai_score >= 80"
            ),
            (user_id,),
        )
        high = _row_to_dict(cur.fetchone())["c"]
        cur.execute(
            (
                "SELECT COUNT(*) as c FROM saved_jobs WHERE user_id = %s"
                if _use_postgres
                else "SELECT COUNT(*) as c FROM saved_jobs WHERE user_id = ?"
            ),
            (user_id,),
        )
        saved = _row_to_dict(cur.fetchone())["c"]
    else:
        cur.execute("SELECT COUNT(*) as c FROM applications")
        total = _row_to_dict(cur.fetchone())["c"]
        cur.execute(
            "SELECT COALESCE(AVG(ai_score), 0) as a FROM applications WHERE ai_score > 0"
        )
        avg = _row_to_dict(cur.fetchone())["a"]
        cur.execute("SELECT COUNT(*) as c FROM applications WHERE ai_score >= 80")
        high = _row_to_dict(cur.fetchone())["c"]
        cur.execute("SELECT COUNT(*) as c FROM saved_jobs")
        saved = _row_to_dict(cur.fetchone())["c"]
    return {
        "total_jobs": total,
        "avg_score": round(avg, 1),
        "high_match": high,
        "saved_jobs": saved,
    }
