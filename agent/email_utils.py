"""
Email utility module for Job Agent.
Sends password reset emails using Gmail SMTP.
Reuses Gmail credential management from notifier.py.
"""

import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from .notifier import _get_gmail_credentials

logger = logging.getLogger(__name__)

APP_URL = os.environ.get("APP_URL", "https://gouklkrishan-job-agent.hf.space")


def send_password_reset_email(user_email: str, user_name: str, reset_token: str) -> bool:
    """
    Send a password reset email with a secure token link via Gmail SMTP.

    Args:
        user_email: The recipient's email address
        user_name: The user's name (used in greeting)
        reset_token: The password reset token

    Returns:
        True if email was sent successfully, False otherwise
    """
    gmail_user, gmail_app_password = _get_gmail_credentials()
    if not gmail_user or not gmail_app_password:
        logger.info(
            f"Password reset email not sent to {user_email} "
            f"(Gmail SMTP not configured)"
        )
        return False

    reset_link = f"{APP_URL}/reset-password/{reset_token}"
    greeting = f"Hi {user_name}," if user_name else "Hi,"
    subject = "Reset your Job Agent password"

    html = f"""\
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
        msg = MIMEMultipart("alternative")
        msg["From"] = gmail_user
        msg["To"] = user_email
        msg["Subject"] = subject
        msg.attach(MIMEText(text.strip(), "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_app_password)
            server.sendmail(gmail_user, user_email, msg.as_string())

        logger.info(f"Password reset email sent to {user_email}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(f"Gmail SMTP authentication failed for {gmail_user}. Check GMAIL_APP_PASSWORD.")
        return False
    except Exception as e:
        logger.error(f"Failed to send password reset email to {user_email}: {e}")
        return False
