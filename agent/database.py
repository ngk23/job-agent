"""
SQLite database layer for Job Agent.
Stores users, job applications, applied jobs, and saved (bookmarked) jobs.
Each user's data is isolated by user_id.
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any

from .config import get_env

# Thread-local storage for DB connections
_local = threading.local()

# Database path — HF Spaces uses /data, local uses current dir
DB_DIR = get_env("DATA_DIR", ".")
DB_PATH = str(Path(DB_DIR) / "job_agent.db")


def get_db() -> sqlite3.Connection:
    """Get a thread-local database connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    """Initialize database schema — creates tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
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
    """)
    conn.commit()

    # Migration: add 'status' column if it doesn't exist (for databases created before this feature)
    _migrate_add_column("users", "status", "TEXT DEFAULT 'active'")

    # Create password_reset_tokens table
    conn.executescript("""
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
    """)
    conn.commit()


def _migrate_add_column(table: str, column: str, col_def: str):
    """Add a column to a table if it doesn't already exist (safe migration)."""
    conn = get_db()
    try:
        # Check if column exists
        cursor = conn.execute(f"PRAGMA table_info({table})")
        cols = {r[1] for r in cursor.fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
            conn.commit()
            logger = __import__('logging').getLogger(__name__)
            logger.info(f"Added column '{column}' to '{table}' table")
    except Exception as e:
        logger = __import__('logging').getLogger(__name__)
        logger.warning(f"Migration failed for {table}.{column}: {e}")


# ── User Operations ───────────────────────────────────────────────────────────

def create_user(email: str, password_hash: str, name: str, role: str = "user", api_key: str = "", status: str = "pending") -> Optional[Dict[str, Any]]:
    """Create a new user. Returns user dict or None if email exists.
    By default, new users are created with status='pending' (awaiting admin approval).
    Admin users are created with status='active'.
    """
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, name, role, api_key, status) VALUES (?, ?, ?, ?, ?, ?)",
            (email, password_hash, name, role, api_key, status),
        )
        conn.commit()
        return get_user_by_id(cursor.lastrowid)
    except sqlite3.IntegrityError:
        return None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Get user by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Get user by email."""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_all_users() -> List[Dict[str, Any]]:
    """Get all users (for admin)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, email, name, role, status, created_at FROM users ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def approve_user(user_id: int) -> bool:
    """Approve a pending user. Returns True if successful."""
    conn = get_db()
    cursor = conn.execute(
        "UPDATE users SET status = 'active' WHERE id = ? AND status = 'pending'",
        (user_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def reject_user(user_id: int) -> bool:
    """Reject a pending user and delete their account. Returns True if successful."""
    conn = get_db()
    # Delete user (cascades to applications, applied_jobs, saved_jobs)
    cursor = conn.execute(
        "DELETE FROM users WHERE id = ? AND status = 'pending'",
        (user_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_pending_users() -> List[Dict[str, Any]]:
    """Get all pending users (awaiting admin approval)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, email, name, created_at FROM users WHERE status = 'pending' ORDER BY created_at ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def update_user_api_key(user_id: int, api_key: str):
    """Update a user's Anthropic API key."""
    conn = get_db()
    conn.execute("UPDATE users SET api_key = ? WHERE id = ?", (api_key, user_id))
    conn.commit()


def update_user_role(user_id: int, role: str) -> bool:
    """Update a user's role (admin only). Returns True if successful."""
    conn = get_db()
    cursor = conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    conn.commit()
    return cursor.rowcount > 0


def update_user_status(user_id: int, status: str) -> bool:
    """Update a user's account status (active/pending/rejected). Returns True if successful."""
    conn = get_db()
    cursor = conn.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
    conn.commit()
    return cursor.rowcount > 0


def delete_user(user_id: int):
    """Delete a user and all their data (admin only)."""
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()


def update_user_password(user_id: int, password_hash: str) -> bool:
    """Update a user's password hash. Returns True if successful."""
    conn = get_db()
    cursor = conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (password_hash, user_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def update_user_email(user_id: int, email: str) -> bool:
    """Update a user's email address. Returns True if successful."""
    conn = get_db()
    try:
        cursor = conn.execute(
            "UPDATE users SET email = ? WHERE id = ?",
            (email, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        return False


def update_user_name(user_id: int, name: str) -> bool:
    """Update a user's name. Returns True if successful."""
    conn = get_db()
    cursor = conn.execute(
        "UPDATE users SET name = ? WHERE id = ?",
        (name, user_id),
    )
    conn.commit()
    return cursor.rowcount > 0


# ── Password Reset Tokens ─────────────────────────────────────────────────────

def create_password_reset_token(user_id: int) -> Optional[str]:
    """Create a password reset token for a user. Returns the token string."""
    import secrets
    from datetime import datetime, timedelta
    conn = get_db()
    # Delete any existing unused tokens for this user
    conn.execute(
        "DELETE FROM password_reset_tokens WHERE user_id = ? AND used = 0",
        (user_id,),
    )
    conn.commit()
    # Create new token (valid for 1 hour)
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    conn.execute(
        "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user_id, token, expires_at),
    )
    conn.commit()
    return token


def get_user_by_reset_token(token: str) -> Optional[Dict[str, Any]]:
    """Get user by a valid (unused, not expired) password reset token."""
    from datetime import datetime
    conn = get_db()
    row = conn.execute(
        """SELECT user_id FROM password_reset_tokens 
           WHERE token = ? AND used = 0 AND expires_at > ?""",
        (token, datetime.utcnow().isoformat()),
    ).fetchone()
    if not row:
        return None
    return get_user_by_id(row["user_id"])


def use_password_reset_token(token: str) -> bool:
    """Mark a reset token as used."""
    conn = get_db()
    cursor = conn.execute(
        "UPDATE password_reset_tokens SET used = 1 WHERE token = ?",
        (token,),
    )
    conn.commit()
    return cursor.rowcount > 0


def cleanup_expired_tokens():
    """Delete expired password reset tokens."""
    from datetime import datetime
    conn = get_db()
    conn.execute(
        "DELETE FROM password_reset_tokens WHERE expires_at < ?",
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
    """Record a login attempt in the login_logs table."""
    conn = get_db()
    conn.execute(
        """INSERT INTO login_logs (user_id, email, ip_address, user_agent, success, details)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, email, ip_address, user_agent, 1 if success else 0, details),
    )
    conn.commit()


def get_login_logs(limit: int = 200) -> List[Dict[str, Any]]:
    """Get all login logs with user info (for admin)."""
    conn = get_db()
    rows = conn.execute(
        """SELECT l.*, u.name as user_name, u.role as user_role
           FROM login_logs l
           LEFT JOIN users u ON l.user_id = u.id
           ORDER BY l.created_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_login_logs_for_user(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """Get login logs for a specific user."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM login_logs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Application Operations ────────────────────────────────────────────────────

def save_application(user_id: int, app_data: Dict[str, Any]) -> int:
    """Save a scored job application for a user. Returns the application ID."""
    conn = get_db()
    skills_json = json.dumps(app_data.get("matching_skills", []))
    concerns_json = json.dumps(app_data.get("concerns", []))
    cursor = conn.execute(
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
    return cursor.lastrowid


def get_user_applications(user_id: int, min_score: int = 0, limit: int = 200) -> List[Dict[str, Any]]:
    """Get applications for a user, optionally filtering by min score."""
    conn = get_db()
    if min_score > 0:
        rows = conn.execute(
            "SELECT * FROM applications WHERE user_id = ? AND ai_score >= ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, min_score, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM applications WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [_parse_app_row(r) for r in rows]


def get_all_applications(limit: int = 500) -> List[Dict[str, Any]]:
    """Get all applications across all users (for admin)."""
    conn = get_db()
    rows = conn.execute(
        """SELECT a.*, u.email as user_email, u.name as user_name 
           FROM applications a JOIN users u ON a.user_id = u.id 
           ORDER BY a.timestamp DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [_parse_app_row(r) for r in rows]


def delete_application(application_id: int) -> bool:
    """Delete a single application by ID. Returns True if deleted."""
    conn = get_db()
    cursor = conn.execute("DELETE FROM applications WHERE id = ?", (application_id,))
    conn.commit()
    return cursor.rowcount > 0


def clear_user_applications(user_id: int):
    """Clear all applications for a user."""
    conn = get_db()
    conn.execute("DELETE FROM applications WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM saved_jobs WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM applied_jobs WHERE user_id = ?", (user_id,))
    conn.commit()


def clear_all_applications():
    """Clear all applications (admin)."""
    conn = get_db()
    conn.execute("DELETE FROM applications")
    conn.execute("DELETE FROM saved_jobs")
    conn.execute("DELETE FROM applied_jobs")
    conn.commit()


def _parse_app_row(row) -> Dict[str, Any]:
    """Parse a database row into a dict with parsed JSON fields."""
    d = dict(row)
    # Parse JSON fields
    for field in ["matching_skills", "concerns"]:
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = []
    return d


# ── Applied Jobs Operations ──────────────────────────────────────────────────

def mark_applied(user_id: int, url: str) -> bool:
    """Mark a job as applied. Returns True if newly marked."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO applied_jobs (user_id, url) VALUES (?, ?)",
            (user_id, url),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_applied_urls(user_id: int) -> set:
    """Get set of applied job URLs for a user."""
    conn = get_db()
    rows = conn.execute(
        "SELECT url FROM applied_jobs WHERE user_id = ?", (user_id,)
    ).fetchall()
    return {r["url"] for r in rows}


# ── Saved Jobs Operations ─────────────────────────────────────────────────────

def save_job_with_data(user_id: int, job_data: Dict[str, Any]) -> Optional[int]:
    """Save a job application and mark it as saved/bookmarked in one call.
    Returns the application ID if successful, None on failure.
    """
    # First save the application data
    app_id = save_application(user_id, job_data)
    if not app_id:
        return None
    # Then mark it as saved
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO saved_jobs (user_id, application_id) VALUES (?, ?)",
            (user_id, app_id),
        )
        conn.commit()
        return app_id
    except sqlite3.IntegrityError:
        # Already saved, return the app_id anyway
        return app_id


def get_saved_applications(user_id: int) -> List[Dict[str, Any]]:
    """Get all saved job applications with full data for a user."""
    conn = get_db()
    rows = conn.execute(
        """SELECT a.*, s.saved_at
           FROM saved_jobs s
           JOIN applications a ON s.application_id = a.id
           WHERE s.user_id = ?
           ORDER BY s.saved_at DESC""",
        (user_id,),
    ).fetchall()
    return [_parse_app_row(r) for r in rows]


def cleanup_old_saved_jobs(days: int = 7):
    """Delete saved jobs (and their application data) older than the specified number of days."""
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    conn = get_db()
    # Get IDs of applications to delete
    rows = conn.execute(
        """SELECT s.application_id
           FROM saved_jobs s
           WHERE s.saved_at < ?""",
        (cutoff,),
    ).fetchall()
    app_ids = [r["application_id"] for r in rows]
    if not app_ids:
        return 0
    # Delete from saved_jobs first
    conn.execute(
        "DELETE FROM saved_jobs WHERE saved_at < ?",
        (cutoff,),
    )
    # Then delete orphaned applications (CASCADE will handle related data)
    for app_id in app_ids:
        conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
    conn.commit()
    logger = __import__('logging').getLogger(__name__)
    logger.info(f"Cleaned up {len(app_ids)} saved job(s) older than {days} days")
    return len(app_ids)


def save_job(user_id: int, application_id: int) -> bool:
    """Save/bookmark a job. Returns True if newly saved."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO saved_jobs (user_id, application_id) VALUES (?, ?)",
            (user_id, application_id),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def unsave_job(user_id: int, application_id: int) -> bool:
    """Remove a saved/bookmarked job."""
    conn = get_db()
    cursor = conn.execute(
        "DELETE FROM saved_jobs WHERE user_id = ? AND application_id = ?",
        (user_id, application_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_saved_application_ids(user_id: int) -> set:
    """Get set of saved application IDs for a user."""
    conn = get_db()
    rows = conn.execute(
        "SELECT application_id FROM saved_jobs WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    return {r["application_id"] for r in rows}


def get_stats(user_id: Optional[int] = None) -> Dict[str, Any]:
    """Get stats for a user, or overall stats (admin)."""
    conn = get_db()
    if user_id:
        total = conn.execute(
            "SELECT COUNT(*) as c FROM applications WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        avg = conn.execute(
            "SELECT COALESCE(AVG(ai_score), 0) as a FROM applications WHERE user_id = ? AND ai_score > 0",
            (user_id,),
        ).fetchone()["a"]
        high = conn.execute(
            "SELECT COUNT(*) as c FROM applications WHERE user_id = ? AND ai_score >= 80",
            (user_id,),
        ).fetchone()["c"]
        saved = conn.execute(
            "SELECT COUNT(*) as c FROM saved_jobs WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
    else:
        total = conn.execute("SELECT COUNT(*) as c FROM applications").fetchone()["c"]
        avg = conn.execute(
            "SELECT COALESCE(AVG(ai_score), 0) as a FROM applications WHERE ai_score > 0"
        ).fetchone()["a"]
        high = conn.execute(
            "SELECT COUNT(*) as c FROM applications WHERE ai_score >= 80"
        ).fetchone()["c"]
        saved = conn.execute("SELECT COUNT(*) as c FROM saved_jobs").fetchone()["c"]

    return {
        "total_jobs": total,
        "avg_score": round(avg, 1),
        "high_match": high,
        "saved_jobs": saved,
    }
