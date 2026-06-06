"""
Web GUI for Job Agent.
Provides a cyberpunk-styled interface with authentication, CV upload,
Run Agent button, real-time streaming output, results display, and admin panel.
"""

import json
import logging
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template_string, request, Response, send_file, redirect, url_for, session

from .config import AppConfig
from .tracker import ApplicationTracker
from .utils import _ensure_dirs
from .auth import (
    login_user,
    logout_user,
    register_user,
    get_current_user,
    require_login,
    require_admin,
    is_admin,
    get_user_id,
    ensure_admin_exists,
    hash_password,
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
)
from .notifier import notify_approved, notify_rejected, send_password_reset_email
from .database import (
    init_db,
    get_user_applications,
    get_all_applications,
    get_applied_urls,
    mark_applied,
    save_job as db_save_job,
    unsave_job as db_unsave_job,
    get_saved_application_ids,
    get_all_users,
    get_pending_users,
    approve_user,
    reject_user,
    get_stats,
    clear_user_applications,
    clear_all_applications,
    save_application,
    save_job_with_data,
    get_saved_applications,
    cleanup_old_saved_jobs,
    update_user_role,
    delete_user,
    get_user_by_email as db_get_user_by_email,
    get_user_by_id,
    update_user_password,
    create_password_reset_token,
    get_user_by_reset_token,
    use_password_reset_token,
    cleanup_expired_tokens,
    log_login_attempt,
    get_login_logs,
)

logger = logging.getLogger(__name__)

# ── Background runner ─────────────────────────────────────────────────────────

_output_queue: Optional[queue.Queue] = None
_run_process: Optional[subprocess.Popen] = None
_run_thread: Optional[threading.Thread] = None
_run_complete = False
_stop_requested = False
_run_returncode: Optional[int] = None
_gui_api_key: str = ""  # API key entered via the browser GUI
_uploaded_filename: str = "resume.pdf"  # Actual uploaded CV filename
_dashboard_data_dir: str = "."  # Configurable data directory
_selected_region: str = "Remote"  # Country/region selected by user

# ── Applied Jobs Tracking ─────────────────────────────────────────────────────

def _applied_path():
    return Path(_dashboard_data_dir) / "logs" / "applied.json"

def _load_applied() -> set:
    """Load set of applied job URLs."""
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
    """Save set of applied job URLs."""
    path = _applied_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(applied), indent=2))

def _mark_applied(job_url: str) -> bool:
    """Mark a job URL as applied. Returns True if newly marked."""
    applied = _load_applied()
    if job_url in applied:
        return False
    applied.add(job_url)
    _save_applied(applied)
    return True


def _run_agent_in_thread(cwd: str, api_key: str = "", user_id: Optional[int] = None):
    """Run the agent as a subprocess and push output lines to a queue.
    user_id is captured in the Flask request context and passed here to avoid
    accessing Flask session from a background thread (which won't have it).
    """
    global _output_queue, _run_process, _run_complete, _run_returncode, _stop_requested

    env = os.environ.copy()
    # Use the API key from the config (passed from the dashboard app)
    if not api_key:
        api_key = env.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        _output_queue.put("[ERROR] ANTHROPIC_API_KEY not set. Cannot run agent.\n")
        _output_queue.put("[ERROR] Set the ANTHROPIC_API_KEY environment variable and restart the dashboard.\n")
        _run_complete = True
        return
    # Ensure the subprocess has the key
    env["ANTHROPIC_API_KEY"] = api_key
    # Pass the selected region to the agent
    env["AGENT_LOCATION"] = _selected_region
    # Pass the user ID so the tracker saves per-user files
    if user_id:
        env["USER_ID"] = str(user_id)

    cmd = [sys.executable, "-m", "agent", "run", "--headless"]

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
            _output_queue.put(f"\n[SYSTEM] Agent finished with exit code {process.returncode}\n")
        _run_complete = True

    except Exception as e:
        if _output_queue is not None:
            _output_queue.put(f"\n[ERROR] Failed to run agent: {e}\n")
        _run_complete = True


def _agent_status():
    """Return current agent run status."""
    return {
        "running": _run_thread is not None and _run_thread.is_alive(),
        "complete": _run_complete,
        "returncode": _run_returncode,
    }


# ── Dashboard App ─────────────────────────────────────────────────────────────

