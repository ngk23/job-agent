"""
Google OAuth module for Job Agent.
Uses Authlib to provide Google Sign-In functionality.
"""

import logging
import os
from typing import Optional, Dict, Any

from authlib.integrations.flask_client import OAuth
from flask import session, url_for

logger = logging.getLogger(__name__)

# Google OAuth config
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# OAuth instance (initialized lazily)
_oauth: Optional[OAuth] = None
_oauth_initialized = False


def init_oauth(app) -> Optional[OAuth]:
    """Initialize OAuth with Google provider. Returns OAuth instance or None if not configured."""
    global _oauth, _oauth_initialized

    if _oauth_initialized:
        return _oauth

    _oauth_initialized = True

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        logger.info("Google OAuth not configured — set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars")
        _oauth = None
        return None

    _oauth = OAuth(app)
    _oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid email profile",
        },
    )
    logger.info("Google OAuth initialized successfully")
    return _oauth


def get_google_oauth():
    """Get the OAuth instance (must be initialized first)."""
    return _oauth


def is_google_oauth_configured() -> bool:
    """Check if Google OAuth credentials are configured."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def get_google_redirect_uri() -> str:
    """Get the callback URL for Google OAuth."""
    # Use APP_URL from notifier or fall back to request-based URL
    app_url = os.environ.get("APP_URL", "")
    if app_url:
        return f"{app_url}/login/google/callback"
    # Fallback: will be set dynamically in the route
    return ""


# User info extraction from Google token
def extract_user_info(userinfo: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract standardized user info from Google's userinfo response."""
    if not userinfo:
        return None
    return {
        "google_id": userinfo.get("sub", ""),
        "email": userinfo.get("email", "").lower(),
        "name": userinfo.get("name", ""),
        "picture": userinfo.get("picture", ""),
    }
