"""
Web GUI for Job Agent (FastAPI version).
Cyberpunk-styled interface with authentication, CV upload,
Run Agent button, real-time streaming output, results display, and admin panel.
"""

import hashlib
import json
import logging
import os
import queue
import secrets
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlparse, urlunparse

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from jinja2 import Template
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .auth import (
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
    ensure_admin_exists,
    hash_password,
)
from .auth import register_user as register_user_fn
from .auth_fastapi import (
    get_current_user_fastapi,
    get_user_id_fastapi,
    is_admin_fastapi,
    login_user_fastapi,
    logout_user_fastapi,
)
from .config import AppConfig
from .database import (
    _cursor,
    approve_user,
    cleanup_expired_tokens,
    cleanup_old_saved_jobs,
    clear_all_applications,
    clear_user_applications,
    create_password_reset_token,
    delete_user,
    get_active_users_count,
    get_all_applications,
    get_all_recent_activity,
    get_all_users,
    get_applied_urls,
    get_db,
    get_db_connection_info,
    get_feedback_summary,
    get_login_logs,
    get_pending_users,
    get_saved_application_ids,
    get_saved_applications,
    get_stats,
    get_user_activity_stats,
    get_user_applications,
)
from .database import get_user_by_email as db_get_user_by_email
from .database import (
    get_user_by_id,
    get_user_by_reset_token,
    init_db,
    log_activity,
    log_login_attempt,
)
from .database import mark_applied as db_mark_applied
from .database import (
    mark_password_changed,
    mark_password_needs_change,
    needs_password_change,
    reject_user,
    save_application,
    save_feedback,
)
from .database import save_job as db_save_job
from .database import (
    save_job_with_data,
)
from .database import unsave_job as db_unsave_job
from .database import (
    update_gmail_credentials,
    update_user_password,
    update_user_resend_key,
    update_user_role,
    use_password_reset_token,
)
from .email_utils import send_password_reset_email
from .feedback_learning import get_feedback_insights_short
from .notifier import (
    _get_gmail_credentials,
    notify_approved,
    notify_rejected,
    set_gmail_credentials,
)
from .tracker import ApplicationTracker
from .utils import _ensure_dirs

logger = logging.getLogger(__name__)

# ── Import HTML templates from shared module ──────────────────────────────────
from .templates_fastapi import GUI_HTML as _GUI_HTML
from .templates_fastapi import LOGIN_HTML as _LOGIN_HTML
from .templates_fastapi import SIGNUP_HTML as _SIGNUP_HTML

_init_persistent_data = lambda c: None  # HF Spaces data init (placeholder)

# ── Background runner ─────────────────────────────────────────────────────────
_output_queue: Optional[queue.Queue] = None
_run_process: Optional[subprocess.Popen] = None
_run_thread: Optional[threading.Thread] = None
_run_complete = False
_stop_requested = False
_run_returncode: Optional[int] = None
_uploaded_filename: str = "resume.pdf"
_dashboard_data_dir: str = "."
_selected_region: str = "Remote"


def _applied_path():
    return Path(_dashboard_data_dir) / "logs" / "applied.json"


def _load_applied() -> set:
    path = _applied_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text())
        return set(data) if isinstance(data, list) else set()
    except (json.JSONDecodeError, IOError):
        return set()


def _save_applied(applied: set):
    path = _applied_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(applied), indent=2))


def _mark_applied(job_url: str) -> bool:
    applied = _load_applied()
    if job_url in applied:
        return False
    applied.add(job_url)
    _save_applied(applied)
    return True


def _run_agent_in_thread(cwd: str, api_key: str = "", user_id: Optional[int] = None):
    global _output_queue, _run_process, _run_complete, _run_returncode, _stop_requested
    env = os.environ.copy()
    if not api_key:
        api_key = env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        api_key = env.get("GROQ_API_KEY", "")
    if not api_key:
        _output_queue.put("[ERROR] No API key configured. Cannot run agent.\n")
        _run_complete = True
        return
    if api_key.startswith("gsk_"):
        env["GROQ_API_KEY"] = api_key
        env["OPENROUTER_API_KEY"] = ""
    else:
        env["OPENROUTER_API_KEY"] = api_key
    env["AGENT_LOCATION"] = _selected_region
    if user_id:
        env["USER_ID"] = str(user_id)
        resume_candidate = Path(_dashboard_data_dir) / "logs" / f"resume_{user_id}.pdf"
        if resume_candidate.exists():
            env["RESUME_PATH"] = str(resume_candidate)
    cmd = [sys.executable, "-m", "agent", "run", "--headless"]
    try:
        fb_insight = get_feedback_insights_short()
        if fb_insight and fb_insight != "No feedback data yet":
            _output_queue.put(f"[LEARN] {fb_insight}\n")
    except Exception:
        pass
    _output_queue.put("[SYSTEM] Initializing Job Agent...\n")
    _output_queue.put("[SYSTEM] Launching browser, searching job platforms...\n\n")
    try:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        _run_process = process
        for line in iter(process.stdout.readline, ""):
            if _output_queue is not None:
                _output_queue.put(line)
        process.wait()
        _run_returncode = process.returncode
        if not _stop_requested:
            _output_queue.put(
                f"\n[SYSTEM] Agent finished with exit code {process.returncode}\n"
            )
        _run_complete = True
    except Exception as e:
        if _output_queue is not None:
            _output_queue.put(f"\n[ERROR] Failed to run agent: {e}\n")
        _run_complete = True


def _agent_status():
    return {
        "running": _run_thread is not None and _run_thread.is_alive(),
        "complete": _run_complete,
        "returncode": _run_returncode,
    }


# ── Template Helpers ─────────────────────────────────────────────────────────

# ── Template cache ───────────────────────────────────────────────────────────
_template_cache = {}


def _render_template(html_str: str, **kwargs) -> str:
    """Render a Jinja2 template string with context. Results are cached."""
    if html_str not in _template_cache:
        _template_cache[html_str] = Template(html_str)
    return _template_cache[html_str].render(**kwargs)