def create_dashboard_app(config: AppConfig):
    """Create and configure the GUI Flask app."""
    try:
        from flask import Flask, jsonify, render_template_string, request, Response, send_file
    except ImportError:
        logger.error("Flask not installed. Run: pip install flask")
        return None

    app = Flask(__name__)
    app.config['JSON_SORT_KEYS'] = False
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max upload
    app.secret_key = os.urandom(24).hex()  # For Flask sessions

    global _dashboard_data_dir
    _dashboard_data_dir = config.data_dir

    # Ensure data directories exist
    _ensure_dirs(config.data_dir)

    # On HF Spaces, copy initial files from project to /data if needed
    _init_persistent_data(config)

    # Initialize database and ensure admin user exists
    init_db()
    ensure_admin_exists()
    # Clean up expired saved jobs (older than 7 days)
    cleanup_old_saved_jobs(days=7)

    tracker = ApplicationTracker(data_dir=config.data_dir)

    # ── Login / Signup Page ──

    LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Agent - Login</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Inter:wght@400;600;700&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root {
    --bg: #0a0a0f;
    --surface: #12121a;
    --surface2: #1a1a2e;
    --border: #2a2a4a;
    --primary: #00ff41;
    --accent: #0ff;
    --text: #c8c8d0;
    --text-dim: #666;
    --error: #ff3355;
  }
  body {
    font-family: 'Share Tech Mono', monospace;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .auth-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 40px;
    width: 100%;
    max-width: 420px;
    box-shadow: 0 0 60px rgba(0,255,65,0.05);
  }
  .auth-box h1 {
    font-size: 1.8em;
    text-align: center;
    margin-bottom: 8px;
    background: linear-gradient(135deg, var(--primary), var(--accent));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: 3px;
    text-transform: uppercase;
  }
  .auth-box .subtitle {
    text-align: center;
    color: var(--text-dim);
    font-size: 0.8em;
    margin-bottom: 30px;
    letter-spacing: 1px;
  }
  .auth-box label {
    display: block;
    font-size: 0.75em;
    color: var(--text-dim);
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 6px;
    margin-top: 16px;
  }
  .auth-box input {
    width: 100%;
    padding: 12px 14px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.9em;
    outline: none;
    transition: border-color 0.2s;
  }
  .auth-box input:focus {
    border-color: var(--primary);
    box-shadow: 0 0 10px rgba(0,255,65,0.15);
  }
  .auth-btn {
    width: 100%;
    padding: 14px;
    margin-top: 24px;
    background: transparent;
    border: 2px solid var(--primary);
    border-radius: 8px;
    color: var(--primary);
    font-family: 'Share Tech Mono', monospace;
    font-size: 1em;
    font-weight: 700;
    letter-spacing: 3px;
    text-transform: uppercase;
    cursor: pointer;
    transition: all 0.3s;
  }
  .auth-btn:hover {
    background: rgba(0,255,65,0.08);
    box-shadow: 0 0 20px rgba(0,255,65,0.2);
  }
  .auth-error {
    color: var(--error);
    font-size: 0.8em;
    text-align: center;
    margin-top: 12px;
    padding: 8px;
    background: rgba(255,51,85,0.08);
    border: 1px solid rgba(255,51,85,0.2);
    border-radius: 4px;
    display: none;
  }
  .auth-link {
    text-align: center;
    margin-top: 20px;
    font-size: 0.8em;
    color: var(--text-dim);
  }
  .auth-link a {
    color: var(--accent);
    text-decoration: none;
  }
  .auth-link a:hover {
    text-decoration: underline;
  }
  .auth-msg {
    color: var(--primary);
    font-size: 0.8em;
    text-align: center;
    margin-top: 12px;
    display: none;
  }

  /* ── Hacking Animation Overlay ── */
  .hack-overlay {
    display: none;
    position: fixed;
    top: 0; left: 0;
    width: 100%; height: 100%;
    background: rgba(0, 0, 0, 0.92);
    z-index: 9999;
    font-family: 'Share Tech Mono', monospace;
    overflow: hidden;
  }
  .hack-overlay.active {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }
  #hackCanvas {
    position: absolute;
    top: 0; left: 0;
    width: 100%; height: 100%;
    z-index: -1;
    opacity: 0.15;
  }
  .hack-terminal {
    background: rgba(0, 20, 0, 0.6);
    border: 1px solid var(--primary);
    border-radius: 8px;
    padding: 24px;
    width: 90%;
    max-width: 600px;
    max-height: 70vh;
    overflow: hidden;
    box-shadow: 0 0 40px rgba(0, 255, 65, 0.15);
    position: relative;
  }
  .hack-terminal-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-bottom: 12px;
    border-bottom: 1px solid rgba(0, 255, 65, 0.2);
    margin-bottom: 12px;
  }
  .hack-dot {
    width: 10px; height: 10px;
    border-radius: 50%;
  }
  .hack-dot.red { background: #ff5f56; }
  .hack-dot.yellow { background: #ffbd2e; }
  .hack-dot.green { background: #27c93f; }
  .hack-terminal-title {
    color: var(--text-dim);
    font-size: 0.8em;
    letter-spacing: 2px;
    margin-left: 8px;
  }
  .hack-output {
    font-size: 0.85em;
    line-height: 1.6;
    color: var(--primary);
    min-height: 200px;
    max-height: 50vh;
    overflow-y: auto;
    padding: 4px 0;
  }
  .hack-output .line {
    opacity: 0;
    white-space: pre-wrap;
    word-break: break-all;
    animation: hackFadeIn 0.3s ease forwards;
  }
  .hack-output .line.success { color: var(--primary); }
  .hack-output .line.warning { color: var(--warning); }
  .hack-output .line.error { color: var(--error); }
  .hack-output .line.info { color: var(--accent); }
  .hack-output .line.dim { color: var(--text-dim); }
  .hack-output .line.highlight { color: var(--accent2, #f0f); }
  @keyframes hackFadeIn {
    to { opacity: 1; }
  }
  .hack-progress {
    margin-top: 16px;
    width: 100%;
    height: 4px;
    background: rgba(0, 255, 65, 0.1);
    border-radius: 2px;
    overflow: hidden;
  }
  .hack-progress-bar {
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, var(--primary), var(--accent));
    border-radius: 2px;
    transition: width 0.3s ease;
    box-shadow: 0 0 10px rgba(0, 255, 65, 0.5);
  }
  .hack-cursor {
    display: inline-block;
    width: 8px;
    height: 14px;
    background: var(--primary);
    animation: hackBlink 0.8s step-end infinite;
    margin-left: 2px;
    vertical-align: middle;
  }
  @keyframes hackBlink {
    50% { opacity: 0; }
  }
  .hack-granted {
    margin-top: 12px;
    font-size: 0.9em;
    text-align: center;
    display: none;
    letter-spacing: 3px;
    text-transform: uppercase;
  }
  .hack-granted.active {
    display: block;
    color: var(--primary);
    text-shadow: 0 0 20px rgba(0, 255, 65, 0.5);
    animation: hackPulse 0.5s ease-in-out 3;
  }
  @keyframes hackPulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.7; transform: scale(1.05); }
  }

</style>
</head>
<body>
<div class="auth-box">
  <h1>Job Agent</h1>
  <div class="subtitle">Sign in to your account</div>
  
  <form id="loginForm" onsubmit="return handleLogin(event)">
    <label>Email</label>
    <input type="email" id="loginEmail" placeholder="you@example.com" required autocomplete="email">
    <label>Password</label>
    <input type="password" id="loginPassword" placeholder="••••••••" required autocomplete="current-password">
    <button type="submit" class="auth-btn">SIGN IN</button>
    <div class="auth-error" id="loginError"></div>
  </form>
  
  <div class="auth-link">
    Don't have an account? <a href="/signup">Sign up</a>
  </div>
  <div style="text-align:center;margin-top:10px;font-size:0.75em;">
    <a href="/forgot-password" style="color:var(--text-dim);text-decoration:none;">Forgot password?</a>
  </div>
</div>

<script>
async function handleLogin(e) {
  e.preventDefault();
  const email = document.getElementById('loginEmail').value.trim();
  const password = document.getElementById('loginPassword').value;
  const errorEl = document.getElementById('loginError');
  
  try {
    const resp = await fetch('/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
    const data = await resp.json();
    if (data.status === 'ok') {
      await showHackAnimation(email);
      window.location.href = '/';
    } else {
      errorEl.textContent = data.error || 'Login failed';
      errorEl.style.display = 'block';
    }
  } catch (err) {
    errorEl.textContent = 'Error: ' + err.message;
    errorEl.style.display = 'block';
  }
  return false;
}

// ── Hacking Animation ──
function getHackLines(email) {
  return [
    { text: '[INIT] Establishing secure connection...', cls: 'info', delay: 100 },
    { text: '[OK]  Handshake complete (TLS 1.3, 4096-bit RSA)', cls: 'success', delay: 200 },
    { text: '[INIT] Locating target...', cls: 'info', delay: 150 },
    { text: '[!]   Target identified: ' + email, cls: 'warning', delay: 250 },
    { text: '[INIT] Scanning mainframe access points...', cls: 'info', delay: 120 },
    { text: '[!]   Detected firewall: SKYNET-ASM v4.2', cls: 'warning', delay: 200 },
    { text: '[INIT] Deploying bypass payload...', cls: 'info', delay: 150 },
    { text: '[OK]  IPS/IDS evasion successful', cls: 'success', delay: 250 },
    { text: '[INIT] Cracking credential vault...', cls: 'info', delay: 180 },
    { text: '[OK]  Decryption key obtained', cls: 'success', delay: 200 },
    { text: '[INIT] Injecting session token...', cls: 'info', delay: 150 },
    { text: '[OK]  Privilege escalation: ROOT', cls: 'success', delay: 250 },
    { text: '[INIT] Masking trace route...', cls: 'info', delay: 120 },
    { text: '[OK]  Proxy chain: ACTIVE (14 hops)', cls: 'success', delay: 200 },
    { text: '[INIT] Synchronizing data streams...', cls: 'info', delay: 150 },
    { text: '[OK]  All channels encrypted', cls: 'success', delay: 180 },
    { text: '[SYS] Connection secured. Redirecting...', cls: 'highlight', delay: 300 },
  ];
}

async function showHackAnimation(email) {
  const overlay = document.getElementById('hackOverlay');
  const output = document.getElementById('hackOutput');
  const progressBar = document.getElementById('hackProgressBar');
  const granted = document.getElementById('hackGranted');
  
  // Reset
  overlay.classList.add('active');
  output.innerHTML = '';
  progressBar.style.width = '0%';
  granted.classList.remove('active');
  granted.style.display = 'none';
  
  // Start matrix rain on canvas
  const canvas = document.getElementById('hackCanvas');
  const ctx = canvas.getContext('2d');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  const cols = Math.floor(canvas.width / 14);
  const drops = Array(cols).fill(1);
  const chars = 'ABCDEF0123456789<>!@#$%^&*()_+-=[]{}|;:,./<>?~`';
  
  function drawMatrix() {
    ctx.fillStyle = 'rgba(0, 0, 0, 0.05)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#00ff41';
    ctx.font = '14px monospace';
    for (let i = 0; i < drops.length; i++) {
      const char = chars[Math.floor(Math.random() * chars.length)];
      ctx.fillText(char, i * 14, drops[i] * 14);
      if (drops[i] * 14 > canvas.height && Math.random() > 0.975) drops[i] = 0;
      drops[i]++;
    }
  }
  const matrixInterval = setInterval(drawMatrix, 50);
  
  // Show lines with typing effect
  const lines = getHackLines(email);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const div = document.createElement('div');
    div.className = 'line ' + line.cls;
    div.textContent = line.text;
    output.appendChild(div);
    output.scrollTop = output.scrollHeight;
    const progress = Math.round(((i + 1) / lines.length) * 100);
    progressBar.style.width = progress + '%';
    await new Promise(r => setTimeout(r, line.delay));
  }
  
  // Flash ACCESS GRANTED
  granted.style.display = 'block';
  granted.classList.add('active');
  
  // Wait a moment then clean up
  await new Promise(r => setTimeout(r, 800));
  clearInterval(matrixInterval);
  overlay.classList.remove('active');
}
</script>
<!-- Hacking Animation Overlay -->
<div class="hack-overlay" id="hackOverlay">
  <canvas id="hackCanvas"></canvas>
  <div class="hack-terminal">
    <div class="hack-terminal-header">
      <span class="hack-dot red"></span>
      <span class="hack-dot yellow"></span>
      <span class="hack-dot green"></span>
      <span class="hack-terminal-title">ACCESS TERMINAL v2.1</span>
    </div>
    <div class="hack-output" id="hackOutput"></div>
    <div class="hack-progress"><div class="hack-progress-bar" id="hackProgressBar"></div></div>
    <div class="hack-granted" id="hackGranted">ACCESS GRANTED</div>
  </div>
</div>
</body>
</html>
"""

    SIGNUP_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Agent - Sign Up</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Inter:wght@400;600;700&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root {
    --bg: #0a0a0f;
    --surface: #12121a;
    --surface2: #1a1a2e;
    --border: #2a2a4a;
    --primary: #00ff41;
    --accent: #0ff;
    --text: #c8c8d0;
    --text-dim: #666;
    --error: #ff3355;
  }
  body {
    font-family: 'Share Tech Mono', monospace;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .auth-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 40px;
    width: 100%;
    max-width: 420px;
    box-shadow: 0 0 60px rgba(0,255,65,0.05);
  }
  .auth-box h1 {
    font-size: 1.8em;
    text-align: center;
    margin-bottom: 8px;
    background: linear-gradient(135deg, var(--primary), var(--accent));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: 3px;
    text-transform: uppercase;
  }
  .auth-box .subtitle {
    text-align: center;
    color: var(--text-dim);
    font-size: 0.8em;
    margin-bottom: 30px;
    letter-spacing: 1px;
  }
  .auth-box label {
    display: block;
    font-size: 0.75em;
    color: var(--text-dim);
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 6px;
    margin-top: 16px;
  }
  .auth-box input {
    width: 100%;
    padding: 12px 14px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.9em;
    outline: none;
    transition: border-color 0.2s;
  }
  .auth-box input:focus {
    border-color: var(--primary);
    box-shadow: 0 0 10px rgba(0,255,65,0.15);
  }
  .auth-btn {
    width: 100%;
    padding: 14px;
    margin-top: 24px;
    background: transparent;
    border: 2px solid var(--primary);
    border-radius: 8px;
    color: var(--primary);
    font-family: 'Share Tech Mono', monospace;
    font-size: 1em;
    font-weight: 700;
    letter-spacing: 3px;
    text-transform: uppercase;
    cursor: pointer;
    transition: all 0.3s;
  }
  .auth-btn:hover {
    background: rgba(0,255,65,0.08);
    box-shadow: 0 0 20px rgba(0,255,65,0.2);
  }
  .auth-error {
    color: var(--error);
    font-size: 0.8em;
    text-align: center;
    margin-top: 12px;
    padding: 8px;
    background: rgba(255,51,85,0.08);
    border: 1px solid rgba(255,51,85,0.2);
    border-radius: 4px;
    display: none;
  }
  .auth-link {
    text-align: center;
    margin-top: 20px;
    font-size: 0.8em;
    color: var(--text-dim);
  }
  .auth-link a {
    color: var(--accent);
    text-decoration: none;
  }
  .auth-link a:hover {
    text-decoration: underline;
  }
  .name-fields {
    display: flex;
    gap: 10px;
  }
  .name-fields > div { flex: 1; }
</style>
</head>
<body>
<div class="auth-box">
  <h1>Job Agent</h1>
  <div class="subtitle">Create your account</div>
  
  <form id="signupForm" onsubmit="return handleSignup(event)">
    <label>Full Name</label>
    <input type="text" id="signupName" placeholder="Your Name" required autocomplete="name">
    <label>Email</label>
    <input type="email" id="signupEmail" placeholder="you@example.com" required autocomplete="email">
    <label>Password</label>
    <input type="password" id="signupPassword" placeholder="At least 6 characters" required minlength="6" autocomplete="new-password">
    <button type="submit" class="auth-btn">CREATE ACCOUNT</button>
    <div class="auth-error" id="signupError"></div>
  </form>
  
  <div class="auth-link">
    Already have an account? <a href="/login">Sign in</a>
  </div>
</div>

<script>
async function handleSignup(e) {
  e.preventDefault();
  const name = document.getElementById('signupName').value.trim();
  const email = document.getElementById('signupEmail').value.trim();
  const password = document.getElementById('signupPassword').value;
  const errorEl = document.getElementById('signupError');
  
  if (!name || !email || !password) {
    errorEl.textContent = 'All fields are required';
    errorEl.style.display = 'block';
    return false;
  }
  if (password.length < 6) {
    errorEl.textContent = 'Password must be at least 6 characters';
    errorEl.style.display = 'block';
    return false;
  }
  
  try {
    const resp = await fetch('/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, password })
    });
    const data = await resp.json();
    if (data.status === 'ok') {
      window.location.href = '/';
    } else if (data.status === 'pending_approval') {
      // Show success: waiting for admin approval
      document.getElementById('signupForm').style.display = 'none';
      errorEl.style.display = 'none';
      const msg = document.createElement('div');
      msg.style.cssText = 'text-align:center;padding:20px 0;';
      msg.innerHTML = '<div style="font-size:2em;margin-bottom:12px;">⏳</div>'
        + '<div style="color:var(--primary);font-size:1em;margin-bottom:8px;">Account Created!</div>'
        + '<div style="color:var(--text-dim);font-size:0.85em;line-height:1.5;">'
        + 'Your account is pending admin approval.<br>'
        + 'An admin will activate your account shortly.<br><br>'
        + '<a href="/login" style="color:var(--accent);">Back to login</a>'
        + '</div>';
      document.querySelector('.auth-box').appendChild(msg);
    } else {
      errorEl.textContent = data.error || 'Sign up failed';
      errorEl.style.display = 'block';
    }
  } catch (err) {
    errorEl.textContent = 'Error: ' + err.message;
    errorEl.style.display = 'block';
  }
  return false;
}
</script>
<!-- Hacking Animation Overlay -->
<div class="hack-overlay" id="hackOverlay">
  <canvas id="hackCanvas"></canvas>
  <div class="hack-terminal">
    <div class="hack-terminal-header">
      <span class="hack-dot red"></span>
      <span class="hack-dot yellow"></span>
      <span class="hack-dot green"></span>
      <span class="hack-terminal-title">ACCESS TERMINAL v2.1</span>
    </div>
    <div class="hack-output" id="hackOutput"></div>
    <div class="hack-progress"><div class="hack-progress-bar" id="hackProgressBar"></div></div>
    <div class="hack-granted" id="hackGranted">ACCESS GRANTED</div>
  </div>
</div>
</body>
</html>
"""

    # ── Main GUI Page ──

    GUI_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Agent - AI Job Search</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Inter:wght@400;600;700&display=swap');

  * { margin: 0; padding: 0; box-sizing: border-box; }

  :root {
    --bg: #0a0a0f;
    --surface: #12121a;
    --surface2: #1a1a2e;
    --border: #2a2a4a;
    --primary: #00ff41;
    --primary-dim: #00cc33;
    --accent: #0ff;
    --accent2: #f0f;
    --text: #c8c8d0;
    --text-dim: #666;
    --error: #ff3355;
    --warning: #ffaa00;
  }

  body {
    font-family: 'Share Tech Mono', monospace;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* ── Matrix Rain Canvas ── */
  #matrixCanvas {
    position: fixed;
    top: 0; left: 0;
    width: 100%; height: 100%;
    z-index: 0;
    pointer-events: none;
    opacity: 0.08;
  }

  .container {
    position: relative;
    z-index: 1;
    max-width: 1000px;
    margin: 0 auto;
    padding: 30px 20px;
  }

  /* ── Header ── */
  header {
    text-align: center;
    padding: 40px 0 30px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 30px;
  }
  header h1 {
    font-size: 2.5em;
    font-weight: 700;
    background: linear-gradient(135deg, var(--primary), var(--accent), var(--accent2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    text-shadow: 0 0 40px rgba(0,255,65,0.2);
    letter-spacing: 4px;
    text-transform: uppercase;
  }
  header p {
    color: var(--text-dim);
    margin-top: 8px;
    font-size: 0.9em;
    letter-spacing: 2px;
  }
  header .status-dot {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--primary);
    margin-right: 6px;
    animation: pulse-dot 2s infinite;
  }
  @keyframes pulse-dot {
    0%, 100% { opacity: 1; box-shadow: 0 0 6px var(--primary); }
    50% { opacity: 0.4; box-shadow: 0 0 2px var(--primary); }
  }

  /* ── User Info Bar ── */
  .user-bar {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 20px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 0.8em;
  }
  .user-bar .user-icon { font-size: 1.2em; }
  .user-bar .user-name { color: var(--primary); font-weight: bold; }
  .user-bar .user-email { color: var(--text-dim); font-size: 0.9em; }
  .user-bar .user-spacer { flex: 1; }
  .user-bar a {
    color: var(--accent);
    text-decoration: none;
    padding: 4px 12px;
    border: 1px solid var(--border);
    border-radius: 4px;
    transition: all 0.2s;
  }
  .user-bar a:hover {
    border-color: var(--accent);
    background: rgba(0,255,255,0.08);
  }
  .user-bar .logout-btn {
    background: transparent;
    border: 1px solid var(--text-dim);
    border-radius: 4px;
    color: var(--text-dim);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.85em;
    padding: 4px 12px;
    cursor: pointer;
    transition: all 0.2s;
  }
  .user-bar .logout-btn:hover {
    border-color: var(--error);
    color: var(--error);
  }

  /* ── Save Button ── */
  .history-save {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 10px;
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text-dim);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.72em;
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
  }
  .history-save:hover {
    border-color: var(--warning);
    color: var(--warning);
    background: rgba(255,170,0,0.08);
  }
  .history-save.saved {
    border-color: var(--warning);
    color: var(--warning);
    background: rgba(255,170,0,0.12);
  }
  .history-save.disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }

  /* ── API Key Section ── */
  .api-key-section {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
  .api-key-section label {
    color: var(--text-dim);
    font-size: 0.85em;
    letter-spacing: 1px;
    white-space: nowrap;
  }
  .api-key-input {
    flex: 1;
    min-width: 200px;
    padding: 10px 14px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--primary);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.85em;
    outline: none;
    transition: border-color 0.2s;
  }
  .api-key-input:focus {
    border-color: var(--primary);
    box-shadow: 0 0 10px rgba(0,255,65,0.15);
  }
  .api-key-input::placeholder {
    color: var(--text-dim);
    opacity: 0.5;
  }
  .api-key-status {
    font-size: 0.8em;
    white-space: nowrap;
  }
  .api-key-status.configured { color: var(--primary); }
  .api-key-status.missing { color: var(--warning); }
  .api-key-btn {
    padding: 10px 20px;
    background: transparent;
    border: 1px solid var(--accent);
    border-radius: 6px;
    color: var(--accent);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.85em;
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
  }
  .api-key-btn:hover {
    background: rgba(0,255,255,0.1);
    box-shadow: 0 0 15px rgba(0,255,255,0.2);
  }
  .api-key-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .api-key-ok {
    font-size: 1.2em;
    cursor: default;
  }

  /* ── Upload Section ── */
  .upload-section {
    background: var(--surface);
    border: 2px dashed var(--border);
    border-radius: 16px;
    padding: 40px;
    text-align: center;
    transition: all 0.3s ease;
    margin-bottom: 24px;
    cursor: pointer;
    position: relative;
  }
  .upload-section:hover, .upload-section.drag-over {
    border-color: var(--primary);
    background: var(--surface2);
    box-shadow: 0 0 30px rgba(0,255,65,0.1);
  }
  .upload-section.has-file {
    border-color: var(--primary);
    border-style: solid;
    background: var(--surface2);
  }
  .upload-icon {
    font-size: 3em;
    margin-bottom: 12px;
    display: block;
  }
  .upload-section h3 {
    color: var(--text);
    font-size: 1.1em;
    margin-bottom: 6px;
  }
  .upload-section p {
    color: var(--text-dim);
    font-size: 0.85em;
  }
  .upload-section .file-info {
    display: none;
    margin-top: 12px;
    padding: 10px 16px;
    background: rgba(0,255,65,0.08);
    border: 1px solid var(--primary);
    border-radius: 8px;
    color: var(--primary);
    font-size: 0.9em;
  }
  .upload-section.has-file .file-info { display: inline-block; }
  .upload-section.has-file .upload-prompt { display: none; }
  #fileInput { display: none; }

  /* ── Run Button ── */
  .run-section {
    text-align: center;
    margin-bottom: 24px;
    display: flex;
    gap: 12px;
    justify-content: center;
    align-items: center;
    flex-wrap: wrap;
  }
  .run-btn {
    font-family: 'Share Tech Mono', monospace;
    font-size: 1.1em;
    font-weight: 700;
    letter-spacing: 3px;
    text-transform: uppercase;
    padding: 16px 48px;
    border: 2px solid var(--primary);
    border-radius: 8px;
    background: transparent;
    color: var(--primary);
    cursor: pointer;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
  }
  .run-btn::before {
    content: '';
    position: absolute;
    top: 0; left: -100%;
    width: 100%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(0,255,65,0.15), transparent);
    transition: left 0.5s;
  }
  .run-btn:hover::before { left: 100%; }
  .run-btn:hover {
    background: rgba(0,255,65,0.08);
    box-shadow: 0 0 30px rgba(0,255,65,0.3), inset 0 0 20px rgba(0,255,65,0.1);
    transform: translateY(-2px);
  }
  /* ── Region Selector ── */
  .region-section {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 24px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
  .region-label {
    color: var(--accent);
    font-size: 0.9em;
    letter-spacing: 1px;
    white-space: nowrap;
  }
  .region-select {
    flex: 1;
    min-width: 220px;
    padding: 10px 14px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.85em;
    cursor: pointer;
    outline: none;
    transition: border-color 0.2s, box-shadow 0.2s;
    appearance: none;
    -webkit-appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath fill='%2300ff41' d='M6 8L0 0h12z'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 12px center;
    padding-right: 36px;
  }
  .region-select:focus {
    border-color: var(--accent);
    box-shadow: 0 0 12px rgba(0,255,255,0.15);
  }
  .region-select:hover {
    border-color: var(--primary);
  }
  .region-select option {
    background: var(--surface2);
    color: var(--text);
    padding: 8px;
  }
  .region-select optgroup {
    background: var(--surface);
    color: var(--accent);
    font-weight: 700;
    font-size: 0.9em;
  }
  .region-status {
    font-size: 0.85em;
    color: var(--primary);
    white-space: nowrap;
    padding: 4px 12px;
    background: rgba(0,255,65,0.06);
    border: 1px solid rgba(0,255,65,0.2);
    border-radius: 4px;
  }

  .run-btn:disabled {
    border-color: var(--text-dim);
    color: var(--text-dim);
    cursor: not-allowed;
    box-shadow: none;
    transform: none;
  }
  .run-btn:disabled::before { display: none; }
  .run-btn.running {
    animation: btn-pulse 1.5s infinite;
  }
  @keyframes btn-pulse {
    0%, 100% { box-shadow: 0 0 10px rgba(0,255,65,0.3); }
    50% { box-shadow: 0 0 40px rgba(0,255,65,0.6), 0 0 60px rgba(0,255,65,0.2); }
  }
  .run-btn .btn-text { display: inline; }

  /* ── Stop Button ── */
  .stop-btn {
    font-family: 'Share Tech Mono', monospace;
    font-size: 1em;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 16px 36px;
    border: 2px solid var(--error);
    border-radius: 8px;
    background: transparent;
    color: var(--error);
    cursor: pointer;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
    display: none;
  }
  .stop-btn.visible { display: inline-block; }
  .stop-btn:hover {
    background: rgba(255,51,85,0.12);
    box-shadow: 0 0 25px rgba(255,51,85,0.3), inset 0 0 15px rgba(255,51,85,0.08);
    transform: translateY(-2px);
  }

  /* ── Terminal Output ── */
  .terminal-section {
    background: #050510;
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 24px;
    display: none;
  }
  .terminal-section.active { display: block; }
  .terminal-header {
    background: var(--surface);
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .terminal-dot {
    width: 10px; height: 10px;
    border-radius: 50%;
  }
  .terminal-dot.red { background: #ff5f56; }
  .terminal-dot.yellow { background: #ffbd2e; }
  .terminal-dot.green { background: #27c93f; }
  .terminal-title {
    color: var(--text-dim);
    font-size: 0.8em;
    margin-left: 8px;
    letter-spacing: 1px;
  }
  .terminal-body {
    padding: 16px;
    height: 350px;
    overflow-y: auto;
    font-size: 0.85em;
    line-height: 1.5;
    color: var(--primary);
    position: relative;
  }
  .terminal-body::-webkit-scrollbar {
    width: 6px;
  }
  .terminal-body::-webkit-scrollbar-track {
    background: var(--bg);
  }
  .terminal-body::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 3px;
  }
  .terminal-line {
    white-space: pre-wrap;
    word-break: break-all;
    opacity: 0;
    animation: fadeInLine 0.3s ease forwards;
  }
  @keyframes fadeInLine {
    to { opacity: 1; }
  }
  .terminal-line.system { color: var(--accent); }
  .terminal-line.error { color: var(--error); }
  .terminal-line.ok { color: var(--primary); }
  .terminal-line.skip { color: var(--text-dim); }
  .terminal-line.score-high { color: var(--primary); font-weight: bold; }
  .terminal-line.score-low { color: var(--warning); }
  .terminal-line.progress { color: var(--accent); }
  .terminal-cursor {
    display: inline-block;
    width: 8px;
    height: 14px;
    background: var(--primary);
    animation: blink 1s step-end infinite;
    margin-left: 2px;
  }
  @keyframes blink {
    50% { opacity: 0; }
  }

  /* ── Results Section ── */
  .results-section {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
    display: none;
    margin-bottom: 24px;
  }
  .results-section.active { display: block; }
  .results-section h2 {
    color: var(--primary);
    font-size: 1.2em;
    margin-bottom: 16px;
    letter-spacing: 2px;
    text-transform: uppercase;
  }
  .results-section h2::before { content: '> '; color: var(--accent); }
  .results-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
  }
  .result-stat {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
  }
  .result-stat .value {
    font-size: 2em;
    font-weight: 700;
    color: var(--primary);
  }
  .result-stat .label {
    font-size: 0.75em;
    color: var(--text-dim);
    margin-top: 4px;
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  .result-files {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .result-file {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    text-decoration: none;
    font-size: 0.85em;
    transition: all 0.2s;
  }
  .result-file:hover {
    border-color: var(--primary);
    color: var(--primary);
    background: rgba(0,255,65,0.05);
  }

  /* ── Loading Spinner ── */
  .spinner {
    display: inline-block;
    width: 16px; height: 16px;
    border: 2px solid var(--border);
    border-top-color: var(--primary);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    vertical-align: middle;
    margin-right: 8px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── History Section ── */
  .history-toggle {
    display: block;
    width: 100%;
    padding: 12px 20px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--accent);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.95em;
    cursor: pointer;
    transition: all 0.2s;
    margin-bottom: 24px;
    text-align: center;
    letter-spacing: 1px;
  }
  .history-toggle:hover {
    border-color: var(--accent);
    background: var(--surface2);
    box-shadow: 0 0 20px rgba(0,255,255,0.1);
  }
  .history-section {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    display: none;
    margin-bottom: 24px;
    max-height: 500px;
    overflow-y: auto;
  }
  .history-section.active { display: block; }
  .history-section::-webkit-scrollbar { width: 6px; }
  .history-section::-webkit-scrollbar-track { background: var(--bg); }
  .history-section::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
  .history-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px;
    border-bottom: 1px solid var(--border);
    transition: background 0.2s;
  }
  .history-item:last-child { border-bottom: none; }
  .history-item:hover { background: var(--surface2); }
  .history-score {
    min-width: 48px;
    height: 48px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 1em;
    color: #fff;
  }
  .history-score.high { background: #10b981; }
  .history-score.mid { background: #f59e0b; }
  .history-score.low { background: #ef4444; }
  .history-info { flex: 1; min-width: 0; }
  .history-info .title {
    font-size: 0.9em;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .history-info .company {
    font-size: 0.8em;
    color: var(--accent);
    margin-top: 2px;
  }
  .history-info .meta {
    font-size: 0.7em;
    color: var(--text-dim);
    margin-top: 2px;
    display: flex;
    gap: 10px;
  }
  .history-platform {
    padding: 2px 8px;
    border-radius: 4px;
    background: var(--surface2);
    color: var(--text-dim);
    font-size: 0.7em;
    text-transform: uppercase;
  }
  .history-skills {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 4px;
  }
  .history-skill-tag {
    background: rgba(0,255,65,0.1);
    color: var(--primary);
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 0.7em;
  }
  .history-empty {
    text-align: center;
    padding: 40px;
    color: var(--text-dim);
    font-size: 0.9em;
  }
  .history-apply {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 12px;
    background: rgba(0,255,255,0.1);
    border: 1px solid var(--accent);
    border-radius: 4px;
    color: var(--accent);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.72em;
    text-decoration: none;
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
  }
  .history-apply:hover {
    background: rgba(0,255,255,0.25);
    box-shadow: 0 0 12px rgba(0,255,255,0.3);
  }
  .history-apply.no-url {
    opacity: 0.35;
    cursor: not-allowed;
    border-color: var(--text-dim);
    color: var(--text-dim);
  }
  .history-applied {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 12px;
    background: rgba(0,255,65,0.12);
    border: 1px solid var(--primary);
    border-radius: 4px;
    color: var(--primary);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.72em;
    white-space: nowrap;
    cursor: default;
  }
  .history-loading {
    text-align: center;
    padding: 20px;
    color: var(--text-dim);
  }

  /* ── History Filters ── */
  .history-filters {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    padding: 12px 0;
    margin-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }
  .filter-group {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .filter-label {
    color: var(--text-dim);
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  .filter-select {
    padding: 4px 8px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.78em;
    cursor: pointer;
    outline: none;
    transition: border-color 0.2s;
  }
  .filter-select:focus {
    border-color: var(--accent);
  }
  .filter-select option {
    background: var(--surface2);
    color: var(--text);
  }
  .filter-count {
    margin-left: auto;
    color: var(--text-dim);
    font-size: 0.75em;
    white-space: nowrap;
  }
  .filter-count .num {
    color: var(--accent);
    font-weight: 700;
  }
  .clear-history-btn {
    padding: 4px 12px;
    background: transparent;
    border: 1px solid var(--warning);
    border-radius: 4px;
    color: var(--warning);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.72em;
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
  }
  .clear-history-btn:hover {
    background: rgba(255,170,0,0.12);
    box-shadow: 0 0 10px rgba(255,170,0,0.2);
  }
  .filter-spacer {
    width: 1px;
    height: 20px;
    background: var(--border);
    margin: 0 4px;
  }

  /* ── Responsive ── */
  @media (max-width: 600px) {
    header h1 { font-size: 1.5em; letter-spacing: 2px; }
    .run-btn { padding: 14px 24px; font-size: 0.9em; }
    .upload-section { padding: 24px; }
    .terminal-body { height: 250px; }
  }
</style>
</head>
<body>

<canvas id="matrixCanvas"></canvas>

<div class="container">
  <header>
    <h1>Job Agent</h1>
    <p><span class="status-dot"></span> AI-Powered Job Search &bull; CV Generator</p>
  </header>

  <!-- User Info Bar -->
  <div class="user-bar">
    <span class="user-icon">👤</span>
    <span class="user-name">{{ user.name }}</span>
    <span class="user-email">{{ user.email }}</span>
    <span class="user-spacer"></span>
    {% if user.role == 'admin' %}
    <a href="/admin">🛡️ Admin</a>
    {% endif %}
    <button class="logout-btn" onclick="logoutUser()">🚪 Logout</button>
  </div>

  <!-- API Key Section -->
  <div class="api-key-section" id="apiKeySection">
    <label>🔑 API Key:</label>
    <input type="password" class="api-key-input" id="apiKeyInput"
      placeholder="sk-ant-... paste your Anthropic API key here"
      autocomplete="off" spellcheck="false">
    <button class="api-key-btn" id="apiKeyBtn" onclick="setApiKey()">SAVE</button>
    <span class="api-key-status missing" id="apiKeyStatus">⚠️ Not set</span>
  </div>

  <!-- Upload Section -->
  <div class="upload-section" id="uploadZone">
    <div class="upload-prompt">
      <span class="upload-icon">📄</span>
      <h3>Drop your CV here or click to upload</h3>
      <p>Supports PDF format (max 10MB)</p>
    </div>
    <div class="file-info">
      <span id="fileName">resume.pdf</span> loaded
    </div>
    <input type="file" id="fileInput" accept=".pdf">
  </div>

  <!-- Region Selector -->
  <div class="region-section">
    <label class="region-label">🌍 Region:</label>
    <select class="region-select" id="regionSelect" onchange="setRegion(this.value)">
      <optgroup label="🌐 Broad Regions">
        <option value="Remote" selected>🌍 Remote (Worldwide)</option>
        <option value="Europe">🇪🇺 All Europe</option>
      </optgroup>
      <optgroup label="🇪🇺 Western Europe">
        <option value="Austria">Austria</option>
        <option value="Belgium">Belgium</option>
        <option value="France">France</option>
        <option value="Germany">Germany</option>
        <option value="Ireland">Ireland</option>
        <option value="Luxembourg">Luxembourg</option>
        <option value="Monaco">Monaco</option>
        <option value="Netherlands">Netherlands</option>
        <option value="Switzerland">Switzerland</option>
        <option value="United Kingdom">United Kingdom</option>
      </optgroup>
      <optgroup label="🇪🇺 Northern Europe">
        <option value="Denmark">Denmark</option>
        <option value="Estonia">Estonia</option>
        <option value="Finland">Finland</option>
        <option value="Iceland">Iceland</option>
        <option value="Latvia">Latvia</option>
        <option value="Lithuania">Lithuania</option>
        <option value="Norway">Norway</option>
        <option value="Sweden">Sweden</option>
      </optgroup>
      <optgroup label="🇪🇺 Southern Europe">
        <option value="Croatia">Croatia</option>
        <option value="Cyprus">Cyprus</option>
        <option value="Greece">Greece</option>
        <option value="Italy">Italy</option>
        <option value="Malta">Malta</option>
        <option value="Portugal">Portugal</option>
        <option value="Spain">Spain</option>
      </optgroup>
      <optgroup label="🇪🇺 Central &amp; Eastern Europe">
        <option value="Bulgaria">Bulgaria</option>
        <option value="Czech Republic">Czech Republic</option>
        <option value="Hungary">Hungary</option>
        <option value="Poland">Poland</option>
        <option value="Romania">Romania</option>
        <option value="Slovakia">Slovakia</option>
        <option value="Slovenia">Slovenia</option>
      </optgroup>
      <optgroup label="🌍 North America">
        <option value="Canada">Canada</option>
        <option value="Mexico">Mexico</option>
        <option value="United States">United States</option>
      </optgroup>
      <optgroup label="🌏 Asia &amp; Pacific">
        <option value="Australia">Australia</option>
        <option value="India">India</option>
        <option value="Japan">Japan</option>
        <option value="New Zealand">New Zealand</option>
        <option value="Singapore">Singapore</option>
        <option value="South Korea">South Korea</option>
      </optgroup>
      <optgroup label="🌍 Other">
        <option value="Brazil">Brazil</option>
        <option value="South Africa">South Africa</option>
        <option value="UAE">UAE</option>
      </optgroup>
    </select>
    <span class="region-status" id="regionStatus">🌐 Remote</span>
  </div>

  <!-- Run / Stop Buttons -->
  <div class="run-section">
    <button class="run-btn" id="runBtn" disabled>
      <span class="btn-text">▶ RUN AGENT</span>
    </button>
    <button class="stop-btn" id="stopBtn" onclick="stopAgent()">
      ■ STOP
    </button>
  </div>

  <!-- Terminal -->
  <div class="terminal-section" id="terminalSection">
    <div class="terminal-header">
      <span class="terminal-dot red"></span>
      <span class="terminal-dot yellow"></span>
      <span class="terminal-dot green"></span>
      <span class="terminal-title" id="terminalTitle">Agent Console</span>
    </div>
    <div class="terminal-body" id="terminalBody">
      <span class="terminal-cursor"></span>
    </div>
  </div>

  <!-- Results -->
  <div class="results-section" id="resultsSection">
    <h2>Results</h2>
    <div class="results-grid" id="resultsGrid"></div>
    <div class="result-files" id="resultFiles"></div>
  </div>

  <!-- History Toggle Button -->
  <button class="history-toggle" id="historyToggle" onclick="toggleHistory()">
    📋 VIEW SCORING HISTORY
  </button>

  <!-- History Section -->
  <div class="history-section" id="historySection">
    <div class="history-filters" id="historyFilters" style="display:none;">
      <div class="filter-group">
        <span class="filter-label">Sort:</span>
        <select class="filter-select" id="sortSelect" onchange="applyFiltersAndSort()">
          <option value="score-desc">Score ↓</option>
          <option value="score-asc">Score ↑</option>
          <option value="date-desc" selected>Newest</option>
          <option value="date-asc">Oldest</option>
          <option value="platform">Platform</option>
        </select>
      </div>
      <div class="filter-spacer"></div>
      <div class="filter-group">
        <span class="filter-label">Score:</span>
        <select class="filter-select" id="scoreFilter" onchange="applyFiltersAndSort()">
          <option value="all">All</option>
          <option value="high">80%+</option>
          <option value="mid">60-79%</option>
          <option value="low">0-59%</option>
        </select>
      </div>
      <div class="filter-group">
        <span class="filter-label">Platform:</span>
        <select class="filter-select" id="platformFilter" onchange="applyFiltersAndSort()">
          <option value="all">All</option>
        </select>
      </div>
      <div class="filter-group">
        <span class="filter-label">Status:</span>
        <select class="filter-select" id="statusFilter" onchange="applyFiltersAndSort()">
          <option value="all">All</option>
          <option value="unapplied">Unapplied</option>
          <option value="applied">Applied</option>
          <option value="saved">Saved ⭐</option>
        </select>
      </div>
      <div class="filter-spacer"></div>
      <div class="filter-group">
        <span class="filter-label">Type:</span>
        <select class="filter-select" id="typeFilter" onchange="applyFiltersAndSort()">
          <option value="all">All</option>
          <option value="full">Full Desc</option>
          <option value="title">Title Only</option>
        </select>
      </div>          <span class="filter-count" id="filterCount"></span>
          <div class="filter-spacer"></div>
          <button class="clear-history-btn" id="clearHistoryBtn" onclick="clearHistory()">
            🗑 CLEAR
          </button>
    </div>
    <div id="historyContent">
      <div class="history-loading">Loading history...</div>
    </div>
  </div>
</div>

<script>
// ── Matrix Rain ──
const canvas = document.getElementById('matrixCanvas');
const ctx = canvas.getContext('2d');

function resizeCanvas() {
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
}
resizeCanvas();
window.addEventListener('resize', resizeCanvas);

const chars = 'アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン0123456789ABCDEF';
const fontSize = 14;
const columns = canvas.width / fontSize;
const drops = Array(Math.floor(columns)).fill(1);

function drawMatrix() {
  ctx.fillStyle = 'rgba(10, 10, 15, 0.05)';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#00ff41';
  ctx.font = fontSize + 'px monospace';

  for (let i = 0; i < drops.length; i++) {
    const char = chars[Math.floor(Math.random() * chars.length)];
    ctx.fillText(char, i * fontSize, drops[i] * fontSize);
    if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) {
      drops[i] = 0;
    }
    drops[i]++;
  }
}
setInterval(drawMatrix, 50);

// ── API Key ──
const apiKeyInput = document.getElementById('apiKeyInput');
const apiKeyStatus = document.getElementById('apiKeyStatus');

async function setApiKey() {
  const key = apiKeyInput.value.trim();
  if (!key || !key.startsWith('sk-ant-')) {
    apiKeyStatus.textContent = '⚠️ Invalid key (must start with sk-ant-)';
    apiKeyStatus.className = 'api-key-status missing';
    return;
  }
  try {
    const resp = await fetch('/set-api-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: key })
    });
    const data = await resp.json();
    if (data.status === 'ok') {
      apiKeyStatus.textContent = '✅ Configured';
      apiKeyStatus.className = 'api-key-status configured';
      apiKeyInput.type = 'password';
      apiKeyInput.disabled = true;
      document.getElementById('apiKeyBtn').disabled = true;
      // Enable run button if CV is also uploaded
      if (uploadedFile) runBtn.disabled = false;
    } else {
      apiKeyStatus.textContent = '⚠️ ' + (data.error || 'Failed');
      apiKeyStatus.className = 'api-key-status missing';
    }
  } catch (err) {
    apiKeyStatus.textContent = '⚠️ Error: ' + err.message;
    apiKeyStatus.className = 'api-key-status missing';
  }
}

// ── Region Selector ──
const regionSelect = document.getElementById('regionSelect');
const regionStatus = document.getElementById('regionStatus');

async function setRegion(value) {
  if (!value) return;
  try {
    const resp = await fetch('/set-region', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ region: value })
    });
    const data = await resp.json();
    if (data.status === 'ok') {
      regionStatus.textContent = '🌐 ' + data.region;
    }
  } catch (err) {
    console.error('Failed to set region:', err);
  }
}

// Check on page load if API key is already set (don't pre-load uploaded CV)
fetch('/status').then(r => r.json()).then(status => {
  if (status.api_key_configured) {
    apiKeyStatus.textContent = '✅ Configured';
    apiKeyStatus.className = 'api-key-status configured';
    apiKeyInput.disabled = true;
    document.getElementById('apiKeyBtn').disabled = true;
  }
  // Restore previously selected region
  if (status.selected_region) {
    const options = regionSelect.querySelectorAll('option');
    for (const opt of options) {
      if (opt.value === status.selected_region) {
        opt.selected = true;
        regionStatus.textContent = '🌐 ' + status.selected_region;
        break;
      }
    }
  }
});

// ── Upload ──
const uploadZone = document.getElementById('uploadZone');
const fileInput = document.getElementById('fileInput');
const fileName = document.getElementById('fileName');
const runBtn = document.getElementById('runBtn');
let uploadedFile = null;

uploadZone.addEventListener('click', () => fileInput.click());

uploadZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  uploadZone.classList.add('drag-over');
});
uploadZone.addEventListener('dragleave', () => {
  uploadZone.classList.remove('drag-over');
});
uploadZone.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadZone.classList.remove('drag-over');
  const files = e.dataTransfer.files;
  if (files.length > 0) handleFile(files[0]);
});

fileInput.addEventListener('change', () => {
  if (fileInput.files.length > 0) handleFile(fileInput.files[0]);
});

async function handleFile(file) {
  if (!file.name.endsWith('.pdf')) {
    alert('Please upload a PDF file');
    return;
  }
  uploadedFile = file;
  fileName.textContent = file.name;
  uploadZone.classList.add('has-file');

  // Upload to server
  const formData = new FormData();
  formData.append('file', file);

  try {
    const resp = await fetch('/upload', { method: 'POST', body: formData });
    const data = await resp.json();
    if (data.status === 'ok') {
      // Only enable Run button if API key is also configured
      runBtn.disabled = !apiKeyInput.disabled;
    } else {
      alert('Upload failed: ' + (data.error || 'Unknown error'));
    }
  } catch (err) {
    alert('Upload failed: ' + err.message);
  }
}

// ── Run Agent ──
const terminalSection = document.getElementById('terminalSection');
const terminalBody = document.getElementById('terminalBody');
const resultsSection = document.getElementById('resultsSection');
const resultsGrid = document.getElementById('resultsGrid');
const resultFiles = document.getElementById('resultFiles');
let eventSource = null;

const stopBtn = document.getElementById('stopBtn');

async function stopAgent() {
  try {
    await fetch('/stop', { method: 'POST' });
  } catch (err) {
    console.error('Stop failed:', err);
  }
}

runBtn.addEventListener('click', () => {
  if (eventSource) return;

  runBtn.disabled = true;
  runBtn.classList.add('running');
  stopBtn.classList.add('visible');
  const btnText = runBtn.querySelector('.btn-text');
  // Animate button dots with JS (CSS cannot animate content)
  let dotCount = 0;
  const dotTimer = setInterval(() => {
    dotCount = (dotCount + 1) % 4;
    btnText.textContent = '⟳ RUNNING' + '.'.repeat(dotCount);
  }, 500);
  // Update terminal header with selected region and CV filename
  const regionLabel = regionStatus.textContent || '🌐 Remote';
  const cvLabel = fileName.textContent || 'resume.pdf';
  document.getElementById('terminalTitle').textContent = 'Agent Console — ' + regionLabel + ' | CV: ' + cvLabel;
  terminalSection.classList.add('active');
  resultsSection.classList.remove('active');
  terminalBody.innerHTML = '';

  // Start SSE stream
  eventSource = new EventSource('/run');
  eventSource.onmessage = (e) => {
    const lines = e.data.split('\n');
    for (const line of lines) {
      if (!line) continue;
      appendTerminalLine(line);
    }
  };
  eventSource.onerror = () => {
    eventSource.close();
    eventSource = null;
    clearInterval(dotTimer);
    runBtn.classList.remove('running');
    stopBtn.classList.remove('visible');
    runBtn.querySelector('.btn-text').textContent = '▶ RUN AGAIN';
    runBtn.disabled = !uploadedFile;
    fetchResults();
  };
});

function appendTerminalLine(text) {
  // Remove cursor
  const cursor = terminalBody.querySelector('.terminal-cursor');
  if (cursor) cursor.remove();

  const div = document.createElement('div');
  div.className = 'terminal-line';

  if (text.startsWith('[ERROR]') || text.includes('ERROR')) {
    div.classList.add('error');
  } else if (text.startsWith('[SYSTEM]') || text.startsWith('=') || text.includes('PHASE')) {
    div.classList.add('system');
  } else if (text.includes('[OK]') || text.includes('done')) {
    div.classList.add('score-high');
  } else if (text.includes('SKIP')) {
    div.classList.add('skip');
  } else if (text.includes('[  ]') || text.includes('->')) {
    if (text.includes('*')) {
      div.classList.add('score-high');
    } else {
      div.classList.add('score-low');
    }
  } else if (text.includes('%') && text.includes('/')) {
    div.classList.add('progress');
  } else if (text.startsWith('  Found') || text.startsWith('  Results')) {
    div.classList.add('ok');
  }

  div.textContent = text;
  terminalBody.appendChild(div);
  terminalBody.scrollTop = terminalBody.scrollHeight;

  // Add cursor back
  const newCursor = document.createElement('span');
  newCursor.className = 'terminal-cursor';
  terminalBody.appendChild(newCursor);
}

async function fetchResults() {
  try {
    const resp = await fetch('/results');
    const data = await resp.json();
    displayResults(data);
  } catch (err) {
    console.error('Failed to fetch results:', err);
  }
}

function displayResults(data) {
  if (!data.files || data.files.length === 0) return;

  resultsSection.classList.add('active');

  // Stats
  resultsGrid.innerHTML = '';
  const stats = [
    { value: data.stats?.total_jobs_reviewed || data.jobs_found || 0, label: 'Jobs Found' },
    { value: data.high_match || 0, label: 'High Match (80%+)' },
    { value: data.cvs_generated || 0, label: 'CVs Generated' },
    { value: data.files.length, label: 'Files Created' },
  ];
  for (const stat of stats) {
    const div = document.createElement('div');
    div.className = 'result-stat';
    div.innerHTML = `<div class="value">${stat.value}</div><div class="label">${stat.label}</div>`;
    resultsGrid.appendChild(div);
  }

  // Files
  resultFiles.innerHTML = '';
  for (const file of data.files) {
    const a = document.createElement('a');
    a.className = 'result-file';
    a.href = '/download/' + encodeURIComponent(file);
    a.download = file;
    const ext = file.endsWith('.pdf') ? '📕' : '📄';
    a.innerHTML = `${ext} ${file}`;
    resultFiles.appendChild(a);
  }
}

// ── History Toggle & Render ──
const historySection = document.getElementById('historySection');
const historyContent = document.getElementById('historyContent');
let _allHistoryJobs = [];
let _appliedSet = new Set();
let _savedSet = new Set();

async function logoutUser() {
  await fetch('/logout', { method: 'POST' });
  window.location.href = '/login';
}

async function toggleHistory() {
  const btn = document.getElementById('historyToggle');
  if (historySection.classList.contains('active')) {
    historySection.classList.remove('active');
    btn.textContent = '📋 VIEW SCORING HISTORY';
    return;
  }
  historySection.classList.add('active');
  btn.textContent = '📋 HIDE SCORING HISTORY';
  await renderHistory();
}

async function renderHistory() {
  historyContent.innerHTML = '<div class="history-loading"><span class="spinner"></span> Loading history...</div>';
  try {
    // Fetch history, applied set, and saved set in parallel
    const [histResp, appliedResp, savedResp] = await Promise.all([
      fetch('/api/history'),
      fetch('/api/applied'),
      fetch('/api/saved'),
    ]);
    const data = await histResp.json();
    const appliedData = await appliedResp.json();
    const savedData = await savedResp.json();
    _appliedSet = new Set(appliedData.applied || []);
    _savedSet = new Set(savedData.saved || []);
    // Client-side safety: filter out any unscored jobs (score=0)
    _allHistoryJobs = (data.jobs || []).filter(j => (j.ai_score || 0) > 0);

    if (_allHistoryJobs.length === 0) {
      historyContent.innerHTML = '<div class="history-empty">No scoring history yet. Run the agent to get started!</div>';
      document.getElementById('historyFilters').style.display = 'none';
      return;
    }

    // Build platform filter options from unique platforms
    const platforms = [...new Set(_allHistoryJobs.map(j => j.job?.platform || 'unknown').filter(Boolean))];
    const platformSelect = document.getElementById('platformFilter');
    const currentVal = platformSelect.value;
    platformSelect.innerHTML = '<option value="all">All</option>' +
      platforms.map(p => `<option value="${escHtml(p)}">${escHtml(p.charAt(0).toUpperCase() + p.slice(1))}</option>`).join('');
    if (platforms.some(p => p === currentVal)) platformSelect.value = currentVal;

    // Show filter toolbar and apply current filters
    document.getElementById('historyFilters').style.display = 'flex';
    applyFiltersAndSort();
  } catch (err) {
    historyContent.innerHTML = `<div class="history-empty">Failed to load history: ${err.message}</div>`;
    document.getElementById('historyFilters').style.display = 'none';
  }
}

function applyFiltersAndSort() {
  const sortVal = document.getElementById('sortSelect').value;
  const scoreVal = document.getElementById('scoreFilter').value;
  const platformVal = document.getElementById('platformFilter').value;
  const statusVal = document.getElementById('statusFilter').value;
  const typeVal = document.getElementById('typeFilter').value;

  // Filter
  let filtered = _allHistoryJobs.filter(job => {
    // Score filter
    const score = job.ai_score || 0;
    if (scoreVal === 'high' && score < 80) return false;
    if (scoreVal === 'mid' && (score < 60 || score >= 80)) return false;
    if (scoreVal === 'low' && score >= 60) return false;

    // Platform filter
    const platform = (job.job?.platform || 'unknown').toLowerCase();
    if (platformVal !== 'all' && platform !== platformVal) return false;

    // Status filter
    const jobUrl = job.job?.url || '';
    const isApplied = jobUrl && _appliedSet.has(jobUrl);
    if (statusVal === 'applied' && !isApplied) return false;
    if (statusVal === 'unapplied' && isApplied) return false;

    // Saved filter
    const jobId = job.id;
    const isSaved = jobId && _savedSet.has(jobId);
    if (statusVal === 'saved' && !isSaved) return false;

    // Type filter (title-only vs full description)
    const concerns = job.concerns || [];
    const isTitleOnly = concerns.some(c => c && c.toLowerCase().includes('no job description'));
    if (typeVal === 'title' && !isTitleOnly) return false;
    if (typeVal === 'full' && isTitleOnly) return false;

    return true;
  });

  // Sort
  filtered.sort((a, b) => {
    switch (sortVal) {
      case 'score-desc': return (b.ai_score || 0) - (a.ai_score || 0);
      case 'score-asc': return (a.ai_score || 0) - (b.ai_score || 0);
      case 'date-desc': return (b.timestamp || '').localeCompare(a.timestamp || '');
      case 'date-asc': return (a.timestamp || '').localeCompare(b.timestamp || '');
      case 'platform': return (a.job?.platform || '').localeCompare(b.job?.platform || '');
      default: return 0;
    }
  });

  // Update count
  const countEl = document.getElementById('filterCount');
  countEl.innerHTML = `<span class="num">${filtered.length}</span> / ${_allHistoryJobs.length} jobs`;

  // Render
  _renderJobList(filtered);
}

function _renderJobList(jobs) {
  if (jobs.length === 0) {
    historyContent.innerHTML = '<div class="history-empty">No jobs match the current filters.</div>';
    return;
  }
  let html = '';
  for (const job of jobs) {
    const score = job.ai_score || 0;
    const scoreClass = score >= 80 ? 'high' : (score >= 60 ? 'mid' : 'low');
    const platform = job.job?.platform || 'unknown';
    const skills = (job.matching_skills || []).slice(0, 3);
    const date = (job.timestamp || '').slice(0, 10);
    const jobUrl = job.job?.url || '';
    const isApplied = jobUrl && _appliedSet.has(jobUrl);
    const jobId = job.id;
    const isSaved = jobId && _savedSet.has(jobId);
    const canSave = score >= 80;

    let actionHtml;
    if (isApplied) {
      actionHtml = `<span class="history-applied">✅ Applied</span>`;
    } else if (jobUrl) {
      const safeUrl = escHtml(jobUrl);
      actionHtml = `<button class="history-apply" data-url="${safeUrl}" onclick="applyToJob(this.dataset.url, this)">🔗 Apply</button>`;
    } else {
      actionHtml = `<span class="history-apply no-url">🔗 No Link</span>`;
    }

    // Save/star button (only for 80%+)
    let saveHtml;
    if (canSave) {
      const savedClass = isSaved ? 'saved' : '';
      const starIcon = isSaved ? '⭐' : '☆';
      const saveText = isSaved ? 'Saved' : 'Save';
      const escTitle = escHtml(job.job?.title || '');
      const escCompany = escHtml(job.job?.company || '');
      const escUrl = escHtml(job.job?.url || '');
      const escPlatform = escHtml(job.job?.platform || 'unknown');
      const escLocation = escHtml(job.job?.location || '');
      const jobData = JSON.stringify({
        timestamp: job.timestamp || '',
        ai_score: score,
        matching_skills: job.matching_skills || [],
        concerns: job.concerns || [],
        cover_letter: job.cover_letter || '',
        job: { title: escTitle, company: escCompany, url: escUrl, platform: escPlatform, location: escLocation }
      });
      saveHtml = `<button class="history-save ${savedClass}" data-id="${jobId}" data-job="${encodeURIComponent(jobData)}" onclick="toggleSaveJob(this.dataset.id, this)">${starIcon} ${saveText}</button>`;
    } else {
      saveHtml = `<span class="history-save disabled">☆ Save (80%+ only)</span>`;
    }

    html += `
      <div class="history-item">
        <div class="history-score ${scoreClass}">${score}</div>
        <div class="history-info">
          <div class="title">${escHtml(job.job?.title || 'Unknown')}</div>
          <div class="company">${escHtml(job.job?.company || 'Unknown')}</div>
          <div class="meta">
            <span class="history-platform">${escHtml(platform)}</span>
            <span>${date}</span>
          </div>
          <div class="history-skills">
            ${skills.map(s => `<span class="history-skill-tag">${escHtml(s)}</span>`).join('')}
          </div>
        </div>
        <div style="display:flex;flex-direction:column;align-items:center;gap:6px;">
          ${saveHtml}
          ${actionHtml}
        </div>
      </div>`;
  }
  historyContent.innerHTML = html;
}

async function toggleSaveJob(applicationId, btn) {
  const isSaved = _savedSet.has(applicationId);
  try {
    if (isSaved) {
      const resp = await fetch('/api/unsave-job', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ application_id: applicationId })
      });
      const data = await resp.json();
      if (data.status === 'ok') {
        _savedSet.delete(applicationId);
        btn.classList.remove('saved');
        btn.innerHTML = '☆ Save';
        applyFiltersAndSort();
      }
    } else {
      // Send full job data from data-job attribute
      let body;
      if (btn.dataset.job) {
        body = decodeURIComponent(btn.dataset.job);
      } else {
        body = JSON.stringify({ application_id: applicationId });
      }
      const resp = await fetch('/api/save-job', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body
      });
      const data = await resp.json();
      if (data.status === 'ok') {
        _savedSet.add(applicationId);
        btn.classList.add('saved');
        btn.innerHTML = '⭐ Saved';
        // Update data-id with the new application_id from backend
        if (data.application_id) {
          btn.dataset.id = data.application_id;
          _savedSet.delete(applicationId);
          _savedSet.add(data.application_id);
        }
        applyFiltersAndSort();
      } else {
        alert(data.error || 'Failed to save job');
      }
    }
  } catch (err) {
    console.error('Toggle save failed:', err);
  }
}

