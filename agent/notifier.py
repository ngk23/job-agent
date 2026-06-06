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

# Resend API key from environment variable
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")

# Email configuration
EMAIL_FROM = os.environ.get("EMAIL_FROM", "noreply@jobagent.app")
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
    if RESEND_API_KEY:
        return _send_via_resend(to_email, subject, body)
    else:
        logger.info(f"Email not sent (RESEND_API_KEY not configured). Would send to {to_email}: {subject}")
        logger.info(f"Set RESEND_API_KEY env var to enable email notifications.")
        return False


def _send_via_resend(to_email: str, subject: str, body: str) -> bool:
    """Send email via Resend API."""
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        
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
    return send_email(user_email, APPROVED_SUBJECT, body)


def notify_rejected(user_email: str, user_name: str) -> bool:
    """Send rejection notification email to a user."""
    body = REJECTED_BODY.format(name=user_name, app_url=APP_URL)
    return send_email(user_email, REJECTED_SUBJECT, body)
