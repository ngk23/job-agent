"""
Email notification module for Job Agent.
Sends email notifications when admin approves or rejects a user.
Uses Gmail SMTP as the email provider.
Falls back quietly if no email service is configured.
"""

import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

# Gmail SMTP credentials — checked in order:
# 1. Runtime-set (from dashboard admin panel, stored in DB)
# 2. Environment variables (GMAIL_USER, GMAIL_APP_PASSWORD)
_runtime_gmail_user: str = ""
_runtime_gmail_app_password: str = ""


def set_gmail_credentials(gmail_user: str, gmail_app_password: str):
    """Set Gmail SMTP credentials at runtime (from dashboard admin panel)."""
    global _runtime_gmail_user, _runtime_gmail_app_password
    _runtime_gmail_user = gmail_user
    _runtime_gmail_app_password = gmail_app_password


def _get_gmail_credentials() -> tuple:
    """Get Gmail SMTP credentials: runtime first, env vars fallback, then database."""
    global _runtime_gmail_user, _runtime_gmail_app_password
    if _runtime_gmail_user and _runtime_gmail_app_password:
        return _runtime_gmail_user, _runtime_gmail_app_password

    user = os.environ.get("GMAIL_USER", "")
    app_pw = os.environ.get("GMAIL_APP_PASSWORD", "")
    if user and app_pw:
        return user, app_pw

    # Fallback: check database for any user's saved credentials
    # First by specific admin email, then by role, then any user
    try:
        from .database import get_db, get_user_by_email
        conn = get_db()

        # Try 1: Look up the default admin email specifically
        from .auth import DEFAULT_ADMIN_EMAIL
        admin_user = get_user_by_email(DEFAULT_ADMIN_EMAIL)
        if admin_user and admin_user.get("gmail_user") and admin_user.get("gmail_app_password"):
            _runtime_gmail_user = admin_user["gmail_user"]
            _runtime_gmail_app_password = admin_user["gmail_app_password"]
            return _runtime_gmail_user, _runtime_gmail_app_password

        # Try 2: Any user with role='admin' that has gmail credentials
        row = conn.execute(
            "SELECT gmail_user, gmail_app_password FROM users WHERE role = ? "
            "AND gmail_user IS NOT NULL AND gmail_user != '' "
            "AND gmail_app_password IS NOT NULL AND gmail_app_password != '' LIMIT 1",
            ("admin",),
        ).fetchone()
        if row and row["gmail_user"] and row["gmail_app_password"]:
            _runtime_gmail_user = row["gmail_user"]
            _runtime_gmail_app_password = row["gmail_app_password"]
            return _runtime_gmail_user, _runtime_gmail_app_password

        # Try 3: Any user at all (in case roles are weird)
        row = conn.execute(
            "SELECT gmail_user, gmail_app_password FROM users "
            "WHERE gmail_user IS NOT NULL AND gmail_user != '' "
            "AND gmail_app_password IS NOT NULL AND gmail_app_password != '' LIMIT 1",
        ).fetchone()
        if row and row["gmail_user"] and row["gmail_app_password"]:
            _runtime_gmail_user = row["gmail_user"]
            _runtime_gmail_app_password = row["gmail_app_password"]
            return _runtime_gmail_user, _runtime_gmail_app_password
    except Exception as e:
        logger.warning("Gmail credential DB lookup failed: %s", e)
    return ("", "")


# Email configuration
APP_URL = os.environ.get("APP_URL", "https://gouklkrishan-job-agent.hf.space")

# Base subject and body templates
APPROVED_SUBJECT = "Your Job Agent account has been approved!"
APPROVED_BODY = """\
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
REJECTED_BODY = """\
Hi {name},

Unfortunately, your registration request for Job Agent was not approved by the admin.

If you believe this was a mistake, please contact the administrator directly.

— The Job Agent Team
"""


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an email using Gmail SMTP.
    Returns True if sent successfully, False if not configured or failed.
    """
    gmail_user, gmail_app_password = _get_gmail_credentials()
    if gmail_user and gmail_app_password:
        return _send_via_gmail(to_email, subject, body, gmail_user, gmail_app_password)
    else:
        logger.info(f"Email not sent (Gmail SMTP not configured). Would send to {to_email}: {subject}")
        logger.info("Set GMAIL_USER and GMAIL_APP_PASSWORD env vars or configure in Admin panel.")
        return False


def _send_via_gmail(to_email: str, subject: str, body: str, gmail_user: str, gmail_app_password: str) -> bool:
    """Send email via Gmail SMTP."""
    try:
        msg = MIMEMultipart()
        msg["From"] = gmail_user
        msg["To"] = to_email
        msg["Subject"] = subject
        body_html = body.replace("\n", "<br>")
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(gmail_user, gmail_app_password)
            server.sendmail(gmail_user, to_email, msg.as_string())

        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email via Gmail SMTP to {to_email}: {e}")
        return False


def notify_approved(user_email: str, user_name: str) -> bool:
    """Send approval notification email to a user."""
    body = APPROVED_BODY.format(name=user_name, app_url=APP_URL)
    logger.info(f"Sending approval email to {user_email}")
    return send_email(user_email, APPROVED_SUBJECT, body)


def notify_rejected(user_email: str, user_name: str) -> bool:
    """Send rejection notification email to a user."""
    body = REJECTED_BODY.format(name=user_name, app_url=APP_URL)
    logger.info(f"Sending rejection email to {user_email}")
    return send_email(user_email, REJECTED_SUBJECT, body)


PASSWORD_RESET_SUBJECT = "Reset your Job Agent password"
PASSWORD_RESET_BODY = """\
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