async function applyToJob(url, btn) {
  // Disable button and show loading state
  btn.disabled = true;
  btn.textContent = '⏳ Applying...';
  try {
    const resp = await fetch('/api/mark-applied', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url })
    });
    const data = await resp.json();
    if (data.status === 'ok') {
      // Update global applied set so filters/sorts stay in sync
      _appliedSet.add(url);
      // Replace button with Applied badge
      btn.outerHTML = '<span class="history-applied">✅ Applied</span>';
      // Re-apply filters so the list re-syncs (e.g. Status: Unapplied filter)
      applyFiltersAndSort();
      // Open job listing in new tab
      window.open(url, '_blank', 'noopener,noreferrer');
    } else {
      btn.textContent = '🔗 Apply';
      btn.disabled = false;
      alert('Failed to mark as applied: ' + (data.error || 'Unknown error'));
    }
  } catch (err) {
    btn.textContent = '🔗 Apply';
    btn.disabled = false;
    alert('Error: ' + err.message);
  }
}

async function clearHistory() {
  if (!confirm('Clear all scoring history and applied jobs?')) return;
  try {
    const resp = await fetch('/api/clear-history', { method: 'POST' });
    const data = await resp.json();
    if (data.status === 'ok') {
      _allHistoryJobs = [];
      _appliedSet = new Set();
      _savedSet = new Set();
      historyContent.innerHTML = '<div class="history-empty">History cleared. Run the agent to generate new results!</div>';
      document.getElementById('historyFilters').style.display = 'none';
    }
  } catch (err) {
    alert('Failed to clear history: ' + err.message);
  }
}

