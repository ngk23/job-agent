"""
Authentication module for Job Agent (FastAPI version).
Uses werkzeug for password hashing and Starlette's SessionMiddleware for auth state.
"""

import logging
from typing import Optional, Dict, Any

from starlette.requests import Request
from starlette.responses import RedirectResponse, JSONResponse
from werkzeug.security import generate_password_hash, check_password_hash

from .database import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    get_all_users,
    init_db,
)
from .auth import register_user

logger = logging.getLogger(__name__)

# ── Password Hashing ──────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash a password using werkzeug."""
    return generate_password_hash(password)


def verify_password(password: str, hash_str: str) -> bool:
    """Verify a password against its hash."""
    return check_password_hash(hash_str, password)


# ── Session Management ────────────────────────────────────────────────────────


def login_user_fastapi(request: Request, email: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate a user. Sets session on the Starlette Request.
    Returns user dict on success, None on failure.
    Returns dict with 'error' key if user is pending or rejected.
    Auto-activates the default admin account if it's pending.
    """
    from .auth import DEFAULT_ADMIN_EMAIL
    user = get_user_by_email(email)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None

    # Check account status
    status = user.get("status", "active")
    if status == "pending":
        if email.lower() == DEFAULT_ADMIN_EMAIL.lower():
            from .database import update_user_status, update_user_role
            update_user_status(user["id"], "active")
            update_user_role(user["id"], "admin")
            logger.info(f"Auto-activated admin account: {email}")
            user = get_user_by_email(email)
            status = user.get("status", "active")
        else:
            return {"error": "pending", "message": "Your account is pending admin approval."}
    if status == "rejected":
        return {"error": "rejected", "message": "Your account registration was rejected by the admin."}

    # Set session
    request.session["user_id"] = user["id"]
    request.session["user_name"] = user["name"]
    request.session["user_role"] = user["role"]
    request.session["user_email"] = user["email"]
    return user


def logout_user_fastapi(request: Request):
    """Clear the user session."""
    request.session.pop("user_id", None)
    request.session.pop("user_name", None)
    request.session.pop("user_role", None)
    request.session.pop("user_email", None)


def get_current_user_fastapi(request: Request) -> Optional[Dict[str, Any]]:
    """Get the currently logged-in user from database, or None."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return get_user_by_id(user_id)


def register_user(email: str, password: str, name: str) -> Optional[Dict[str, Any]]:
    """Register a new user (re-exports from auth.py)."""
    from .auth import register_user as _reg
    return _reg(email, password, name)


# ── FastAPI Dependencies ──────────────────────────────────────────────────────


async def require_login_fastapi(request: Request):
    """FastAPI dependency: require authentication.
    Redirects to /login for page requests, returns 401 for API requests.
    """
    if not request.session.get("user_id"):
        if request.url.path.startswith("/api/") or request.url.path.startswith("/admin/"):
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        return RedirectResponse(url="/login", status_code=302)
    return None  # Continue to route handler


async def require_admin_fastapi(request: Request):
    """FastAPI dependency: require admin role.
    Returns 401 for unauthenticated, 403 for non-admins.
    """
    if not request.session.get("user_id"):
        if request.url.path.startswith("/api/") or request.url.path.startswith("/admin/"):
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        return RedirectResponse(url="/login", status_code=302)
    if request.session.get("user_role") != "admin":
        if request.url.path.startswith("/api/") or request.url.path.startswith("/admin/"):
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        return JSONResponse({"error": "Admin access required"}, status_code=403)
    return None  # Continue to route handler


def is_admin_fastapi(request: Request) -> bool:
    """Check if current user is an admin."""
    return request.session.get("user_role") == "admin"


def get_user_id_fastapi(request: Request) -> Optional[int]:
    """Get current user's ID from session."""
    return request.session.get("user_id")


def require_login_json(request: Request):
    """FastAPI dependency: require auth for JSON APIs only. Returns 401 on failure."""
    if not request.session.get("user_id"):
        return JSONResponse({"error": "Authentication required", "status": "unauthorized"}, status_code=401)
    return None


def require_admin_json(request: Request):
    """FastAPI dependency: require admin for JSON APIs. Returns 401/403 on failure."""
    if not request.session.get("user_id"):
        return JSONResponse({"error": "Authentication required", "status": "unauthorized"}, status_code=401)
    if request.session.get("user_role") != "admin":
        return JSONResponse({"error": "Admin access required", "status": "forbidden"}, status_code=403)
    return None
