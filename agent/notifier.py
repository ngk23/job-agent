"""
Email notification module for Job Agent.
Sends email notifications when admin approves or rejects a user.
Uses Resend (recommended) as primary email API.
Falls back quietly if no email service is configured.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Resend API key — checked in order:
# 1. Runtime-set key (from dashboard admin panel, stored in DB)
# 2. Environment variable (RESEND_API_KEY)
_runtime_api_key: str = ""


def set_resend_api_key(key: str):
    """Set the Resend API key at runtime (from dashboard admin panel)."""
    global _runtime_api_key
    _runtime_api_key = key


def _get_resend_api_key() -> str:
    """Get the Resend API key, checking runtime key first, then env var."""
    if _runtime_api_key:
        return _runtime_api_key
    return os.environ.get("RESEND_API_KEY", "")

# Email configuration
EMAIL_FROM = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")
APP_URL = os.environ.get("APP_URL", "https://gouklkrishan-job-agent.hf.space")

# Base subject and body templates
APPROVED_SUBJECT = "Your Job Agent account has been approved!"
APPROVED_BODY = """
Hi {name},

Your account on Job Agent has been approved! 🎉

You can now log in and start using the platform:
{app_url}

What you can do:
• Upload your CV and let the AI analyze your profile
• Search for jobs across LinkedIn, Indeed, Glassdoor, and Monster
• Get AI-powered match scores for each job
• Generate tailored CVs for high-match positions
• Save your favorite jobs for later

Log in here: {app_url}

Happy job hunting!
— The Job Agent Team
"""

REJECTED_SUBJECT = "Your Job Agent registration was not approved"
REJECTED_BODY = """
Hi {name},

Unfortunately, your registration request for Job Agent was not approved by the admin.

If you believe this was a mistake, please contact the administrator directly.

— The Job Agent Team
"""


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an email using the configured provider.
    Returns True if sent successfully, False if not configured or failed.
    """
    api_key = _get_resend_api_key()
    if api_key:
        return _send_via_resend(to_email, subject, body, api_key)
    else:
        logger.info(f"Email not sent (RESEND_API_KEY not configured). Would send to {to_email}: {subject}")
        logger.info(f"Set RESEND_API_KEY env var or configure in Admin panel to enable email notifications.")
        return False


def _send_via_resend(to_email: str, subject: str, body: str, api_key: str) -> bool:
    """Send email via Resend API."""
    try:
        import resend
        resend.api_key = api_key
        
        params = {
            "from": EMAIL_FROM,
            "to": [to_email],
            "subject": subject,
            "text": body.strip(),
        }
        
        response = resend.Emails.send(params)
        logger.info(f"Email sent to {to_email}: {subject} (id: {response.get('id', 'unknown')})")
        return True
    except ImportError:
        logger.warning("resend package not installed. Run: pip install resend")
        return False
    except Exception as e:
        logger.error(f"Failed to send email via Resend to {to_email}: {e}")
        return False


def notify_approved(user_email: str, user_name: str) -> bool:
    """Send approval notification email to a user."""
    body = APPROVED_BODY.format(name=user_name, app_url=APP_URL)
    logger.info(f"Sending approval email to {user_email} via {EMAIL_FROM}")
    return send_email(user_email, APPROVED_SUBJECT, body)


def notify_rejected(user_email: str, user_name: str) -> bool:
    """Send rejection notification email to a user."""
    body = REJECTED_BODY.format(name=user_name, app_url=APP_URL)
    logger.info(f"Sending rejection email to {user_email} via {EMAIL_FROM}")
    return send_email(user_email, REJECTED_SUBJECT, body)


PASSWORD_RESET_SUBJECT = "Reset your Job Agent password"
PASSWORD_RESET_BODY = """
Hi {name},

We received a request to reset your password for your Job Agent account.

Click the link below to reset your password (valid for 1 hour):
{reset_url}

If you did not request a password reset, you can safely ignore this email.

— The Job Agent Team
"""


def send_password_reset_email(user_email: str, user_name: str, reset_token: str) -> bool:
    """Send a password reset email with a secure token link."""
    reset_url = f"{APP_URL}/reset-password/{reset_token}"
    body = PASSWORD_RESET_BODY.format(name=user_name, reset_url=reset_url)
    return send_email(user_email, PASSWORD_RESET_SUBJECT, body)