function escHtml(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}
</script>
<!-- Hacking Animation Overlay -->
<div class="hack-overlay" id="hackOverlay">
  <canvas id="hackCanvas"></canvas>
  <div class="hack-terminal">
    <div class="hack-terminal-header">
      <span class="hack-dot red"></span>
      <span class="hack-dot yellow"></span>
      <span class="hack-dot green"></span>
      <span class="hack-terminal-title">ACCESS TERMINAL v2.1</span>
    </div>
    <div class="hack-output" id="hackOutput"></div>
    <div class="hack-progress"><div class="hack-progress-bar" id="hackProgressBar"></div></div>
    <div class="hack-granted" id="hackGranted">ACCESS GRANTED</div>
  </div>
</div>
</body>
</html>
"""

    # ── Auth Routes ──

    @app.route('/login', methods=['GET', 'POST'])
    def login_page():
        """Login page. GET shows form, POST authenticates."""
        if session.get('user_id'):
            return redirect(url_for('index'))
        if request.method == 'GET':
            return render_template_string(LOGIN_HTML)
        # POST
        # Ensure the admin account exists and is active on every login
        ensure_admin_exists()
        cleanup_old_saved_jobs(days=7)
        
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'error': 'Invalid request'}), 400
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        if not email or not password:
            return jsonify({'status': 'error', 'error': 'Email and password required'}), 400
        result = login_user(email, password)
        # Check if result is an error dict (pending/rejected) or actual user
        if isinstance(result, dict) and result.get('error'):
            if result['error'] == 'pending':
                log_login_attempt(email=email, success=False, details='pending approval', ip_address=request.remote_addr or '', user_agent=request.user_agent.string if request.user_agent else '')
                return jsonify({'status': 'error', 'error': '⏳ Your account is pending admin approval. Please wait for an admin to activate it.'}), 403
            elif result['error'] == 'rejected':
                log_login_attempt(email=email, success=False, details='rejected', ip_address=request.remote_addr or '', user_agent=request.user_agent.string if request.user_agent else '')
                return jsonify({'status': 'error', 'error': '❌ Your account registration was rejected by the admin.'}), 403
        if not result:
            return jsonify({'status': 'error', 'error': 'Invalid email or password'}), 401
        logger.info(f"User logged in: {email}")
        # Log successful login
        log_login_attempt(
            email=email,
            success=True,
            user_id=result.get('id'),
            ip_address=request.remote_addr or '',
            user_agent=request.user_agent.string if request.user_agent else '',
        )
        return jsonify({'status': 'ok', 'user': {'name': result['name'], 'email': result['email']}})

    @app.route('/signup', methods=['GET', 'POST'])
    def signup_page():
        """Signup page. GET shows form, POST registers."""
        if session.get('user_id'):
            return redirect(url_for('index'))
        if request.method == 'GET':
            return render_template_string(SIGNUP_HTML)
        # POST
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'error': 'Invalid request'}), 400
        name = data.get('name', '').strip()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        if not name or not email or not password:
            return jsonify({'status': 'error', 'error': 'All fields required'}), 400
        if len(password) < 6:
            return jsonify({'status': 'error', 'error': 'Password must be at least 6 characters'}), 400
        user = register_user(email, password, name)
        if not user:
            return jsonify({'status': 'error', 'error': 'Email already registered'}), 409
        # No auto-login — user must wait for admin approval
        logger.info(f"New user registered (pending approval): {email}")
        return jsonify({'status': 'pending_approval', 'message': 'Account created! Please wait for admin approval before logging in.'})

    @app.route('/logout', methods=['POST'])
    def logout():
        """Logout the current user."""
        logout_user()
        return jsonify({'status': 'ok'})

    # ── Forgot / Reset Password Routes ──

    @app.route('/forgot-password', methods=['GET', 'POST'])
    def forgot_password():
        """Forgot password page. GET shows form, POST sends reset email."""
        if session.get('user_id'):
            return redirect(url_for('index'))
        if request.method == 'GET':
            return render_template_string(FORGOT_PASSWORD_HTML)
        # POST
        data = request.get_json()
        if not data or not data.get('email'):
            return jsonify({'status': 'error', 'error': 'Email required'}), 400
        email = data['email'].strip().lower()
        # Always respond with same message for security (don't reveal if email exists)
        # Clean up expired tokens on every request
        cleanup_expired_tokens()
        
        user = db_get_user_by_email(email)
        if user and user.get('status') == 'active':
            token = create_password_reset_token(user['id'])
            if token:
                sent = send_password_reset_email(email, user['name'], token)
                if sent:
                    logger.info(f"Password reset email sent to {email}")
                else:
                    logger.info(f"Password reset email would be sent to {email} (no RESEND_API_KEY)")
        return jsonify({
            'status': 'ok',
            'message': 'If that email exists and is active, a reset link has been sent. Check your inbox (and spam folder).'
        })

    @app.route('/reset-password/<token>', methods=['GET', 'POST'])
    def reset_password(token):
        """Reset password page. GET validates token, POST updates password."""
        if session.get('user_id'):
            return redirect(url_for('index'))
        
        # Validate token
        user = get_user_by_reset_token(token)
        if not user:
            return render_template_string(r"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Agent - Invalid Link</title>
<style>@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Inter:wght@400;600;700&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0a0a0f;--surface:#12121a;--border:#2a2a4a;--primary:#00ff41;--accent:#0ff;--text:#c8c8d0;--text-dim:#666;--error:#ff3355}
body{font-family:'Share Tech Mono',monospace;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center}
.box{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:40px;width:100%;max-width:420px;text-align:center}
h1{color:var(--error);font-size:1.4em;margin-bottom:12px}
p{color:var(--text-dim);font-size:0.85em;margin-bottom:20px;line-height:1.5}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
</style>
</head>
<body>
<div class="box">
<h1>🔗 Invalid or Expired Link</h1>
<p>This password reset link is invalid, expired, or has already been used.<br>Reset links are valid for 1 hour.</p>
<a href="/forgot-password">Request a new reset link</a>
</div>
<!-- Hacking Animation Overlay -->
<div class="hack-overlay" id="hackOverlay">
  <canvas id="hackCanvas"></canvas>
  <div class="hack-terminal">
    <div class="hack-terminal-header">
      <span class="hack-dot red"></span>
      <span class="hack-dot yellow"></span>
      <span class="hack-dot green"></span>
      <span class="hack-terminal-title">ACCESS TERMINAL v2.1</span>
    </div>
    <div class="hack-output" id="hackOutput"></div>
    <div class="hack-progress"><div class="hack-progress-bar" id="hackProgressBar"></div></div>
    <div class="hack-granted" id="hackGranted">ACCESS GRANTED</div>
  </div>
</div>
</body>
</html>
""")

        if request.method == 'GET':
            return render_template_string(RESET_PASSWORD_HTML)
        
        # POST - update password
        data = request.get_json()
        if not data or not data.get('password'):
            return jsonify({'status': 'error', 'error': 'Password required'}), 400
        
        new_password = data['password']
        if len(new_password) < 6:
            return jsonify({'status': 'error', 'error': 'Password must be at least 6 characters'}), 400
        
        new_hash = hash_password(new_password)
        ok = update_user_password(user['id'], new_hash)
        if ok:
            use_password_reset_token(token)
            logger.info(f"Password reset completed for user {user['email']}")
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error', 'error': 'Failed to update password'}), 500

    # ── Forgot Password HTML ──

    FORGOT_PASSWORD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Agent - Forgot Password</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Inter:wght@400;600;700&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root { --bg: #0a0a0f; --surface: #12121a; --surface2: #1a1a2e; --border: #2a2a4a; --primary: #00ff41; --accent: #0ff; --text: #c8c8d0; --text-dim: #666; --error: #ff3355; }
  body { font-family: 'Share Tech Mono', monospace; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
  .auth-box { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 40px; width: 100%; max-width: 420px; box-shadow: 0 0 60px rgba(0,255,65,0.05); }
  .auth-box h1 { font-size: 1.8em; text-align: center; margin-bottom: 8px; background: linear-gradient(135deg, var(--primary), var(--accent)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: 3px; text-transform: uppercase; }
  .auth-box .subtitle { text-align: center; color: var(--text-dim); font-size: 0.8em; margin-bottom: 30px; letter-spacing: 1px; }
  .auth-box label { display: block; font-size: 0.75em; color: var(--text-dim); letter-spacing: 1px; text-transform: uppercase; margin-bottom: 6px; margin-top: 16px; }
  .auth-box input { width: 100%; padding: 12px 14px; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text); font-family: 'Share Tech Mono', monospace; font-size: 0.9em; outline: none; transition: border-color 0.2s; }
  .auth-box input:focus { border-color: var(--primary); box-shadow: 0 0 10px rgba(0,255,65,0.15); }
  .auth-btn { width: 100%; padding: 14px; margin-top: 24px; background: transparent; border: 2px solid var(--primary); border-radius: 8px; color: var(--primary); font-family: 'Share Tech Mono', monospace; font-size: 1em; font-weight: 700; letter-spacing: 3px; text-transform: uppercase; cursor: pointer; transition: all 0.3s; }
  .auth-btn:hover { background: rgba(0,255,65,0.08); box-shadow: 0 0 20px rgba(0,255,65,0.2); }
  .auth-msg { font-size: 0.8em; text-align: center; margin-top: 12px; padding: 8px; border-radius: 4px; display: none; }
  .auth-msg.success { display: block; color: var(--primary); background: rgba(0,255,65,0.08); border: 1px solid rgba(0,255,65,0.2); }
  .auth-msg.error { display: block; color: var(--error); background: rgba(255,51,85,0.08); border: 1px solid rgba(255,51,85,0.2); }
  .auth-link { text-align: center; margin-top: 20px; font-size: 0.8em; color: var(--text-dim); }
  .auth-link a { color: var(--accent); text-decoration: none; }
  .auth-link a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="auth-box">
  <h1>Job Agent</h1>
  <div class="subtitle">Reset your password</div>
  
  <form id="forgotForm" onsubmit="return handleForgot(event)">
    <label>Email</label>
    <input type="email" id="forgotEmail" placeholder="you@example.com" required autocomplete="email">
    <button type="submit" class="auth-btn">SEND RESET LINK</button>
    <div class="auth-msg" id="forgotMsg"></div>
  </form>
  
  <div class="auth-link">
    <a href="/login">Back to login</a>
  </div>
</div>

<script>
async function handleForgot(e) {
  e.preventDefault();
  const email = document.getElementById('forgotEmail').value.trim();
  const msg = document.getElementById('forgotMsg');
  const btn = document.querySelector('.auth-btn');
  btn.disabled = true;
  btn.textContent = '⏳ SENDING...';
  msg.className = 'auth-msg';
  msg.style.display = 'none';
  try {
    const resp = await fetch('/forgot-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email })
    });
    const data = await resp.json();
    msg.textContent = data.message || 'If that email exists, a reset link has been sent.';
    msg.className = 'auth-msg success';
    msg.style.display = 'block';
    document.getElementById('forgotEmail').value = '';
  } catch (err) {
    msg.textContent = 'Error: ' + err.message;
    msg.className = 'auth-msg error';
    msg.style.display = 'block';
  }
  btn.disabled = false;
  btn.textContent = 'SEND RESET LINK';
  return false;
}
</script>
<!-- Hacking Animation Overlay -->
<div class="hack-overlay" id="hackOverlay">
  <canvas id="hackCanvas"></canvas>
  <div class="hack-terminal">
    <div class="hack-terminal-header">
      <span class="hack-dot red"></span>
      <span class="hack-dot yellow"></span>
      <span class="hack-dot green"></span>
      <span class="hack-terminal-title">ACCESS TERMINAL v2.1</span>
    </div>
    <div class="hack-output" id="hackOutput"></div>
    <div class="hack-progress"><div class="hack-progress-bar" id="hackProgressBar"></div></div>
    <div class="hack-granted" id="hackGranted">ACCESS GRANTED</div>
  </div>
</div>
</body>
</html>
"""

    RESET_PASSWORD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Agent - Reset Password</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Inter:wght@400;600;700&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root { --bg: #0a0a0f; --surface: #12121a; --surface2: #1a1a2e; --border: #2a2a4a; --primary: #00ff41; --accent: #0ff; --text: #c8c8d0; --text-dim: #666; --error: #ff3355; }
  body { font-family: 'Share Tech Mono', monospace; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
  .auth-box { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 40px; width: 100%; max-width: 420px; box-shadow: 0 0 60px rgba(0,255,65,0.05); }
  .auth-box h1 { font-size: 1.8em; text-align: center; margin-bottom: 8px; background: linear-gradient(135deg, var(--primary), var(--accent)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: 3px; text-transform: uppercase; }
  .auth-box .subtitle { text-align: center; color: var(--text-dim); font-size: 0.8em; margin-bottom: 30px; letter-spacing: 1px; }
  .auth-box label { display: block; font-size: 0.75em; color: var(--text-dim); letter-spacing: 1px; text-transform: uppercase; margin-bottom: 6px; margin-top: 16px; }
  .auth-box input { width: 100%; padding: 12px 14px; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text); font-family: 'Share Tech Mono', monospace; font-size: 0.9em; outline: none; transition: border-color 0.2s; }
  .auth-box input:focus { border-color: var(--primary); box-shadow: 0 0 10px rgba(0,255,65,0.15); }
  .auth-btn { width: 100%; padding: 14px; margin-top: 24px; background: transparent; border: 2px solid var(--primary); border-radius: 8px; color: var(--primary); font-family: 'Share Tech Mono', monospace; font-size: 1em; font-weight: 700; letter-spacing: 3px; text-transform: uppercase; cursor: pointer; transition: all 0.3s; }
  .auth-btn:hover { background: rgba(0,255,65,0.08); box-shadow: 0 0 20px rgba(0,255,65,0.2); }
  .auth-msg { font-size: 0.8em; text-align: center; margin-top: 12px; padding: 8px; border-radius: 4px; display: none; }
  .auth-msg.success { display: block; color: var(--primary); background: rgba(0,255,65,0.08); border: 1px solid rgba(0,255,65,0.2); }
  .auth-msg.error { display: block; color: var(--error); background: rgba(255,51,85,0.08); border: 1px solid rgba(255,51,85,0.2); }
  .auth-link { text-align: center; margin-top: 20px; font-size: 0.8em; color: var(--text-dim); }
  .auth-link a { color: var(--accent); text-decoration: none; }
  .auth-link a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="auth-box">
  <h1>Job Agent</h1>
  <div class="subtitle" id="resetSubtitle">Enter your new password</div>
  
  <form id="resetForm" onsubmit="return handleReset(event)">
    <label>New Password</label>
    <input type="password" id="resetPassword" placeholder="At least 6 characters" required minlength="6" autocomplete="new-password">
    <button type="submit" class="auth-btn">UPDATE PASSWORD</button>
    <div class="auth-msg" id="resetMsg"></div>
  </form>
  
  <div class="auth-link" id="resetLink">
    <a href="/login">Back to login</a>
  </div>
</div>

<script>
async function handleReset(e) {
  e.preventDefault();
  const password = document.getElementById('resetPassword').value;
  const msg = document.getElementById('resetMsg');
  if (password.length < 6) {
    msg.textContent = 'Password must be at least 6 characters';
    msg.className = 'auth-msg error';
    msg.style.display = 'block';
    return;
  }
  const btn = document.querySelector('.auth-btn');
  btn.disabled = true;
  btn.textContent = '⏳ UPDATING...';
  msg.className = 'auth-msg';
  msg.style.display = 'none';
  try {
    const path = window.location.pathname;
    const resp = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password })
    });
    const data = await resp.json();
    if (data.status === 'ok') {
      msg.textContent = '✅ Password updated! Redirecting to login...';
      msg.className = 'auth-msg success';
      msg.style.display = 'block';
      document.getElementById('resetForm').style.display = 'none';
      document.getElementById('resetSubtitle').textContent = 'Password updated!';
      setTimeout(() => { window.location.href = '/login'; }, 2000);
    } else {
      msg.textContent = data.error || 'Failed to reset password';
      msg.className = 'auth-msg error';
      msg.style.display = 'block';
    }
  } catch (err) {
    msg.textContent = 'Error: ' + err.message;
    msg.className = 'auth-msg error';
    msg.style.display = 'block';
  }
  btn.disabled = false;
  btn.textContent = 'UPDATE PASSWORD';
  return false;
}
</script>
<!-- Hacking Animation Overlay -->
<div class="hack-overlay" id="hackOverlay">
  <canvas id="hackCanvas"></canvas>
  <div class="hack-terminal">
    <div class="hack-terminal-header">
      <span class="hack-dot red"></span>
      <span class="hack-dot yellow"></span>
      <span class="hack-dot green"></span>
      <span class="hack-terminal-title">ACCESS TERMINAL v2.1</span>
    </div>
    <div class="hack-output" id="hackOutput"></div>
    <div class="hack-progress"><div class="hack-progress-bar" id="hackProgressBar"></div></div>
    <div class="hack-granted" id="hackGranted">ACCESS GRANTED</div>
  </div>
</div>
</body>
</html>
"""

    # ── Main Routes (require login) ──

    @app.route('/')
    @require_login
    def index():
        user = get_current_user()
        return render_template_string(GUI_HTML, user=user)

    @app.route('/healthz')
    def healthz():
        """Health check endpoint for HF Spaces."""
        return jsonify({'status': 'ok'})

    @app.route('/upload', methods=['POST'])
    @require_login
    def upload_file():
        global _run_complete

        if 'file' not in request.files:
            return jsonify({'status': 'error', 'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'status': 'error', 'error': 'No file selected'}), 400

        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'status': 'error', 'error': 'Only PDF files are supported'}), 400

        global _uploaded_filename

        # Save user-specific resume: data/logs/{user_id}_resume.pdf
        uid = get_user_id()
        resume_dir = Path(config.data_dir) / "logs"
        resume_dir.mkdir(parents=True, exist_ok=True)
        if uid:
            save_path = resume_dir / f"resume_{uid}.pdf"
        else:
            save_path = Path(config.resume_save_path)
        file.save(str(save_path))
        _uploaded_filename = file.filename

        # Clear old results tracking for a fresh run
        _run_complete = False

        logger.info(f"CV '{_uploaded_filename}' uploaded and saved to {save_path}")
        return jsonify({'status': 'ok', 'filename': _uploaded_filename})

    @app.route('/stop', methods=['POST'])
    @require_login
    def stop_agent():
        """Stop the running agent subprocess."""
        global _run_process, _run_thread, _run_complete, _output_queue, _stop_requested

        _stop_requested = True

        if _run_process is not None:
            try:
                _run_process.terminate()
                _run_process.wait(timeout=3)
            except Exception:
                try:
                    _run_process.kill()
                    _run_process.wait(timeout=2)
                except Exception:
                    pass

        if _output_queue is not None:
            _output_queue.put("[SYSTEM] Agent stopped by user.\n")

        logger.info("Agent stopped by user")
        return jsonify({'status': 'ok'})

    @app.route('/set-region', methods=['POST'])
    @require_login
    def set_region():
        global _selected_region
        data = request.get_json()
        if not data or 'region' not in data:
            return jsonify({'status': 'error', 'error': 'No region provided'}), 400
        region = data['region'].strip()
        if not region:
            return jsonify({'status': 'error', 'error': 'Empty region'}), 400
        _selected_region = region
        logger.info(f"Region set to: {region}")
        return jsonify({'status': 'ok', 'region': region})

    @app.route('/set-api-key', methods=['POST'])
    @require_login
    def set_api_key():
        global _gui_api_key
        data = request.get_json()
        if not data or 'api_key' not in data:
            return jsonify({'status': 'error', 'error': 'No API key provided'}), 400

        key = data['api_key'].strip()
        if not key.startswith('sk-ant-'):
            return jsonify({'status': 'error', 'error': 'Invalid key format'}), 400

        _gui_api_key = key
        
        # Also save API key to user's profile in DB
        uid = get_user_id()
        if uid:
            update_user_api_key(uid, key)
        
        logger.info("API key configured via browser GUI")
        return jsonify({'status': 'ok'})

    @app.route('/run')
    @require_login
    def run_agent():
        global _output_queue, _run_thread, _run_complete, _gui_api_key, _uploaded_filename

        if _run_thread and _run_thread.is_alive():
            return jsonify({'error': 'Agent is already running'}), 409

        # Reset state
        _output_queue = queue.Queue()
        _run_complete = False
        _stop_requested = False

        project_root = Path(__file__).resolve().parent.parent
        work_dir = str(project_root)

        # Capture user_id in request context BEFORE spawning thread
        current_user_id = get_user_id()

        def generate():
            global _run_complete, _stop_requested
            yield f"data: [SYSTEM] Starting agent with CV: {_uploaded_filename}\n\n"
            yield f"data: [SYSTEM] Analyzing resume, generating search keywords...\n\n"

            api_key = _gui_api_key or config.anthropic_api_key
            thread = threading.Thread(
                target=_run_agent_in_thread,
                args=(work_dir, api_key, current_user_id),
                daemon=True,
            )
            thread.start()
            _run_thread = thread

            while True:
                try:
                    line = _output_queue.get(timeout=1)
                    safe_line = line.replace('\n', '\\n')
                    yield f"data: {safe_line}\n\n"
                except queue.Empty:
                    if _run_complete:
                        try:
                            while True:
                                line = _output_queue.get_nowait()
                                safe_line = line.replace('\n', '\\n')
                                yield f"data: {safe_line}\n\n"
                        except queue.Empty:
                            pass
                        if _stop_requested:
                            yield "data: [SYSTEM] Agent stopped.\n\n"
                        else:
                            yield "data: [SYSTEM] Agent completed.\n\n"
                        break
                    else:
                        yield ": heartbeat\n\n"

        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive',
            }
        )

    @app.route('/results')
    @require_login
    def get_results():
        data_dir = Path(config.data_dir)
        files = []

        for pattern in ['jobs_*.docx', 'cv_*.pdf']:
            for f in data_dir.glob(pattern):
                files.append(f.name)

        uid = get_user_id()
        # Use per-user tracker
        user_tracker = ApplicationTracker(data_dir=config.data_dir, user_id=uid)
        stats = user_tracker.get_stats()
        high_match = len(user_tracker.get_high_match(min_score=80))

        return jsonify({
            'files': sorted(files),
            'jobs_found': stats['total_jobs_reviewed'],
            'high_match': high_match,
            'cvs_generated': len([f for f in files if f.startswith('cv_')]),
            'stats': stats,
            'run_complete': _run_complete,
        })

    @app.route('/api/clear-history', methods=['POST'])
    @require_login
    def clear_history():
        """Clear user's scoring history."""
        uid = get_user_id()
        if uid:
            # Clear from SQLite DB
            clear_user_applications(uid)
            # Clear per-user tracker JSON file
            user_tracker = ApplicationTracker(data_dir=config.data_dir, user_id=uid)
            user_tracker.clear()
            # Also delete the JSON file to prevent re-import on next sync
            json_path = Path(config.data_dir) / "logs" / f"applications_{uid}.json"
            if json_path.exists():
                json_path.unlink()
        else:
            tracker.clear()
        logger.info(f"History cleared for user {uid}")
        return jsonify({'status': 'ok'})

    @app.route('/api/applied', methods=['GET'])
    @require_login
    def get_applied():
        uid = get_user_id()
        if uid:
            urls = get_applied_urls(uid)
            return jsonify({'applied': sorted(urls)})
        return jsonify({'applied': sorted(_load_applied())})

    @app.route('/api/mark-applied', methods=['POST'])
    @require_login
    def mark_applied():
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'status': 'error', 'error': 'No URL provided'}), 400
        url = data['url'].strip()
        if not url:
            return jsonify({'status': 'error', 'error': 'Empty URL'}), 400
        
        uid = get_user_id()
        if uid:
            newly = mark_applied(uid, url)
        else:
            newly = _mark_applied(url)
        logger.info(f"Job marked as applied: {url[:80]}...")
        return jsonify({'status': 'ok', 'newly_marked': newly})

    @app.route('/api/history')
    @require_login
    def get_history():
        uid = get_user_id()
        jobs = []
        cleanup_old_saved_jobs(days=7)
        if uid:
            # 1. Load saved jobs from SQLite (user explicitly saved these)
            saved_apps = get_saved_applications(uid)
            for a in saved_apps:
                jobs.append({
                    'timestamp': a.get('timestamp', ''),
                    'ai_score': a.get('ai_score', 0),
                    'matching_skills': a.get('matching_skills', []),
                    'concerns': a.get('concerns', []),
                    'cover_letter': a.get('cover_letter', ''),
                    'id': a.get('id'),
                    'job': {
                        'title': a.get('title', 'Unknown'),
                        'company': a.get('company', 'Unknown'),
                        'url': a.get('url', ''),
                        'platform': a.get('platform', 'unknown'),
                        'location': a.get('location', ''),
                    }
                })
            
            # 2. Load current session results from JSON file (not persisted)
            json_path = Path(config.data_dir) / "logs" / f"applications_{uid}.json"
            if json_path.exists():
                try:
                    content = json_path.read_text().strip()
                    if content:
                        data = json.loads(content)
                        if not isinstance(data, list):
                            data = [data]
                        for item in data:
                            job_data = item.get('job', {})
                            url = job_data.get('url', '')
                            # Skip if already saved (avoid duplicates)
                            if any(j.get('job', {}).get('url') == url for j in jobs if url):
                                continue
                            jobs.append({
                                'timestamp': item.get('timestamp', ''),
                                'ai_score': item.get('ai_score', 0),
                                'matching_skills': item.get('matching_skills', []),
                                'concerns': item.get('concerns', []),
                                'cover_letter': item.get('cover_letter', ''),
                                'id': None,  # Not saved yet
                                'job': {
                                    'title': job_data.get('title', 'Unknown'),
                                    'company': job_data.get('company', 'Unknown'),
                                    'url': url,
                                    'platform': job_data.get('platform', 'unknown'),
                                    'location': job_data.get('location', ''),
                                }
                            })
                except Exception:
                    pass
            
            # Sort by timestamp descending
            jobs.sort(key=lambda j: j.get('timestamp', ''), reverse=True)
            return jsonify({'jobs': jobs})
        else:
            all_jobs = tracker.load_all()
            all_jobs = [j for j in all_jobs if (j.get('ai_score') or 0) > 0]
            all_jobs.reverse()
            return jsonify({'jobs': all_jobs[:200]})

    @app.route('/download/<path:filename>')
    def download_file(filename):
        data_dir = Path(config.data_dir)
        filepath = data_dir / filename
        if filepath.exists() and filepath.is_file():
            return send_file(str(filepath), as_attachment=True)
        project_root = Path(__file__).resolve().parent.parent
        filepath = project_root / filename
        if filepath.exists() and filepath.is_file():
            return send_file(str(filepath), as_attachment=True)
        return jsonify({'error': 'File not found'}), 404

    @app.route('/status')
    @require_login
    def status():
        s = _agent_status()
        uid = get_user_id()
        user = get_current_user()
        s['api_key_configured'] = bool(_gui_api_key or config.anthropic_api_key)
        s['uploaded_filename'] = _uploaded_filename
        s['selected_region'] = _selected_region
        s['user'] = {
            'id': uid,
            'name': user['name'] if user else '',
            'email': user['email'] if user else '',
            'role': user['role'] if user else '',
        } if user else None
        return jsonify(s)

    @app.route('/api/config')
    @require_login
    def api_config():
        uid = get_user_id()
        user = get_current_user()
        return jsonify({
            'uploaded_filename': _uploaded_filename,
            'data_dir': config.data_dir,
            'is_hf_space': config.is_hf_space,
            'user': {
                'id': uid,
                'name': user['name'] if user else '',
                'email': user['email'] if user else '',
                'role': user['role'] if user else '',
            } if user else None,
        })

    # ── Save / Bookmark Jobs (80%+ only) ──

    @app.route('/api/save-job', methods=['POST'])
    @require_login
    def save_job_route():
        """Save/bookmark a job. Accepts full job data and saves it."""
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'error': 'No data provided'}), 400
        uid = get_user_id()
        
        # Build app entry from submitted data
        job_data = data.get('job', data)
        score = data.get('ai_score') or data.get('score') or 0
        if score < 80:
            return jsonify({'status': 'error', 'error': 'Only jobs with 80%+ match can be saved'}), 403
        
        app_entry = {
            'timestamp': data.get('timestamp', ''),
            'title': job_data.get('title', 'Unknown'),
            'company': job_data.get('company', 'Unknown'),
            'url': job_data.get('url', ''),
            'platform': job_data.get('platform', 'unknown'),
            'location': job_data.get('location', ''),
            'ai_score': score,
            'matching_skills': data.get('matching_skills', []),
            'concerns': data.get('concerns', []),
            'cover_letter': data.get('cover_letter', ''),
            'job_description': job_data.get('description', ''),
        }
        app_id = save_job_with_data(uid, app_entry)
        if not app_id:
            return jsonify({'status': 'error', 'error': 'Failed to save job'}), 500
        return jsonify({'status': 'ok', 'application_id': app_id})

    @app.route('/api/unsave-job', methods=['POST'])
    @require_login
    def unsave_job_route():
        """Remove a saved/bookmarked job and its application data."""
        data = request.get_json()
        if not data or 'application_id' not in data:
            return jsonify({'status': 'error', 'error': 'No application_id provided'}), 400
        app_id = data['application_id']
        uid = get_user_id()
        removed = db_unsave_job(uid, app_id)
        # Also delete the application data since user doesn't want it anymore
        if removed:
            from .database import delete_application
            delete_application(app_id)
        return jsonify({'status': 'ok', 'removed': removed})

    @app.route('/api/saved', methods=['GET'])
    @require_login
    def get_saved():
        """Get list of saved application IDs for current user."""
        uid = get_user_id()
        saved_ids = get_saved_application_ids(uid)
        return jsonify({'saved': sorted(saved_ids)})

    # ── Admin Routes ──

    @app.route('/admin')
    @require_admin
    def admin_panel():
        """Admin panel page."""
        users = get_all_users()
        pending_users = get_pending_users()
        all_apps = get_all_applications(limit=200)
        stats = get_stats()
        pending_count = len(pending_users)
        html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Agent - Admin</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Inter:wght@400;600;700&display=swap');
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  :root {{ --bg: #0a0a0f; --surface: #12121a; --surface2: #1a1a2e; --border: #2a2a4a; --primary: #00ff41; --accent: #0ff; --text: #c8c8d0; --text-dim: #666; --warning: #ffaa00; --error: #ff3355; }}
  body {{ font-family: 'Share Tech Mono', monospace; background: var(--bg); color: var(--text); padding: 30px; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ font-size: 1.8em; background: linear-gradient(135deg, var(--primary), var(--accent)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: 3px; text-transform: uppercase; margin-bottom: 30px; }}
  .stats {{ display: flex; gap: 16px; margin-bottom: 30px; flex-wrap: wrap; }}
  .stat-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px 24px; flex: 1; min-width: 120px; }}
  .stat-card .num {{ font-size: 2em; color: var(--primary); }}
  .stat-card .lbl {{ font-size: 0.75em; color: var(--text-dim); text-transform: uppercase; }}
  .stat-card.warning .num {{ color: var(--warning); }}
  table {{ width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin-bottom: 30px; }}
  th {{ background: var(--surface2); color: var(--accent); padding: 10px 14px; text-align: left; font-size: 0.75em; text-transform: uppercase; letter-spacing: 1px; }}
  td {{ padding: 10px 14px; border-top: 1px solid var(--border); font-size: 0.85em; }}
  tr:hover td {{ background: var(--surface2); }}
  .badge {{ padding: 2px 8px; border-radius: 4px; font-size: 0.75em; }}
  .badge-admin {{ background: rgba(0,255,255,0.15); color: var(--accent); border: 1px solid rgba(0,255,255,0.3); }}
  .badge-user {{ background: rgba(0,255,65,0.1); color: var(--primary); border: 1px solid rgba(0,255,65,0.2); }}
  .badge-pending {{ background: rgba(255,170,0,0.15); color: var(--warning); border: 1px solid rgba(255,170,0,0.3); }}
  .btn-approve {{ padding: 4px 12px; background: transparent; border: 1px solid var(--primary); border-radius: 4px; color: var(--primary); font-family: 'Share Tech Mono', monospace; font-size: 0.75em; cursor: pointer; transition: all 0.2s; }}
  .btn-approve:hover {{ background: rgba(0,255,65,0.15); }}
  .btn-reject {{ padding: 4px 12px; background: transparent; border: 1px solid var(--error); border-radius: 4px; color: var(--error); font-family: 'Share Tech Mono', monospace; font-size: 0.75em; cursor: pointer; transition: all 0.2s; }}
  .btn-reject:hover {{ background: rgba(255,51,85,0.15); }}
  .btn-reset {{ padding: 4px 12px; background: transparent; border: 1px solid var(--warning); border-radius: 4px; color: var(--warning); font-family: 'Share Tech Mono', monospace; font-size: 0.75em; cursor: pointer; transition: all 0.2s; }}
  .btn-reset:hover {{ background: rgba(255,170,0,0.15); }}
  .btn-group {{ display: flex; gap: 6px; }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .nav {{ margin-bottom: 20px; display: flex; gap: 16px; align-items: center; }}
  .nav a {{ font-size: 0.85em; }}
  .nav .pending-badge {{ background: rgba(255,170,0,0.15); color: var(--warning); padding: 2px 10px; border-radius: 12px; font-size: 0.75em; }}
  .score {{ color: var(--primary); font-weight: bold; }}
  .section-title {{ color: var(--accent); font-size: 0.9em; text-transform: uppercase; letter-spacing: 2px; margin: 20px 0 10px; display: flex; align-items: center; gap: 10px; }}
  .empty {{ text-align: center; padding: 30px; color: var(--text-dim); font-size: 0.85em; }}
</style></head>
<body>
<div class="container">
  <div class="nav">
    <a href="/">← Dashboard</a>
    <span style="flex:1;"></span>
    <a href="/logout" onclick="fetch('/logout',{{method:'POST'}}).then(()=>location='/login')">Logout</a>
  </div>
  <h1>🛡️ Admin Panel</h1>
  
  <div class="stats">
    <div class="stat-card"><div class="num">{stats['total_jobs']}</div><div class="lbl">Total Jobs</div></div>
    <div class="stat-card"><div class="num">{stats['avg_score']}</div><div class="lbl">Avg Score</div></div>
    <div class="stat-card"><div class="num">{stats['high_match']}</div><div class="lbl">80%+ Match</div></div>
    <div class="stat-card"><div class="num">{stats['saved_jobs']}</div><div class="lbl">Saved Jobs</div></div>
    <div class="stat-card"><div class="num">{len(users)}</div><div class="lbl">Users</div></div>
    <div class="stat-card warning"><div class="num">{pending_count}</div><div class="lbl">Pending ⏳</div></div>
  </div>

  <!-- Change Password Section -->
  <div class="section-title">🔑 Change Admin Password</div>
  <div style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:20px;margin-bottom:24px;">
    <form id="changePwForm" onsubmit="return changePassword(event)" style="display:flex;flex-wrap:wrap;gap:12px;align-items:end;">
      <div>
        <label style="display:block;font-size:0.75em;color:var(--text-dim);margin-bottom:4px;">Current Password</label>
        <input type="password" id="currentPw" required style="padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'Share Tech Mono',monospace;font-size:0.85em;outline:none;width:200px;">
      </div>
      <div>
        <label style="display:block;font-size:0.75em;color:var(--text-dim);margin-bottom:4px;">New Password</label>
        <input type="password" id="newPw" required minlength="6" placeholder="At least 6 characters" style="padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'Share Tech Mono',monospace;font-size:0.85em;outline:none;width:200px;">
      </div>
      <button type="submit" style="padding:8px 20px;background:transparent;border:1px solid var(--primary);border-radius:4px;color:var(--primary);font-family:'Share Tech Mono',monospace;font-size:0.85em;cursor:pointer;transition:all 0.2s;" onmouseover="this.style.background='rgba(0,255,65,0.08)'" onmouseout="this.style.background='transparent'">UPDATE PASSWORD</button>
      <span id="pwMsg" style="font-size:0.8em;display:none;"></span>
    </form>
  </div>

  {{pending_section}}
  
  <div class="section-title">👥 All Users <span style="font-size:0.7em;color:var(--text-dim);font-weight:400;">({len(users)} total)</span></div>
  <table>
    <tr><th>ID</th><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Joined</th><th>Actions</th></tr>
    {"".join(f'<tr><td>{u["id"]}</td><td>{u["name"]}</td><td>{u["email"]}</td><td><span class="badge badge-{"admin" if u["role"]=="admin" else "user"}">{u["role"]}</span></td><td><span class="badge badge-{"pending" if u.get("status")=="pending" else "user"}">{u.get("status","active")}</span></td><td>{u["created_at"][:10] if u.get("created_at") else ""}</td><td>{"<button class=\"btn-reset\" onclick=\"resetUserPassword("+str(u["id"])+")\">🔑 Reset Pw</button>" if u["role"]!="admin" else ""}</td></tr>' for u in users)}
  </table>
  
  <div class="section-title">🕐 Session Logs <span style="font-size:0.7em;color:var(--text-dim);font-weight:400;">(recent 200 logins)</span></div>
  <div style="margin-bottom:12px;">
    <button onclick="toggleSessionLogs()" style="padding:6px 16px;background:transparent;border:1px solid var(--accent);border-radius:4px;color:var(--accent);font-family:'Share Tech Mono',monospace;font-size:0.8em;cursor:pointer;transition:all 0.2s;">
      📋 Show Session Logs
    </button>
  </div>
  <div id="sessionLogSection" style="display:none;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:24px;overflow-x:auto;">
    <div id="sessionLogContent" style="font-size:0.8em;color:var(--text-dim);text-align:center;padding:20px;">Loading...</div>
  </div>

  <div class="section-title">📋 Recent Applications <span style="font-size:0.7em;color:var(--text-dim);font-weight:400;">(all users)</span></div>
  <table>
    <tr><th>User</th><th>Title</th><th>Company</th><th>Score</th><th>Platform</th><th>Date</th></tr>
    {"".join(f'<tr><td>{a.get("user_name","?")}</td><td>{a.get("title","?")}</td><td>{a.get("company","?")}</td><td class="score">{a.get("ai_score",0)}%</td><td>{a.get("platform","")}</td><td>{(a.get("timestamp") or "")[:10]}</td></tr>' for a in all_apps[:100])}
  </table>
</div>

<script>
function approveUser(id) {{
  if (!confirm('Approve this user?')) return;
  fetch('/admin/api/approve-user/' + id, {{ method: 'POST' }})
    .then(r => r.json())
    .then(d => {{ if (d.status === 'ok') location.reload(); else alert(d.error); }});
}}
function rejectUser(id) {{
  if (!confirm('Reject and delete this user account?')) return;
  fetch('/admin/api/reject-user/' + id, {{ method: 'POST' }})
    .then(r => r.json())
    .then(d => {{ if (d.status === 'ok') location.reload(); else alert(d.error); }});
}}
function resetUserPassword(id) {{
  const newPw = prompt('Enter new password for user ID ' + id + ' (min 6 chars):');
  if (!newPw || newPw.length < 6) {{ alert('Password must be at least 6 characters'); return; }}
  fetch('/admin/api/reset-user-password/' + id, {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ password: newPw }})
  }})
  .then(r => r.json())
  .then(d => {{ if (d.status === 'ok') {{ alert('✅ Password reset successfully!'); location.reload(); }} else {{ alert('⚠️ ' + (d.error || 'Failed')); }} }});
}}

