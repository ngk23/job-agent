"""
Daily usage tracker for Job Agent.
Limits:
  - Max 3 UNIQUE users per day
  - Max 250 job searches per user per day
  - Auto-resets at midnight
  - Uses SQLite for persistence across restarts
"""

import logging
from datetime import datetime, date
from typing import Optional, Dict, Any

from .database import get_db

logger = logging.getLogger(__name__)

# Limits
MAX_USERS_PER_DAY = 3
MAX_SEARCHES_PER_USER = 250


def init_usage_table():
    """Create the daily_usage table if it doesn't exist (safe to call multiple times)."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            usage_date TEXT NOT NULL,
            search_count INTEGER DEFAULT 0,
            UNIQUE(user_id, usage_date)
        );
        CREATE INDEX IF NOT EXISTS idx_daily_usage_date ON daily_usage(usage_date);
    """)
    conn.commit()


def _today_str() -> str:
    """Get today's date as YYYY-MM-DD string."""
    return date.today().isoformat()


def get_today_usage() -> Dict[str, Any]:
    """Get current usage stats for today.
    
    Returns:
        Dict with:
            - date: today's date string
            - total_users: number of distinct users who searched today
            - user_usage: dict of {user_id: search_count} for each user who searched today
    """
    conn = get_db()
    today = _today_str()
    
    rows = conn.execute(
        "SELECT user_id, search_count FROM daily_usage WHERE usage_date = ?",
        (today,),
    ).fetchall()
    
    user_usage = {r["user_id"]: r["search_count"] for r in rows}
    
    return {
        "date": today,
        "total_users": len(user_usage),
        "user_usage": user_usage,
    }


def can_run_search(user_id: int) -> Dict[str, Any]:
    """Check if a user is allowed to run a job search today.
    
    Returns dict with:
        - allowed: bool
        - reason: str (why blocked, if not allowed)
        - searches_today: int (how many searches this user has done today)
        - searches_remaining: int (how many more this user can do)
        - users_today: int (how many distinct users have searched today)
    """
    init_usage_table()
    today = _today_str()
    usage = get_today_usage()
    
    # Check 1: How many searches has this user already done today?
    user_count = usage["user_usage"].get(user_id, 0)
    
    # Check 2: If this is a new user for today, would we exceed the 3-user limit?
    is_new_user_today = user_id not in usage["user_usage"]
    
    if is_new_user_today and usage["total_users"] >= MAX_USERS_PER_DAY:
        return {
            "allowed": False,
            "reason": f"Daily limit reached: {MAX_USERS_PER_DAY} users have already searched today. Try again tomorrow.",
            "searches_today": 0,
            "searches_remaining": 0,
            "users_today": usage["total_users"],
        }
    
    if user_count >= MAX_SEARCHES_PER_USER:
        return {
            "allowed": False,
            "reason": f"Daily limit reached: You've done {user_count} searches today (max {MAX_SEARCHES_PER_USER}). Try again tomorrow.",
            "searches_today": user_count,
            "searches_remaining": 0,
            "users_today": usage["total_users"],
        }
    
    return {
        "allowed": True,
        "reason": "",
        "searches_today": user_count,
        "searches_remaining": MAX_SEARCHES_PER_USER - user_count,
        "users_today": usage["total_users"],
    }


def increment_search_count(user_id: int) -> bool:
    """Increment the search count for a user today.
    Returns True if incremented successfully, False if limit would be exceeded.
    """
    init_usage_table()
    today = _today_str()
    conn = get_db()
    
    # Get current count
    row = conn.execute(
        "SELECT search_count FROM daily_usage WHERE user_id = ? AND usage_date = ?",
        (user_id, today),
    ).fetchone()
    
    current = row["search_count"] if row else 0
    
    if current >= MAX_SEARCHES_PER_USER:
        return False
    
    if row:
        conn.execute(
            "UPDATE daily_usage SET search_count = search_count + 1 WHERE user_id = ? AND usage_date = ?",
            (user_id, today),
        )
    else:
        # Check 3-user limit before adding new user
        today_users = conn.execute(
            "SELECT COUNT(DISTINCT user_id) as c FROM daily_usage WHERE usage_date = ?",
            (today,),
        ).fetchone()["c"]
        if today_users >= MAX_USERS_PER_DAY:
            return False
        conn.execute(
            "INSERT INTO daily_usage (user_id, usage_date, search_count) VALUES (?, ?, 1)",
            (user_id, today),
        )
    
    conn.commit()
    return True


def get_usage_summary() -> Dict[str, Any]:
    """Get a human-readable summary of today's usage for the admin panel."""
    usage = get_today_usage()
    return {
        "date": usage["date"],
        "users_today": usage["total_users"],
        "max_users": MAX_USERS_PER_DAY,
        "users_remaining": MAX_USERS_PER_DAY - usage["total_users"],
        "max_searches_per_user": MAX_SEARCHES_PER_USER,
        "user_details": usage["user_usage"],
    }
