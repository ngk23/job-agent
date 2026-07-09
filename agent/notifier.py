"""
Email notification module for Job Agent.
Sends email notifications when admin approves or rejects a user.
Uses Gmail SMTP as the email provider.
Falls back quietly if no email service is configured.
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List

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
        if (
            admin_user
            and admin_user.get("gmail_user")
            and admin_user.get("gmail_app_password")
        ):
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
    """Send a plain-text email using Gmail SMTP.
    Returns True if sent successfully, False if not configured or failed.
    """
    gmail_user, gmail_app_password = _get_gmail_credentials()
    if gmail_user and gmail_app_password:
        return _send_via_gmail(
            to_email, subject, body, gmail_user, gmail_app_password, is_html=False
        )
    else:
        logger.info(
            f"Email not sent (Gmail SMTP not configured). Would send to {to_email}: {subject}"
        )
        logger.info(
            "Set GMAIL_USER and GMAIL_APP_PASSWORD env vars or configure in Admin panel."
        )
        return False


def send_html_email(
    to_email: str, subject: str, html_body: str, text_body: str = ""
) -> bool:
    """Send an HTML email (with plain-text fallback) using Gmail SMTP.
    Returns True if sent successfully, False if not configured or failed.
    """
    gmail_user, gmail_app_password = _get_gmail_credentials()
    if not gmail_user or not gmail_app_password:
        logger.info(
            f"HTML email not sent (Gmail SMTP not configured). Would send to {to_email}: {subject}"
        )
        logger.info(
            "Set GMAIL_USER and GMAIL_APP_PASSWORD env vars or configure in Admin panel."
        )
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = gmail_user
        msg["To"] = to_email
        msg["Subject"] = subject

        # Plain text fallback
        if text_body:
            msg.attach(MIMEText(text_body, "plain"))

        # HTML body
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(gmail_user, gmail_app_password)
            server.sendmail(gmail_user, to_email, msg.as_string())

        logger.info(f"HTML email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send HTML email to {to_email}: {e}")
        return False


def _send_via_gmail(
    to_email: str,
    subject: str,
    body: str,
    gmail_user: str,
    gmail_app_password: str,
    is_html: bool = True,
) -> bool:
    """Send email via Gmail SMTP."""
    try:
        if is_html:
            msg = MIMEMultipart()
            msg["From"] = gmail_user
            msg["To"] = to_email
            msg["Subject"] = subject
            body_html = body.replace("\n", "<br>")
            msg.attach(MIMEText(body_html, "html"))
        else:
            msg = MIMEText(body)
            msg["From"] = gmail_user
            msg["To"] = to_email
            msg["Subject"] = subject

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


JOB_ALERT_SUBJECT = "🎯 Job Agent: {high_match} high-match jobs found for you!"

JOB_ALERT_BODY_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background-color: #f4f6f8; }}
    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
    .header {{ background: linear-gradient(135deg, #0066CC, #004999); color: white; padding: 30px; border-radius: 12px 12px 0 0; text-align: center; }}
    .header h1 {{ margin: 0; font-size: 24px; }}
    .header p {{ margin: 8px 0 0; opacity: 0.9; font-size: 14px; }}
    .stats {{ background: white; padding: 20px; text-align: center; border-bottom: 1px solid #e0e0e0; }}
    .stats .number {{ font-size: 36px; font-weight: bold; color: #0066CC; }}
    .stats .label {{ font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 1px; }}
    .job-card {{ background: white; margin: 12px 0; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    .job-title {{ font-size: 16px; font-weight: bold; color: #333; margin: 0 0 4px; }}
    .job-company {{ font-size: 14px; color: #666; margin: 0 0 8px; }}
    .score-badge {{ display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: bold; margin-bottom: 8px; }}
    .score-high {{ background: #e8f5e9; color: #2e7d32; }}
    .score-good {{ background: #fff3e0; color: #e65100; }}
    .score-low {{ background: #fce4ec; color: #c62828; }}
    .skills {{ margin: 8px 0 0; font-size: 12px; color: #888; }}
    .skills span {{ display: inline-block; background: #e3f2fd; color: #1565c0; padding: 2px 8px; border-radius: 12px; margin: 2px; font-size: 11px; }}
    .apply-btn {{ display: inline-block; margin-top: 10px; padding: 8px 20px; background: #0066CC; color: white; text-decoration: none; border-radius: 6px; font-size: 13px; font-weight: bold; }}
    .footer {{ text-align: center; padding: 20px; color: #999; font-size: 12px; }}
    .title-only {{ font-style: italic; font-size: 11px; color: #999; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🎯 Job Matches Found</h1>
      <p>Hi {name}, here are your best matches from the latest job search</p>
    </div>
    <div class="stats">
      <div class="number">{high_match}</div>
      <div class="label">Jobs matching 60%+ of your skills</div>
    </div>
    {job_cards}
    <div class="footer">
      <p>Generated by Job Agent — AI-powered job search</p>
      <p style="font-size:11px;color:#bbb;">You received this email because your CV was analyzed by Job Agent.</p>
    </div>
  </div>
</body>
</html>
"""