function changePassword(e) {{
  e.preventDefault();
  const current = document.getElementById('currentPw').value;
  const newPw = document.getElementById('newPw').value;
  const msg = document.getElementById('pwMsg');
  if (!current || !newPw) return;
  if (newPw.length < 6) {{ msg.textContent = '⚠️ Min 6 characters'; msg.style.display = 'block'; msg.style.color = '#ff3355'; return; }}
  msg.textContent = '⏳ Updating...';
  msg.style.display = 'block';
  msg.style.color = '#666';
  fetch('/admin/api/change-password', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ current_password: current, new_password: newPw }})
  }})
  .then(r => r.json())
  .then(d => {{
    if (d.status === 'ok') {{
      msg.textContent = '✅ Password updated successfully!';
      msg.style.color = '#00ff41';
      document.getElementById('currentPw').value = '';
      document.getElementById('newPw').value = '';
    }} else {{
      msg.textContent = '⚠️ ' + (d.error || 'Failed');
      msg.style.color = '#ff3355';
    }}
  }})
  .catch(err => {{
    msg.textContent = '⚠️ Error: ' + err.message;
    msg.style.color = '#ff3355';
  }});
  return false;
}}

let _sessionLogsVisible = false;
async function toggleSessionLogs() {{
  const section = document.getElementById('sessionLogSection');
  const btn = event.target;
  if (_sessionLogsVisible) {{
    section.style.display = 'none';
    btn.textContent = '📋 Show Session Logs';
    _sessionLogsVisible = false;
    return;
  }}
  section.style.display = 'block';
  btn.textContent = '📋 Hide Session Logs';
  _sessionLogsVisible = true;
  document.getElementById('sessionLogContent').innerHTML = '<span class="spinner" style="display:inline-block;width:12px;height:12px;border:2px solid var(--border);border-top-color:var(--primary);border-radius:50%;animation:spin 0.8s linear infinite;vertical-align:middle;margin-right:8px;"></span> Loading...';
  try {{
    const resp = await fetch('/admin/api/session-logs');
    const data = await resp.json();
    const logs = data.logs || [];
    if (logs.length === 0) {{
      document.getElementById('sessionLogContent').innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-dim);">No login records yet.</div>';
      return;
    }}
    const failedCount = logs.filter(l => l.success === 0).length;
    let html = '<div style="margin-bottom:10px;display:flex;gap:16px;flex-wrap:wrap;">'
      + '<span style="color:var(--accent);font-size:0.85em;">Total Logins: <strong style="color:var(--text);">' + logs.length + '</strong></span>'
      + '<span style="color:var(--warning);font-size:0.85em;">Failed: <strong style="color:var(--error);">' + failedCount + '</strong></span>'
      + '</div>';
    html += '<table style="width:100%;border-collapse:collapse;font-size:0.8em;">'
      + '<tr style="background:var(--surface2);color:var(--accent);font-size:0.75em;text-transform:uppercase;letter-spacing:1px;">'
      + '<th style="padding:6px 8px;text-align:left;">Time</th>'
      + '<th style="padding:6px 8px;text-align:left;">Email</th>'
      + '<th style="padding:6px 8px;text-align:left;">User</th>'
      + '<th style="padding:6px 8px;text-align:center;">Status</th>'
      + '<th style="padding:6px 8px;text-align:left;">IP</th>'
      + '<th style="padding:6px 8px;text-align:left;">Details</th>'
      + '</tr>';
    for (const log of logs) {{
      const ts = (log.created_at || '').slice(0, 19).replace('T', ' ');
      const statusIcon = log.success === 1 ? '✅' : '❌';
      const statusColor = log.success === 1 ? 'var(--primary)' : 'var(--error)';
      const userName = log.user_name || '—';
      const details = log.details || '';
      html += '<tr style="border-top:1px solid var(--border);">'
        + '<td style="padding:6px 8px;color:var(--text-dim);white-space:nowrap;">' + ts + '</td>'
        + '<td style="padding:6px 8px;">' + escHtml(log.email || '') + '</td>'
        + '<td style="padding:6px 8px;color:var(--primary);">' + escHtml(userName) + '</td>'
        + '<td style="padding:6px 8px;text-align:center;color:' + statusColor + ';">' + statusIcon + '</td>'
        + '<td style="padding:6px 8px;color:var(--text-dim);font-size:0.9em;">' + escHtml(log.ip_address || '') + '</td>'
        + '<td style="padding:6px 8px;color:var(--text-dim);font-size:0.9em;">' + escHtml(details) + '</td>'
        + '</tr>';
    }}
    html += '</table>';
    document.getElementById('sessionLogContent').innerHTML = html;
  }} catch (err) {{
    document.getElementById('sessionLogContent').innerHTML = '<div style="text-align:center;padding:20px;color:var(--error);">Error: ' + err.message + '</div>';
  }}
}}
</script>
</body></html>"""
        # Build pending section
        if pending_users:
            pending_rows = "".join(
                f'<tr><td>{u["id"]}</td><td>{u["name"]}</td><td>{u["email"]}</td>'
                f'<td><div class="btn-group">'
                f'<button class="btn-approve" onclick="approveUser({u["id"]})">✅ Approve</button>'
                f'<button class="btn-reject" onclick="rejectUser({u["id"]})">✕ Reject</button>'
                f'</div></td></tr>'
                for u in pending_users
            )
            pending_section = f'''
  <div class="section-title">⏳ Pending Approval <span style="font-size:0.7em;color:var(--warning);font-weight:400;">({len(pending_users)} waiting)</span></div>
  <table>
    <tr><th>ID</th><th>Name</th><th>Email</th><th>Actions</th></tr>
    {pending_rows}
  </table>
'''
        else:
            pending_section = '<div class="section-title">⏳ Pending Approval <span style="font-size:0.7em;color:var(--text-dim);font-weight:400;">(none)</span></div><div class="empty">No pending users. All accounts have been processed.</div>'
        
        html = html.replace('{{pending_section}}', pending_section)
        return render_template_string(html)

    @app.route('/admin/api/stats')
    @require_admin
    def admin_stats():
        return jsonify(get_stats())

    @app.route('/admin/api/users')
    @require_admin
    def admin_users():
        return jsonify({'users': get_all_users()})

    @app.route('/admin/api/pending')
    @require_admin
    def admin_pending():
        return jsonify({'pending': get_pending_users()})

    @app.route('/admin/api/approve-user/<int:target_user_id>', methods=['POST'])
    @require_admin
    def admin_approve_user(target_user_id):
        ok = approve_user(target_user_id)
        if ok:
            user = get_user_by_id(target_user_id)
            email = user['email'] if user else ''
            name = user['name'] if user else 'User'
            logger.info(f"Admin approved user: {email}")
            # Send approval notification email
            if email:
                sent = notify_approved(email, name)
                if sent:
                    logger.info(f"Approval email sent to {email}")
                else:
                    logger.info(f"Approval email not sent to {email} (no email service configured)")
            return jsonify({'status': 'ok', 'email_sent': True if email and os.environ.get('RESEND_API_KEY') else False})
        return jsonify({'status': 'error', 'error': 'User not found or already approved'}), 404

    @app.route('/admin/api/reject-user/<int:target_user_id>', methods=['POST'])
    @require_admin
    def admin_reject_user(target_user_id):
        # Get user info BEFORE deleting
        user = get_user_by_id(target_user_id)
        email = user['email'] if user else ''
        name = user['name'] if user else 'User'
        
        ok = reject_user(target_user_id)
        if ok:
            logger.info(f"Admin rejected user: {email or target_user_id}")
            # Send rejection notification email
            if email:
                sent = notify_rejected(email, name)
                if sent:
                    logger.info(f"Rejection email sent to {email}")
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error', 'error': 'User not found or already processed'}), 404

    @app.route('/admin/api/user-apps/<int:target_user_id>')
    @require_admin
    def admin_user_apps(target_user_id):
        apps = get_user_applications(target_user_id, limit=500)
        return jsonify({'applications': apps})

    @app.route('/admin/api/change-password', methods=['POST'])
    @require_admin
    def admin_change_password():
        """Change the current admin's password."""
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'error': 'Invalid request'}), 400
        
        current = data.get('current_password', '')
        new_password = data.get('new_password', '')
        
        if not current or not new_password:
            return jsonify({'status': 'error', 'error': 'Both current and new password are required'}), 400
        if len(new_password) < 6:
            return jsonify({'status': 'error', 'error': 'New password must be at least 6 characters'}), 400
        
        # Verify current password
        from .auth import verify_password, hash_password
        user = get_current_user()
        if not user or not verify_password(current, user.get('password_hash', '')):
            return jsonify({'status': 'error', 'error': 'Current password is incorrect'}), 403
        
        # Update password
        new_hash = hash_password(new_password)
        ok = update_user_password(user['id'], new_hash)
        if ok:
            logger.info(f"Admin password changed for user {user['email']}")
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error', 'error': 'Failed to update password'}), 500

    @app.route('/admin/api/reset-user-password/<int:target_user_id>', methods=['POST'])
    @require_admin
    def admin_reset_user_password(target_user_id):
        """Admin resets any user's password."""
        data = request.get_json()
        if not data or not data.get('password'):
            return jsonify({'status': 'error', 'error': 'Password required'}), 400
        new_password = data['password']
        if len(new_password) < 6:
            return jsonify({'status': 'error', 'error': 'Password must be at least 6 characters'}), 400
        user = get_user_by_id(target_user_id)
        if not user:
            return jsonify({'status': 'error', 'error': 'User not found'}), 404
        new_hash = hash_password(new_password)
        ok = update_user_password(target_user_id, new_hash)
        if ok:
            logger.info(f"Admin reset password for user {user['email']} (id={target_user_id})")
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error', 'error': 'Failed to update password'}), 500

    return app




