"""
Authentication module for Job Agent.
Handles user registration, login, logout, and session management.
Uses werkzeug for password hashing and Flask sessions for auth state.
"""

import logging
from functools import wraps
from typing import Optional, Dict, Any, Callable

from flask import session, redirect, url_for, request, jsonify, g

from werkzeug.security import generate_password_hash, check_password_hash

from .database import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    get_all_users,
    init_db,
)

logger = logging.getLogger(__name__)

# ── Password Hashing ──────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash a password using werkzeug."""
    return generate_password_hash(password)


def verify_password(password: str, hash_str: str) -> bool:
    """Verify a password against its hash."""
    return check_password_hash(hash_str, password)


# ── Session Management ────────────────────────────────────────────────────────


def login_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate a user. Returns user dict on success, None on failure.
    Returns dict with 'error' key if user is pending or rejected.
    Auto-activates the default admin account if it's pending.
    """
    user = get_user_by_email(email)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    
    # Check account status
    status = user.get("status", "active")
    if status == "pending":
        # Auto-activate the default admin account so they can always log in
        if email.lower() == DEFAULT_ADMIN_EMAIL.lower():
            from .database import update_user_status, update_user_role
            update_user_status(user["id"], "active")
            update_user_role(user["id"], "admin")
            logger.info(f"Auto-activated admin account: {email}")
            # Re-fetch user with updated status
            user = get_user_by_email(email)
            status = user.get("status", "active")
        else:
            return {"error": "pending", "message": "Your account is pending admin approval. Please wait for an admin to activate it."}
    if status == "rejected":
        return {"error": "rejected", "message": "Your account registration was rejected by the admin."}
    
    # Set session
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session["user_role"] = user["role"]
    session["user_email"] = user["email"]
    return user


def logout_user():
    """Clear the user session."""
    session.pop("user_id", None)
    session.pop("user_name", None)
    session.pop("user_role", None)
    session.pop("user_email", None)


def get_current_user() -> Optional[Dict[str, Any]]:
    """Get the currently logged-in user from database, or None."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_user_by_id(user_id)


def register_user(email: str, password: str, name: str) -> Optional[Dict[str, Any]]:
    """Register a new user. Returns user dict or None if email taken.
    New users are created with status='pending' and require admin approval.
    """
    pw_hash = hash_password(password)
    # New users are created as 'pending' — admin must approve them
    user = create_user(email, pw_hash, name, role="user", status="pending")
    return user


def require_login(f: Callable) -> Callable:
    """Decorator: redirect to login if not authenticated.
    For JSON endpoints, returns 401 instead.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            # Check if it's an API/JSON request
            if request.is_json or request.path.startswith("/api/") or request.path.startswith("/admin/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


def require_admin(f: Callable) -> Callable:
    """Decorator: require admin role.
    For JSON/API endpoints, returns 401/403 instead of redirecting.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            if request.is_json or request.path.startswith("/api/") or request.path.startswith("/admin/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login_page"))
        if session.get("user_role") != "admin":
            if request.is_json or request.path.startswith("/api/") or request.path.startswith("/admin/"):
                return jsonify({"error": "Admin access required"}), 403
            return "Admin access required", 403
        return f(*args, **kwargs)
    return decorated


def is_admin() -> bool:
    """Check if current user is an admin."""
    return session.get("user_role") == "admin"


def get_user_id() -> Optional[int]:
    """Get current user's ID from session."""
    return session.get("user_id")


# ── Admin Initialization ──────────────────────────────────────────────────────

DEFAULT_ADMIN_EMAIL = "Gokulkrishnanalla@gmail.com"
DEFAULT_ADMIN_PASSWORD = "admin123"
DEFAULT_ADMIN_NAME = "Gokul"


def ensure_admin_exists():
    """Create the default admin user if no admin exists.
    Admin is created with status='active' so they can log in immediately.
    Also:
    - Migrates old admin email to the current default if needed.
    - Ensures existing admin account is active with correct role.
    """
    init_db()
    from .database import update_user_email, update_user_name, delete_user, update_user_role, update_user_status
    
    # Migration: check if old admin email exists and update it
    old_admin_emails = ["admin@jobagent.com"]
    for old_email in old_admin_emails:
        if old_email.lower() != DEFAULT_ADMIN_EMAIL.lower():
            old_admin = get_user_by_email(old_email)
            if old_admin and old_admin.get("role") == "admin":
                new_admin = get_user_by_email(DEFAULT_ADMIN_EMAIL)
                if new_admin:
                    delete_user(old_admin["id"])
                    logger.info(f"Removed old admin account: {old_email}")
                else:
                    update_user_email(old_admin["id"], DEFAULT_ADMIN_EMAIL)
                    update_user_name(old_admin["id"], DEFAULT_ADMIN_NAME)
                    logger.info(f"Migrated admin from {old_email} to {DEFAULT_ADMIN_EMAIL}")
    
    # Check if the admin account exists but has wrong status/role
    admin = get_user_by_email(DEFAULT_ADMIN_EMAIL)
    if admin:
        # IMPORTANT: Only the default admin email gets upgraded
        # Regular users should never be made admin
        # Ensure admin is active and has correct role
        if admin.get("role") != "admin":
            update_user_role(admin["id"], "admin")
            logger.info(f"Upgraded user {DEFAULT_ADMIN_EMAIL} to admin role")
        if admin.get("status") != "active":
            update_user_status(admin["id"], "active")
            logger.info(f"Activated admin account: {DEFAULT_ADMIN_EMAIL}")
        # Only reset admin password if it doesn't match the default
        from werkzeug.security import check_password_hash
        if not check_password_hash(admin["password_hash"], DEFAULT_ADMIN_PASSWORD):
            from .database import update_user_password
            new_hash = hash_password(DEFAULT_ADMIN_PASSWORD)
            update_user_password(admin["id"], new_hash)
            logger.info(f"Reset admin password for {DEFAULT_ADMIN_EMAIL}")
        return
    
    pw_hash = hash_password(DEFAULT_ADMIN_PASSWORD)
    result = create_user(DEFAULT_ADMIN_EMAIL, pw_hash, DEFAULT_ADMIN_NAME, role="admin", status="active")
    if result:
        logger.info(f"Default admin created: {DEFAULT_ADMIN_EMAIL} / {DEFAULT_ADMIN_PASSWORD}")
    else:
        logger.warning("Failed to create default admin")


# ── API Key helpers ───────────────────────────────────────────────────────────

from .database import update_user_api_key


def set_user_api_key(user_id: int, api_key: str):
    """Set a user's Claude API key."""
    update_user_api_key(user_id, api_key)
    session["api_key_set"] = bool(api_key)