# ── Admin Panel HTML ─────────────────────────────────────────────────────────

ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Job Agent - Admin</title>
<style>@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
*{margin:0;padding:0;box-sizing:border-box}:root{--bg:#0a0a0f;--surface:#12121a;--surface2:#1a1a2e;--border:#2a2a4a;--primary:#00ff41;--accent:#0ff;--text:#c8c8d0;--text-dim:#666;--error:#ff3355;--warning:#ffaa00}
body{font-family:'Share Tech Mono',monospace;background:var(--bg);color:var(--text);padding:20px}
h1{color:var(--primary);font-size:1.5em;margin-bottom:20px;letter-spacing:2px}
h2{color:var(--accent);font-size:1.1em;margin:20px 0 10px;letter-spacing:1px}
table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:20px}
th,td{padding:10px 14px;text-align:left;font-size:0.85em;border-bottom:1px solid var(--border)}
th{background:var(--surface2);color:var(--accent);text-transform:uppercase;letter-spacing:1px;font-size:0.75em}
tr:hover{background:var(--surface2)}
.btn{padding:6px 14px;border:1px solid var(--primary);border-radius:4px;background:transparent;color:var(--primary);font-family:inherit;font-size:0.8em;cursor:pointer;transition:all 0.2s}
.btn:hover{background:rgba(0,255,65,0.1)}.btn.danger{border-color:var(--error);color:var(--error)}.btn.danger:hover{background:rgba(255,51,85,0.1)}
.btn.warning{border-color:var(--warning);color:var(--warning)}.btn.warning:hover{background:rgba(255,170,0,0.1)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px;text-align:center}
.stat .val{font-size:2em;color:var(--primary);font-weight:700}.stat .lbl{color:var(--text-dim);font-size:0.7em;text-transform:uppercase;margin-top:4px}
.nav{margin-bottom:20px}.nav a{color:var(--accent);text-decoration:none;padding:6px 14px;border:1px solid var(--border);border-radius:4px;font-size:0.85em;transition:all 0.2s}.nav a:hover{border-color:var(--accent)}
.msg{padding:8px 12px;border-radius:4px;font-size:0.85em;margin:8px 0}.msg.success{color:var(--primary);background:rgba(0,255,65,0.08);border:1px solid rgba(0,255,65,0.2)}.msg.error{color:var(--error);background:rgba(255,51,85,0.08);border:1px solid rgba(255,51,85,0.2)}
</style></head><body>
<div class="nav"><a href="/">← Dashboard</a> | <a href="/logout" onclick="fetch('/logout',{method:'POST'});return true">Logout</a></div>
<h1>🛡️ Admin Panel</h1>
<div class="stats">
  <div class="stat"><div class="val">{{ stats.total_users }}</div><div class="lbl">Total Users</div></div>
  <div class="stat"><div class="val">{{ stats.active_users }}</div><div class="lbl">Active (7d)</div></div>
  <div class="stat"><div class="val">{{ stats.pending_users }}</div><div class="lbl">Pending</div></div>
  <div class="stat"><div class="val">{{ stats.total_apps }}</div><div class="lbl">Applications</div></div>
</div>
{% if msg %}<div class="msg {{ msg_type }}">{{ msg }}</div>{% endif %}
<h2>📋 Pending Users</h2>
<table><tr><th>Name</th><th>Email</th><th>Date</th><th>Actions</th></tr>
{% for u in pending_users %}
<tr><td>{{ u.name }}</td><td>{{ u.email }}</td><td>{{ u.created_at or '-' }}</td>
<td>
  <button class="btn" onclick="approveUser({{ u.id }})">✅ Approve</button>
  <button class="btn danger" onclick="rejectUser({{ u.id }})">❌ Reject</button>
</td></tr>
{% endfor %}
{% if not pending_users %}<tr><td colspan="4" style="color:var(--text-dim);text-align:center">No pending users</td></tr>{% endif %}
</table>
<h2>👥 All Users</h2>
<table><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Actions</th></tr>
{% for u in all_users %}
<tr><td>{{ u.name }}</td><td>{{ u.email }}</td><td>{{ u.role }}</td><td>{{ u.status or 'active' }}</td>
<td>
  {% if u.role != 'admin' %}<button class="btn warning" onclick="makeAdmin({{ u.id }})">👑 Admin</button>{% endif %}
  <button class="btn danger" onclick="deleteUser({{ u.id }})">🗑</button>
</td></tr>
{% endfor %}</table>

<h2>🔑 Gmail SMTP Settings</h2>
<form id="gmailForm" onsubmit="return saveGmail(event)" style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px;display:flex;gap:10px;flex-wrap:wrap;align-items:end">
  <div><label style="color:var(--text-dim);font-size:0.75em;display:block;margin-bottom:4px">Gmail Address</label><input id="gmailUser" style="padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:inherit;font-size:0.85em;min-width:200px" placeholder="you@gmail.com"></div>
  <div><label style="color:var(--text-dim);font-size:0.75em;display:block;margin-bottom:4px">App Password</label><input id="gmailPass" type="password" style="padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:inherit;font-size:0.85em;min-width:200px" placeholder="16-char app password"></div>
  <button class="btn" type="submit">💾 Save</button>
</form>
<p style="color:var(--text-dim);font-size:0.7em;margin-top:6px">Create an App Password at <a href="https://myaccount.google.com/apppasswords" style="color:var(--accent)" target="_blank">Google App Passwords</a></p>