def _init_persistent_data(config: AppConfig):
    """Initialize persistent data directory with initial files from project.
    On Hugging Face Spaces, copies profiles/ and other data to /data.
    
    Note: On HF Spaces, /profiles and /resume.pdf are symlinked to /data/,
    so reading them through project_root resolves to the (empty) persistent volume.
    We use a non-symlinked backup copy at /app/.default/ as fallback.
    """
    if not config.is_hf_space:
        return

    project_root = Path(__file__).resolve().parent.parent
    data_dir = Path(config.data_dir)

    # Ensure all required subdirectories exist
    for subdir in ['logs', 'logs/sessions', 'profiles']:
        (data_dir / subdir).mkdir(parents=True, exist_ok=True)

    import shutil

    # Helper: try symlinked path first, then fallback to non-symlinked backup
    def _copy_with_fallback(src_rel: str, dst_rel: str, backup_rel: str = None):
        src = project_root / src_rel
        dst = data_dir / dst_rel
        if dst.exists():
            return  # Already initialized
        if src.exists():
            # Source is available (e.g. symlink target exists from previous run)
            shutil.copy2(str(src), str(dst))
            logger.info(f"Copied {src_rel} to {dst}")
        elif backup_rel:
            # Try non-symlinked fallback (Dockerfile copies to /app/.default/)
            backup = project_root / backup_rel
            if backup.exists():
                shutil.copy2(str(backup), str(dst))
                logger.info(f"Copied {backup_rel} (fallback) to {dst}")
            else:
                logger.warning(f"Neither {src_rel} nor {backup_rel} found - skipping")
        else:
            logger.warning(f"{src_rel} not found - skipping")

    # Copy profile template
    _copy_with_fallback('profiles/profile.json', 'profiles/profile.json', '.default/profile.json')

    # Copy existing resume.pdf if present
    _copy_with_fallback('resume.pdf', 'resume.pdf', '.default/resume.pdf')

    # Copy existing applications history if present
    _copy_with_fallback('logs/applications.json', 'logs/applications.json')

    # Copy applied.json if present
    _copy_with_fallback('logs/applied.json', 'logs/applied.json')

    logger.info(f"Persistent data initialized at {data_dir}")


def run_dashboard(config: AppConfig):
    """Run the GUI server and open browser."""
    app = create_dashboard_app(config)
    if app is None:
        logger.error("Failed to create dashboard app")
        return

    host = config.dashboard_host
    port = config.dashboard_port
    url = f"http://{host}:{port}"

    print(f"\n  [NET] Job Agent GUI starting at {url}")
    if not config.anthropic_api_key:
        print(f"  [WARN] ANTHROPIC_API_KEY is not set!")
        print(f"  [WARN] Enter it in the browser GUI (API Key field below the header)")
        print(f"  [WARN] Or restart with: set ANTHROPIC_API_KEY=sk-ant-... && python -m agent dashboard")
        print()
    else:
        print(f"  [OK] ANTHROPIC_API_KEY is configured")
    print(f"  Upload your CV and click 'Run Agent' to start!\n")

    # Open browser automatically
    import webbrowser
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    app.run(host=host, port=port, debug=False, threaded=True)
