"""
Email utility module for Job Agent.
Sends password reset emails using Resend API.
Reuses the Resend API key management from notifier.py.
"""

import logging
import os

from .notifier import _get_resend_api_key

logger = logging.getLogger(__name__)

EMAIL_FROM = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")
APP_URL = os.environ.get("APP_URL", "https://gouklkrishan-job-agent.hf.space")


def send_password_reset_email(to_email: str, reset_token: str, user_name: str = "") -> bool:
    """
    Send a password reset email with a secure token link.

    Args:
        to_email: The recipient's email address
        reset_token: The password reset token
        user_name: The user's name (optional, used in greeting)

    Returns:
        True if email was sent successfully, False otherwise
    """
    api_key = _get_resend_api_key()
    if not api_key:
        logger.info(
            f"Password reset email not sent to {to_email} "
            f"(RESEND_API_KEY not configured)"
        )
        return False

    reset_link = f"{APP_URL}/reset-password/{reset_token}"
    greeting = f"Hi {user_name}," if user_name else "Hi,"
    subject = "Reset your Job Agent password"

    html = f"""
        <p>{greeting}</p>
        <p>We received a request to reset your password for your Job Agent account.</p>
        <p>Click the link below to reset your password (valid for 1 hour):</p>
        <p><a href="{reset_link}" style="color:#00ff41;">Reset Password</a></p>
        <p>If you didn't request this, you can safely ignore this email.</p>
        <hr>
        <p style="color:#666;font-size:0.85em;">— The Job Agent Team</p>
    """

    text = (
        f"{greeting}\n\n"
        f"We received a request to reset your password for your Job Agent account.\n\n"
        f"Click the link below to reset your password (valid for 1 hour):\n"
        f"{reset_link}\n\n"
        f"If you didn't request this, you can safely ignore this email.\n\n"
        f"— The Job Agent Team"
    )

    try:
        import resend
        resend.api_key = api_key

        params = {
            "from": EMAIL_FROM,
            "to": [to_email],
            "subject": subject,
            "html": html,
            "text": text.strip(),
        }

        response = resend.Emails.send(params)
        logger.info(
            f"Password reset email sent to {to_email} (id: {response.get('id', 'unknown')})"
        )
        return True

    except ImportError:
        logger.warning("resend package not installed. Run: pip install resend")
        return False
    except Exception as e:
        logger.error(f"Failed to send password reset email to {to_email}: {e}")
        return False