<script>
async function approveUser(id){await fetch('/admin/approve/'+id,{method:'POST'});location.reload()}
async function rejectUser(id){await fetch('/admin/reject/'+id,{method:'POST'});location.reload()}
async function makeAdmin(id){await fetch('/admin/make-admin/'+id,{method:'POST'});location.reload()}
async function deleteUser(id){if(confirm('Delete this user?')){await fetch('/admin/delete/'+id,{method:'POST'});location.reload()}}
async function saveGmail(e){e.preventDefault();const u=document.getElementById('gmailUser').value;const p=document.getElementById('gmailPass').value;await fetch('/admin/gmail',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({gmail_user:u,gmail_app_password:p})});alert('Saved!');location.reload()}
</script></body></html>"""

FORGOT_PW_HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Forgot Password</title>
<style>@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
*{margin:0;padding:0;box-sizing:border-box}:root{--bg:#0a0a0f;--surface:#12121a;--border:#2a2a4a;--primary:#00ff41;--accent:#0ff;--text:#c8c8d0;--text-dim:#666;--error:#ff3355}
body{font-family:'Share Tech Mono',monospace;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center}
.auth-box{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:40px;width:100%;max-width:420px}
.auth-box h1{font-size:1.8em;text-align:center;margin-bottom:20px;background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:3px;text-transform:uppercase}
.auth-box label{display:block;font-size:0.75em;color:var(--text-dim);letter-spacing:1px;text-transform:uppercase;margin-bottom:6px;margin-top:16px}
.auth-box input{width:100%;padding:12px 14px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-family:inherit;font-size:0.9em;outline:none}
.auth-box input:focus{border-color:var(--primary)}.auth-btn{width:100%;padding:14px;margin-top:24px;background:transparent;border:2px solid var(--primary);border-radius:8px;color:var(--primary);font-family:inherit;font-size:1em;font-weight:700;letter-spacing:3px;text-transform:uppercase;cursor:pointer}
.auth-btn:hover{background:rgba(0,255,65,0.08)}.msg{padding:8px;border-radius:4px;font-size:0.8em;text-align:center;margin-top:12px;display:none}
.msg.success{display:block;color:var(--primary);background:rgba(0,255,65,0.08);border:1px solid rgba(0,255,65,0.2)}
.msg.error{display:block;color:var(--error);background:rgba(255,51,85,0.08);border:1px solid rgba(255,51,85,0.2)}
.auth-link{text-align:center;margin-top:20px;font-size:0.8em}.auth-link a{color:var(--accent);text-decoration:none}
</style></head><body><div class="auth-box"><h1>Reset Password</h1>
<div id="msg" class="msg"></div>
<form id="fpForm" onsubmit="return handleForgotPw(event)"><label>Email</label><input type="email" id="email" placeholder="you@example.com" required><button class="auth-btn" type="submit">SEND RESET LINK</button></form>
<div class="auth-link"><a href="/login">← Back to login</a></div></div>
<script>async function handleForgotPw(e){e.preventDefault();const msg=document.getElementById('msg');try{const r=await fetch('/forgot-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.getElementById('email').value})});const d=await r.json();msg.className='msg '+(d.status==='ok'?'success':'error');msg.textContent=d.message||d.error;msg.style.display='block'}catch(err){msg.className='msg error';msg.textContent='Network error';msg.style.display='block'}return false}</script></body></html>"""

RESET_PW_HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Reset Password</title>
<style>@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
*{margin:0;padding:0;box-sizing:border-box}:root{--bg:#0a0a0f;--surface:#12121a;--border:#2a2a4a;--primary:#00ff41;--accent:#0ff;--text:#c8c8d0;--text-dim:#666;--error:#ff3355}
body{font-family:'Share Tech Mono',monospace;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center}
.auth-box{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:40px;width:100%;max-width:420px}
.auth-box h1{font-size:1.8em;text-align:center;margin-bottom:20px;background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:3px;text-transform:uppercase}
.auth-box label{display:block;font-size:0.75em;color:var(--text-dim);letter-spacing:1px;text-transform:uppercase;margin-bottom:6px;margin-top:16px}
.auth-box input{width:100%;padding:12px 14px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-family:inherit;font-size:0.9em;outline:none}
.auth-box input:focus{border-color:var(--primary)}.auth-btn{width:100%;padding:14px;margin-top:24px;background:transparent;border:2px solid var(--primary);border-radius:8px;color:var(--primary);font-family:inherit;font-size:1em;font-weight:700;letter-spacing:3px;text-transform:uppercase;cursor:pointer}
.auth-btn:hover{background:rgba(0,255,65,0.08)}.msg{padding:8px;border-radius:4px;font-size:0.8em;text-align:center;margin-top:12px;display:none}
.msg.success{display:block;color:var(--primary);background:rgba(0,255,65,0.08);border:1px solid rgba(0,255,65,0.2)}
.msg.error{display:block;color:var(--error);background:rgba(255,51,85,0.08);border:1px solid rgba(255,51,85,0.2)}
</style></head><body><div class="auth-box"><h1>Set New Password</h1>
<div id="msg" class="msg">{{ msg|safe }}</div>
<form id="rpForm" onsubmit="return handleResetPw(event)"><label>New Password</label><input type="password" id="password" placeholder="At least 6 characters" required minlength="6"><button class="auth-btn" type="submit">RESET PASSWORD</button></form></div>
<script>async function handleResetPw(e){e.preventDefault();const msg=document.getElementById('msg');try{const r=await fetch(window.location.pathname,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:document.getElementById('password').value})});const d=await r.json();msg.className='msg '+(d.status==='ok'?'success':'error');msg.textContent=d.message||d.error;msg.style.display='block'}catch(err){msg.className='msg error';msg.textContent='Network error';msg.style.display='block'}return false}</script></body></html>"""

CHANGE_PW_HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Change Password</title>
<style>@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
*{margin:0;padding:0;box-sizing:border-box}:root{--bg:#0a0a0f;--surface:#12121a;--border:#2a2a4a;--primary:#00ff41;--accent:#0ff;--text:#c8c8d0;--text-dim:#666;--error:#ff3355}
body{font-family:'Share Tech Mono',monospace;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center}
.auth-box{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:40px;width:100%;max-width:420px}
.auth-box h1{font-size:1.8em;text-align:center;margin-bottom:20px;background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:3px;text-transform:uppercase}
.auth-box label{display:block;font-size:0.75em;color:var(--text-dim);letter-spacing:1px;text-transform:uppercase;margin-bottom:6px;margin-top:16px}
.auth-box input{width:100%;padding:12px 14px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-family:inherit;font-size:0.9em;outline:none}
.auth-box input:focus{border-color:var(--primary)}.auth-btn{width:100%;padding:14px;margin-top:24px;background:transparent;border:2px solid var(--primary);border-radius:8px;color:var(--primary);font-family:inherit;font-size:1em;font-weight:700;letter-spacing:3px;text-transform:uppercase;cursor:pointer}
.auth-btn:hover{background:rgba(0,255,65,0.08)}.msg{padding:8px;border-radius:4px;font-size:0.8em;text-align:center;margin-top:12px;display:none}
.msg.success{display:block;color:var(--primary);background:rgba(0,255,65,0.08);border:1px solid rgba(0,255,65,0.2)}
.msg.error{display:block;color:var(--error);background:rgba(255,51,85,0.08);border:1px solid rgba(255,51,85,0.2)}
</style></head><body><div class="auth-box"><h1>Change Password</h1><div id="msg" class="msg"></div>
<form id="cpForm" onsubmit="return handleChangePw(event)"><label>Current Password</label><input type="password" id="currentPw" required><label>New Password</label><input type="password" id="newPw" required minlength="6"><label>Confirm New Password</label><input type="password" id="confirmPw" required minlength="6"><button class="auth-btn" type="submit">CHANGE PASSWORD</button></form>
<div style="text-align:center;margin-top:16px"><a href="/" style="color:var(--accent);text-decoration:none;font-size:0.8em">← Back</a></div></div>
<script>async function handleChangePw(e){e.preventDefault();const msg=document.getElementById('msg');const np=document.getElementById('newPw').value;const cp=document.getElementById('confirmPw').value;if(np!==cp){msg.className='msg error';msg.textContent='Passwords do not match';msg.style.display='block';return false}try{const r=await fetch('/change-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_password:document.getElementById('currentPw').value,new_password:np})});const d=await r.json();msg.className='msg '+(d.status==='ok'?'success':'error');msg.textContent=d.message||d.error;msg.style.display='block';if(d.status==='ok')setTimeout(()=>{window.location.href='/'},1500)}catch(err){msg.className='msg error';msg.textContent='Network error';msg.style.display='block'}return false}</script></body></html>"""