JOB_ALERT_TEXT = """\
🎯 Job Agent Alert — {high_match} high-match jobs found!

Hi {name},

The latest job search found {high_match} jobs matching your profile:

{jobs_text}

Log in to view full details:
{app_url}/login

— Job Agent
"""


def send_job_alert(to_email: str, user_name: str, jobs: List[Dict[str, Any]]) -> bool:
    """Send an email alert listing top-matching jobs.

    Args:
        to_email: Recipient's email address (auto-extracted from CV)
        user_name: Recipient's name
        jobs: List of dicts with keys:
            - title (str)
            - company (str)
            - score (int)
            - url (str)
            - skills (list[str])
            - is_title_only (bool) - whether score was estimated from title only

    Returns:
        True if sent successfully, False otherwise
    """
    if not jobs:
        return False

    # Filter to 60%+ and sort by score descending
    top_jobs = sorted(
        [j for j in jobs if j.get("score", 0) >= 60],
        key=lambda j: j.get("score", 0),
        reverse=True,
    )

    if not top_jobs:
        return False

    # Build HTML job cards
    job_cards_html = []
    jobs_text_lines = []

    for j in top_jobs:
        score = j.get("score", 0)
        if score >= 80:
            badge_class = "score-high"
            score_label = f"{score}% — Excellent Match"
        elif score >= 70:
            badge_class = "score-good"
            score_label = f"{score}% — Strong Match"
        else:
            badge_class = "score-low"
            score_label = f"{score}% — Good Match"

        skills_html = (
            "".join(f"<span>{s}</span>" for s in j.get("skills", [])[:5])
            if j.get("skills")
            else ""
        )

        title_only_note = (
            '<p class="title-only">⚠ Score estimated from title only (no description available)</p>'
            if j.get("is_title_only")
            else ""
        )

        apply_link = j.get("url", "")
        apply_btn = (
            f'<a class="apply-btn" href="{apply_link}">Apply Now →</a>'
            if apply_link
            else ""
        )

        card_html = f"""\
    <div class="job-card">
      <p class="job-title">{j.get('title', 'Unknown')}</p>
      <p class="job-company">{j.get('company', 'Unknown')}</p>
      <span class="score-badge {badge_class}">{score_label}</span>
      {title_only_note}
      {f'<div class="skills">{"Matched skills: " + skills_html if skills_html else ""}</div>' if skills_html else ''}
      {apply_btn}
    </div>
"""
        job_cards_html.append(card_html)

        # Text version
        title_note = " (title-only estimate)" if j.get("is_title_only") else ""
        skills_text = ", ".join(j.get("skills", [])[:3])
        skills_line = f"  • Matched: {skills_text}" if skills_text else ""
        jobs_text_lines.append(
            f"• {j.get('title', 'Unknown')} @ {j.get('company', 'Unknown')} — {score}%{title_note}\n{skills_line}"
        )

    html_body = JOB_ALERT_BODY_HTML.format(
        name=user_name,
        high_match=len(top_jobs),
        job_cards="\n".join(job_cards_html),
    )

    text_body = JOB_ALERT_TEXT.format(
        name=user_name,
        high_match=len(top_jobs),
        jobs_text="\n\n".join(jobs_text_lines),
        app_url=APP_URL,
    )

    subject = JOB_ALERT_SUBJECT.format(high_match=len(top_jobs))

    return send_html_email(to_email, subject, html_body, text_body)


PASSWORD_RESET_SUBJECT = "Reset your Job Agent password"
PASSWORD_RESET_BODY = """\
Hi {name},

We received a request to reset your password for your Job Agent account.

Click the link below to reset your password (valid for 1 hour):
{reset_url}

If you did not request a password reset, you can safely ignore this email.

— The Job Agent Team
"""


def send_password_reset_email(
    user_email: str, user_name: str, reset_token: str
) -> bool:
    """Send a password reset email with a secure token link."""
    reset_url = f"{APP_URL}/reset-password/{reset_token}"
    body = PASSWORD_RESET_BODY.format(name=user_name, reset_url=reset_url)
    return send_email(user_email, PASSWORD_RESET_SUBJECT, body)