# ── Create FastAPI App ────────────────────────────────────────────────────────


def create_fastapi_app(config: AppConfig) -> FastAPI:
    """Create and configure the FastAPI dashboard app."""
    app = FastAPI(title="Job Agent", version="2.0.0")

    # Session middleware (cookie-based, same as Flask)
    # Use a PERSISTENT secret key stored in a file so sessions survive
    # container restarts and are consistent across all workers/replicas.
    # Without this, each worker computes a different key and can't read
    # sessions set by other workers — the #1 cause of login redirect loops.
    stable_secret = os.environ.get("DASHBOARD_SECRET_KEY", "")
    if not stable_secret:
        secret_file = os.path.join(config.data_dir, "secret_key")
        try:
            if os.path.exists(secret_file):
                with open(secret_file) as f:
                    stable_secret = f.read().strip()
                    if stable_secret:
                        logger.info("Loaded persistent session secret from %s", secret_file)
        except Exception:
            pass
        if not stable_secret:
            stable_secret = secrets.token_hex(32)
            try:
                os.makedirs(os.path.dirname(secret_file) or ".", exist_ok=True)
                with open(secret_file, "w") as f:
                    f.write(stable_secret)
                logger.info("Created persistent session secret at %s", secret_file)
            except Exception as e:
                logger.warning("Could not save persistent secret to %s: %s", secret_file, e)
    # On HuggingFace Spaces, the app runs inside an iframe on huggingface.co.
    # Browsers block SameSite=Lax cookies in cross-site iframes, so we must
    # use SameSite=None with Secure=True to allow session cookies to work.
    app.add_middleware(
        SessionMiddleware,
        secret_key=stable_secret,
        session_cookie="jobagent_session",
        max_age=86400,
        same_site="none" if config.is_hf_space else "lax",
        https_only=config.is_hf_space,
    )

    # Trust proxy headers for HF Spaces
    class ProxyHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.headers.get("x-forwarded-proto"):
                request.scope["scheme"] = request.headers["x-forwarded-proto"]
            return await call_next(request)

    app.add_middleware(ProxyHeadersMiddleware)

    global _dashboard_data_dir
    _dashboard_data_dir = config.data_dir
    _ensure_dirs(config.data_dir)
    _init_persistent_data(config)

    # Init DB and admin
    init_db()
    ensure_admin_exists()
    cleanup_old_saved_jobs(days=7)
    try:
        admin_user = db_get_user_by_email(DEFAULT_ADMIN_EMAIL)
        if (
            admin_user
            and admin_user.get("gmail_user")
            and admin_user.get("gmail_app_password")
        ):
            set_gmail_credentials(
                admin_user["gmail_user"], admin_user["gmail_app_password"]
            )
    except Exception as e:
        logger.warning("Could not load Gmail credentials: %s", e)

    tracker = ApplicationTracker(data_dir=config.data_dir)

    # ── Auth dependency helpers ───────────────────────────────────────────────

    def _auth_guard(request: Request) -> Optional[JSONResponse]:
        if not request.session.get("user_id"):
            return JSONResponse({"error": "Authentication required"}, 401)
        return None

    def _admin_guard(request: Request) -> Optional[JSONResponse]:
        err = _auth_guard(request)
        if err:
            return err
        if request.session.get("user_role") != "admin":
            return JSONResponse({"error": "Admin required"}, 403)
        return None

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/api/db-status")
    async def db_status(request: Request):
        """Return database connection info so you can verify PostgreSQL is active.
        Visit /api/db-status to confirm your Neon DB is connected.
        """
        if not request.session.get("user_id"):
            return JSONResponse({"error": "Auth required"}, 401)
        info = get_db_connection_info()
        info["status"] = "connected"
        return info

    # ── Debug: Cookie / Session Inspector ──
    @app.get("/debug/cookie")
    async def debug_cookie(request: Request, key: str = ""):
        """Diagnostic endpoint to inspect session cookie state.
        Visit /debug/cookie?key=debug to check if your session cookie is
        being sent and read correctly. Useful for debugging login redirect loops.
        Requires a simple shared secret (default: "debug", override via DEBUG_KEY env var).
        """
        expected_key = os.environ.get("DEBUG_KEY", "debug")
        if key != expected_key:
            return JSONResponse(
                {"error": "Missing or invalid debug key. Use ?key=debug"}, 403
            )

        # Read the raw cookie header and check for our session cookie
        raw_cookie = request.headers.get("cookie", "")
        has_session_cookie = any(
            c.strip().startswith("jobagent_session=")
            for c in raw_cookie.split(";") if "=" in c
        )

        user_id = request.session.get("user_id")
        user_name = request.session.get("user_name")
        user_role = request.session.get("user_role")
        user_email = request.session.get("user_email")

        # Request metadata
        scheme = request.scope.get("scheme", "unknown")
        host = request.headers.get("host", "")
        x_forwarded_proto = request.headers.get("x-forwarded-proto", "")
        x_forwarded_host = request.headers.get("x-forwarded-host", "")
        client_ip = request.client.host if request.client else ""

        # Environment
        is_hf = config.is_hf_space
        data_dir = config.data_dir

        return {
            "session": {
                "cookie_present": has_session_cookie,
                "user_id": user_id,
                "user_name": user_name,
                "user_role": user_role,
                "user_email": user_email,
                "authenticated": user_id is not None,
            },
            "request": {
                "scheme": scheme,
                "host": host,
                "client_ip": client_ip,
                "x_forwarded_proto": x_forwarded_proto,
                "x_forwarded_host": x_forwarded_host,
            },
            "environment": {
                "is_hf_space": is_hf,
                "data_dir": data_dir,
                "session_cookie_name": "jobagent_session",
            },
        }

    # ── Login ──
    @app.get("/login")
    async def login_get(request: Request):
        if request.session.get("user_id"):
            return RedirectResponse(url="/", status_code=302)
        error = request.query_params.get("error", "")
        signup_ok = request.query_params.get("signup", "")
        error_messages = {
            "pending": '<div style="text-align:center;margin-bottom:16px;padding:12px;background:rgba(255,170,0,0.1);border:1px solid rgba(255,170,0,0.3);border-radius:8px;color:#ffaa00;font-size:0.85em">Your account is pending admin approval.</div>',
            "invalid": '<div style="text-align:center;margin-bottom:16px;padding:12px;background:rgba(255,51,85,0.08);border:1px solid rgba(255,51,85,0.2);border-radius:8px;color:#ff3355;font-size:0.85em">Invalid email or password.</div>',
            "empty": '<div style="text-align:center;margin-bottom:16px;padding:12px;background:rgba(255,51,85,0.08);border:1px solid rgba(255,51,85,0.2);border-radius:8px;color:#ff3355;font-size:0.85em">Email and password are required.</div>',
        }
        error_msg = error_messages.get(error, "")
        if not error_msg and signup_ok == "ok":
            error_msg = '<div style="text-align:center;margin-bottom:16px;padding:12px;background:rgba(0,255,65,0.08);border:1px solid rgba(0,255,65,0.2);border-radius:8px;color:#00ff41;font-size:0.85em">Account created! Please wait for admin approval, then sign in.</div>'
        html = (
            _LOGIN_HTML.replace("{pending_msg}", error_msg)
            if _LOGIN_HTML
            else "LOGIN_HTML not loaded"
        )
        return HTMLResponse(html)

    @app.post("/login")
    async def login_post(request: Request):
        ensure_admin_exists()
        cleanup_old_saved_jobs(days=7)
        # Accept both JSON (JS fetch) and form-encoded (no-JS fallback) POST bodies.
        # The native <form> submit sends application/x-www-form-urlencoded.
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            data = await request.json()
        else:
            form = await request.form()
            data = {"email": form.get("email", ""), "password": form.get("password", "")}
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        client_ip = request.client.host if request.client else ""
        user_agent = request.headers.get("user-agent", "")
        if not email or not password:
            logger.warning(f"Login attempt with empty fields from {client_ip}")
            if "application/json" in content_type:
                return JSONResponse(
                    {"status": "error", "error": "Email and password required"}, 400
                )
            return RedirectResponse(url="/login?error=empty", status_code=302)
        logger.info(f"Login attempt: {email} from {client_ip}")
        result = login_user_fastapi(request, email, password)
        if isinstance(result, dict) and result.get("error"):
            code = 403 if result["error"] == "pending" else 403
            logger.warning(f"Login blocked for {email}: {result['error']}")
            log_login_attempt(
                email=email,
                success=False,
                details=result["error"],
                ip_address=client_ip,
                user_agent=user_agent,
            )
            if "application/json" in content_type:
                return JSONResponse(
                    {"status": "error", "error": result.get("message", result["error"])},
                    code,
                )
            error_param = "pending" if result["error"] == "pending" else "invalid"
            return RedirectResponse(url=f"/login?error={error_param}", status_code=302)
        if not result:
            logger.warning(f"Login failed for {email}: invalid credentials")
            log_login_attempt(
                email=email,
                success=False,
                details="invalid_credentials",
                ip_address=client_ip,
                user_agent=user_agent,
            )
            if "application/json" in content_type:
                return JSONResponse(
                    {"status": "error", "error": "Invalid email or password"}, 401
                )
            return RedirectResponse(url="/login?error=invalid", status_code=302)
        logger.info(f"Login successful: {email} (user_id={result.get('id')})")
        log_login_attempt(
            email=email,
            success=True,
            user_id=result.get("id"),
            ip_address=client_ip,
            user_agent=user_agent,
        )
        uid = result.get("id")
        if uid:
            log_activity(
                uid, email, "login", details=f"User {result['name']} logged in"
            )
        must_change = needs_password_change(uid) if uid else False
        if "application/json" in content_type:
            return {
                "status": "ok",
                "user": {"name": result["name"], "email": result["email"]},
                "must_change_password": must_change,
            }
        # No-JS fallback: traditional form submit → redirect to dashboard
        return RedirectResponse(url="/", status_code=302)

    # ── Signup ──
    @app.get("/signup")
    async def signup_get(request: Request):
        if request.session.get("user_id"):
            return RedirectResponse(url="/", status_code=302)
        error = request.query_params.get("error", "")
        error_messages = {
            "empty": '<div style="text-align:center;margin-bottom:16px;padding:12px;background:rgba(255,51,85,0.08);border:1px solid rgba(255,51,85,0.2);border-radius:8px;color:#ff3355;font-size:0.85em">All fields are required.</div>',
            "short_password": '<div style="text-align:center;margin-bottom:16px;padding:12px;background:rgba(255,51,85,0.08);border:1px solid rgba(255,51,85,0.2);border-radius:8px;color:#ff3355;font-size:0.85em">Password must be at least 6 characters.</div>',
            "email_taken": '<div style="text-align:center;margin-bottom:16px;padding:12px;background:rgba(255,51,85,0.08);border:1px solid rgba(255,51,85,0.2);border-radius:8px;color:#ff3355;font-size:0.85em">An account with that email already exists.</div>',
        }
        error_msg = error_messages.get(error, "")
        html = _SIGNUP_HTML if _SIGNUP_HTML else "SIGNUP_HTML not loaded"
        if error_msg:
            html = html.replace(
                '<form id="signupForm"',
                error_msg + '<form id="signupForm"',
            )
        return HTMLResponse(html)

    @app.post("/signup")
    async def signup_post(request: Request):
        # Accept both JSON (JS fetch) and form-encoded (no-JS fallback) POST bodies.
        # The native <form> submit sends application/x-www-form-urlencoded.
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            data = await request.json()
        else:
            form = await request.form()
            data = {"name": form.get("name", ""), "email": form.get("email", ""), "password": form.get("password", "")}
        name = data.get("name", "").strip()
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        if not name or not email or not password:
            if "application/json" in content_type:
                return JSONResponse(
                    {"status": "error", "error": "All fields required"}, 400
                )
            return RedirectResponse(url="/signup?error=empty", status_code=302)
        if len(password) < 6:
            if "application/json" in content_type:
                return JSONResponse(
                    {"status": "error", "error": "Password must be at least 6 characters"},
                    400,
                )
            return RedirectResponse(url="/signup?error=short_password", status_code=302)
        user = register_user_fn(email, password, name)
        if not user:
            if "application/json" in content_type:
                return JSONResponse(
                    {"status": "error", "error": "Email already registered"}, 409
                )
            return RedirectResponse(url="/signup?error=email_taken", status_code=302)
        if "application/json" in content_type:
            return {
                "status": "pending_approval",
                "message": "Account created! Please wait for admin approval.",
            }
        # No-JS fallback: traditional form submit → redirect to login with success message
        return RedirectResponse(url="/login?signup=ok", status_code=302)

    # ── Logout ──
    @app.post("/logout")
    async def logout(request: Request):
        logout_user_fastapi(request)
        return {"status": "ok"}

    # ── Index ──
    @app.get("/")
    async def index(request: Request):
        user_id = request.session.get("user_id")
        if not user_id:
            return RedirectResponse(url="/login", status_code=302)
        user = get_user_by_id(user_id)
        if not user:
            logout_user_fastapi(request)
            return RedirectResponse(url="/login", status_code=302)
        html = _GUI_HTML if _GUI_HTML else "GUI_HTML not loaded"
        rendered = _render_template(html, user=user)
        return HTMLResponse(rendered)

    # ── Change Password ──
    @app.get("/change-password")
    async def change_password_get(request: Request):
        if not request.session.get("user_id"):
            return RedirectResponse(url="/login", status_code=302)
        return HTMLResponse(CHANGE_PW_HTML)

    @app.post("/change-password")
    async def change_password_post(request: Request):
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"status": "error", "error": "Not logged in"}, 401)
        data = await request.json()
        current = data.get("current_password", "")
        new_pw = data.get("new_password", "")
        if len(new_pw) < 6:
            return JSONResponse(
                {
                    "status": "error",
                    "error": "New password must be at least 6 characters",
                },
                400,
            )
        user = get_user_by_id(user_id)
        if not user:
            return JSONResponse({"status": "error", "error": "User not found"}, 404)
        from .auth import verify_password

        if not verify_password(current, user["password_hash"]):
            return JSONResponse(
                {"status": "error", "error": "Current password is incorrect"}, 401
            )
        new_hash = hash_password(new_pw)
        update_user_password(user_id, new_hash)
        mark_password_changed(user_id)
        return {"status": "ok", "message": "Password changed successfully!"}

    # ── Forgot Password ──
    @app.get("/forgot-password")
    async def forgot_password_get():
        return HTMLResponse(FORGOT_PW_HTML)

    @app.post("/forgot-password")
    async def forgot_password_post(request: Request):
        data = await request.json()
        email = data.get("email", "").strip().lower()
        user = db_get_user_by_email(email)
        if not user:
            return {
                "status": "ok",
                "message": "If that email exists, a reset link has been sent.",
            }
        token = create_password_reset_token(user["id"])
        try:
            sent = send_password_reset_email(email, token)
        except Exception:
            sent = False
        if sent:
            return {"status": "ok", "message": "Reset link sent! Check your email."}
        return {
            "status": "ok",
            "message": f"Reset token (email not configured): {token}",
        }

    # ── Reset Password ──
    @app.get("/reset-password/{token}")
    async def reset_password_get(token: str):
        user = get_user_by_reset_token(token)
        if not user:
            html = RESET_PW_HTML.replace(
                "{{ msg|safe }}",
                '<div class="msg error" style="display:block">Invalid or expired reset token.</div>',
            )
            return HTMLResponse(html)
        html = RESET_PW_HTML.replace("{{ msg|safe }}", "")
        return HTMLResponse(html)

    @app.post("/reset-password/{token}")
    async def reset_password_post(token: str, request: Request):
        data = await request.json()
        new_pw = data.get("password", "")
        if len(new_pw) < 6:
            return JSONResponse(
                {"status": "error", "error": "Password must be at least 6 characters"},
                400,
            )
        user = get_user_by_reset_token(token)
        if not user:
            return JSONResponse(
                {"status": "error", "error": "Invalid or expired reset token."}, 400
            )
        new_hash = hash_password(new_pw)
        # Update directly via database module and verify the change took effect
        conn = get_db()
        cur = _cursor(conn)
        cur.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user["id"])
        )
        conn.commit()
        # Verify the update actually persisted
        cur.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],))
        actual = cur.fetchone()
        if actual and actual["password_hash"] == new_hash:
            use_password_reset_token(token)
            return {"status": "ok", "message": "Password reset! You can now log in."}
        return JSONResponse(
            {"status": "error", "error": "Failed to update password"}, 500
        )

    # ── Upload CV ──
    @app.post("/upload")
    async def upload_cv(request: Request, file: UploadFile = File(...)):
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse(
                {"status": "error", "error": "Authentication required"}, 401
            )
        if not file.filename or not file.filename.endswith(".pdf"):
            return JSONResponse(
                {"status": "error", "error": "Only PDF files are supported"}, 400
            )
        global _uploaded_filename
        _uploaded_filename = file.filename
        save_path = Path(_dashboard_data_dir) / "logs" / f"resume_{user_id}.pdf"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        content = await file.read()
        save_path.write_bytes(content)
        return {"status": "ok", "filename": file.filename}

    # ── Set Region ──
    @app.post("/set-region")
    async def set_region(request: Request):
        data = await request.json()
        region = data.get("region", "Remote")
        global _selected_region
        _selected_region = region
        return {"status": "ok", "region": region}

    # ── Stop Agent ──
    @app.post("/stop")
    async def stop_agent(request: Request):
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"status": "error", "error": "Auth required"}, 401)
        global _stop_requested
        _stop_requested = True
        if _run_process:
            _run_process.terminate()
        return {"status": "ok"}

    # ── Run Agent (SSE) ──
    @app.get("/run")
    async def run_agent_sse(request: Request):
        global _output_queue, _run_thread, _run_complete, _stop_requested, _run_returncode
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "Auth required"}, 401)
        _output_queue = queue.Queue()
        _run_complete = False
        _stop_requested = False
        _run_returncode = None

        def runner():
            _run_agent_in_thread(os.getcwd(), "", user_id)

        _run_thread = threading.Thread(target=runner, daemon=True)
        _run_thread.start()

        def event_stream():
            while True:
                try:
                    line = _output_queue.get(timeout=1.0)
                    yield f"data: {line}\n\n"
                except queue.Empty:
                    if _run_complete:
                        break
                    yield ": heartbeat\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Status ──
    @app.get("/status")
    async def status(request: Request):
        return {"selected_region": _selected_region, "agent": _agent_status()}

    # ── Results ──
    @app.get("/results")
    async def results(request: Request):
        user_id = request.session.get("user_id")
        if not user_id:
            return {"files": [], "stats": {}}
        from .utils import _ensure_dirs

        output_dir = Path(_dashboard_data_dir)
        files = [
            f.name
            for f in sorted(output_dir.glob("jobs_*.docx"))
            + sorted(output_dir.glob("cv_*.pdf"))
        ]
        files = files[-8:]  # Last 8 files
        stats = get_stats(user_id)
        return {"files": files, "stats": stats}

    # ── Download ──
    @app.get("/download/{filename:path}")
    async def download_file(filename: str):
        path = Path(_dashboard_data_dir) / filename
        if path.exists():
            return FileResponse(path, filename=filename)
        return JSONResponse({"error": "File not found"}, 404)

    # ── API: History ──
    @app.get("/api/history")
    async def api_history(request: Request):
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "Auth required"}, 401)
        jobs = get_user_applications(user_id)
        return {"jobs": jobs}

    # ── API: Applied ──
    @app.get("/api/applied")
    async def api_applied(request: Request):
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "Auth required"}, 401)
        urls = get_applied_urls(user_id)
        return {"applied": urls}

    # ── API: Saved ──
    @app.get("/api/saved")
    async def api_saved(request: Request):
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "Auth required"}, 401)
        ids = get_saved_application_ids(user_id)
        return {"saved": ids}

    # ── API: Mark Applied ──
    @app.post("/api/mark-applied")
    async def api_mark_applied(request: Request):
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "Auth required"}, 401)
        data = await request.json()
        url = data.get("url", "")
        if url:
            db_mark_applied(user_id, url)
        return {"status": "ok"}

    # ── API: Save Job ──
    @app.post("/api/save-job")
    async def api_save_job(request: Request):
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "Auth required"}, 401)
        data = await request.json()
        app_id = data.get("application_id")
        if app_id:
            db_save_job(user_id, app_id)
            return {"status": "ok", "application_id": app_id}
        # Full job data
        job_data = data.get("job", {})
        app_id = save_job_with_data(user_id, data, job_data)
        return {"status": "ok", "application_id": app_id}

    # ── API: Unsave Job ──
    @app.post("/api/unsave-job")
    async def api_unsave_job(request: Request):
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "Auth required"}, 401)
        data = await request.json()
        app_id = data.get("application_id")
        if app_id:
            db_unsave_job(user_id, app_id)
        return {"status": "ok"}

    # ── API: Clear History ──
    @app.post("/api/clear-history")
    async def api_clear_history(request: Request):
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "Auth required"}, 401)
        clear_user_applications(user_id)
        return {"status": "ok"}

    # ── API: Feedback ──
    @app.post("/api/feedback")
    async def api_feedback(request: Request):
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "Auth required"}, 401)
        data = await request.json()
        save_feedback(
            user_id,
            data.get("application_id", 0),
            data.get("rating", 0),
            data.get("title", ""),
            data.get("company", ""),
        )
        return {"status": "ok"}

    @app.get("/api/user-feedback")
    async def api_user_feedback(request: Request):
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "Auth required"}, 401)
        from .database import get_user_feedback

        try:
            fb = get_user_feedback(user_id)
            return {"feedback": fb if fb else []}
        except Exception:
            return {"feedback": []}

    @app.get("/api/my-feedback-stats")
    async def api_my_feedback_stats(request: Request):
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "Auth required"}, 401)
        summary = get_feedback_summary()
        return {
            "total": summary.get("total", 0),
            "thumbs_up": summary.get("up", 0),
            "thumbs_down": summary.get("down", 0),
            "positivity_rate": summary.get("rate", 0),
        }

    # ── Admin Panel ──
    @app.get("/admin")
    async def admin_panel(request: Request):
        if (
            not request.session.get("user_id")
            or request.session.get("user_role") != "admin"
        ):
            return RedirectResponse(url="/login", status_code=302)
        pending = get_pending_users()
        all_users = get_all_users()
        stats_data = {
            "total_users": len(all_users),
            "active_users": get_active_users_count(),
            "pending_users": len(pending),
            "total_apps": len(get_all_applications()),
        }
        msg = request.query_params.get("msg", "")
        msg_type = request.query_params.get("type", "")
        return HTMLResponse(
            _render_template(
                ADMIN_HTML,
                stats=stats_data,
                pending_users=pending,
                all_users=all_users,
                msg=msg,
                msg_type=msg_type,
            )
        )

    @app.post("/admin/approve/{uid}")
    async def admin_approve(uid: int, request: Request):
        err = _admin_guard(request)
        if err:
            return err
        approve_user(uid)
        return {"status": "ok"}

    @app.post("/admin/reject/{uid}")
    async def admin_reject(uid: int, request: Request):
        err = _admin_guard(request)
        if err:
            return err
        reject_user(uid)
        return {"status": "ok"}

    @app.post("/admin/make-admin/{uid}")
    async def admin_make_admin(uid: int, request: Request):
        err = _admin_guard(request)
        if err:
            return err
        update_user_role(uid, "admin")
        return {"status": "ok"}

    @app.post("/admin/delete/{uid}")
    async def admin_delete_user(uid: int, request: Request):
        err = _admin_guard(request)
        if err:
            return err
        delete_user(uid)
        return {"status": "ok"}

    @app.post("/admin/gmail")
    async def admin_gmail(request: Request):
        err = _admin_guard(request)
        if err:
            return err
        data = await request.json()
        user = data.get("gmail_user", "")
        pw = data.get("gmail_app_password", "")
        set_gmail_credentials(user, pw)
        update_gmail_credentials(DEFAULT_ADMIN_EMAIL, user, pw)
        return {"status": "ok"}

    # ── Google OAuth ──
    def _google_redirect_uri(request: Request) -> str:
        """Build the Google OAuth redirect URI correctly for any environment.

        On HuggingFace Spaces, Starlette's request.url_for returns an internal
        http:// URL (e.g. http://container:7860/login/google/callback).
        We must force https:// for Google to accept it, and use the external
        hostname if available via X-Forwarded-Host.
        """
        raw_uri = str(request.url_for("google_callback"))
        # Starlette returns absolute URLs. On HF Spaces / behind proxies,
        # force https and use the external hostname from headers.
        if raw_uri.startswith("http://") and (
            config.is_hf_space or request.headers.get("x-forwarded-proto") == "https"
        ):
            raw_uri = raw_uri.replace("http://", "https://", 1)
        # If there's an X-Forwarded-Host, use that hostname instead of the internal one
        fwd_host = request.headers.get("x-forwarded-host", "")
        if fwd_host:
            parsed = urlparse(raw_uri)
            parsed = parsed._replace(netloc=fwd_host)
            raw_uri = urlunparse(parsed)
        return raw_uri

    @app.get("/login/google")
    async def google_login(request: Request):
        google_client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        if not google_client_id:
            logger.warning("Google OAuth: GOOGLE_CLIENT_ID not set")
            return RedirectResponse(
                url="/login?error=google_not_configured", status_code=302
            )
        redirect_uri = _google_redirect_uri(request)
        logger.info(f"Google OAuth: redirect_uri={redirect_uri}")
        params = {
            "client_id": google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        return RedirectResponse(url=auth_url, status_code=302)

    @app.get("/login/google/callback")
    async def google_callback(request: Request):
        code = request.query_params.get("code")
        error = request.query_params.get("error")
        if error:
            logger.warning(f"Google OAuth callback error: {error}")
            return RedirectResponse(url=f"/login?error=google_{error}", status_code=302)
        if not code:
            logger.warning("Google OAuth callback: no code received")
            return RedirectResponse(url="/login?error=google_no_code", status_code=302)

        google_client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
        if not google_client_id or not google_client_secret:
            logger.error("Google OAuth: client credentials not configured")
            return RedirectResponse(
                url="/login?error=google_not_configured", status_code=302
            )

        redirect_uri = _google_redirect_uri(request)
        logger.info(
            f"Google OAuth callback: exchanging code, redirect_uri={redirect_uri}"
        )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                token_resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "code": code,
                        "client_id": google_client_id,
                        "client_secret": google_client_secret,
                        "redirect_uri": redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
                token_data = token_resp.json()
                if "error" in token_data:
                    logger.error(f"Google token exchange failed: {token_data}")
                    return RedirectResponse(
                        url="/login?error=google_token", status_code=302
                    )
                access_token = token_data.get("access_token")
                if not access_token:
                    logger.error(
                        f"Google token response missing access_token: {token_data}"
                    )
                    return RedirectResponse(
                        url="/login?error=google_token", status_code=302
                    )
                user_resp = await client.get(
                    "https://www.googleapis.com/oauth2/v3/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                userinfo = user_resp.json()
                if "error" in userinfo:
                    logger.error(f"Google userinfo failed: {userinfo}")
                    return RedirectResponse(
                        url="/login?error=google_userinfo", status_code=302
                    )
        except httpx.TimeoutException:
            logger.exception("Google OAuth token exchange timed out")
            return RedirectResponse(url="/login?error=google_timeout", status_code=302)
        except Exception:
            logger.exception("Google OAuth token exchange failed")
            return RedirectResponse(url="/login?error=google_failed", status_code=302)

        email = userinfo.get("email", "").lower()
        name = userinfo.get("name", "Google User")
        if not email:
            logger.error("Google OAuth: no email in userinfo")
            return RedirectResponse(url="/login?error=google_no_email", status_code=302)

        logger.info(f"Google OAuth: user {email} ({name}) authenticated")

        # Find or create user
        user = db_get_user_by_email(email)
        if not user:
            # Create new user — Google-authenticated users get auto-approved
            user = register_user_fn(email, os.urandom(12).hex(), name)
            if user and user.get("status") == "pending":
                approve_user(user["id"])
                logger.info(f"Google OAuth: auto-approved new user {email}")
            user = db_get_user_by_email(email)
        elif user.get("status") == "pending":
            # Existing pending user signing in via Google — auto-approve
            approve_user(user["id"])
            user = db_get_user_by_email(email)
            logger.info(f"Google OAuth: auto-approved pending user {email}")

        if not user:
            logger.error(f"Google OAuth: failed to find/create user {email}")
            return RedirectResponse(url="/login?error=google_failed", status_code=302)

        # Set session
        request.session["user_id"] = user["id"]
        request.session["user_name"] = user["name"]
        request.session["user_role"] = user.get("role", "user")
        request.session["user_email"] = user["email"]

        log_login_attempt(
            email=email,
            success=True,
            user_id=user["id"],
            details="Google OAuth",
            ip_address=request.client.host if request.client else "",
            user_agent=request.headers.get("user-agent", ""),
        )
        log_activity(
            user["id"],
            email,
            "login",
            details=f"User {user['name']} logged in via Google",
        )

        return RedirectResponse(url="/", status_code=302)

    return app


# ── Runner ────────────────────────────────────────────────────────────────────


def run_fastapi_dashboard(config: AppConfig):
    """Start the FastAPI dashboard via uvicorn."""
    import uvicorn

    app = create_fastapi_app(config)
    host = config.dashboard_host
    port = config.dashboard_port
    logger.info(f"Starting FastAPI dashboard on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
