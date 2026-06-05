"""
Web GUI for Job Agent.
Provides a cyberpunk-styled interface with CV upload, Run Agent button,
real-time streaming output, and results display.
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

from .config import AppConfig
from .tracker import ApplicationTracker
from .utils import _ensure_dirs

logger = logging.getLogger(__name__)

# ── Background runner ─────────────────────────────────────────────────────────

_output_queue: Optional[queue.Queue] = None
_run_process: Optional[subprocess.Popen] = None
_run_thread: Optional[threading.Thread] = None
_run_complete = False
_run_returncode: Optional[int] = None
_gui_api_key: str = ""  # API key entered via the browser GUI
_uploaded_filename: str = "resume.pdf"  # Actual uploaded CV filename
_dashboard_data_dir: str = "."  # Configurable data directory

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


def _run_agent_in_thread(cwd: str, api_key: str = ""):
    """Run the agent as a subprocess and push output lines to a queue."""
    global _output_queue, _run_process, _run_complete, _run_returncode

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

    global _dashboard_data_dir
    _dashboard_data_dir = config.data_dir

    # Ensure data directories exist
    _ensure_dirs(config.data_dir)

    # On HF Spaces, copy initial files from project to /data if needed
    _init_persistent_data(config)

    tracker = ApplicationTracker(data_dir=config.data_dir)

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

  <!-- Run Button -->
  <div class="run-section">
    <button class="run-btn" id="runBtn" disabled>
      <span class="btn-text">▶ RUN AGENT</span>
    </button>
  </div>

  <!-- Terminal -->
  <div class="terminal-section" id="terminalSection">
    <div class="terminal-header">
      <span class="terminal-dot red"></span>
      <span class="terminal-dot yellow"></span>
      <span class="terminal-dot green"></span>
      <span class="terminal-title">Agent Console</span>
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
      </div>
      <span class="filter-count" id="filterCount"></span>
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

// Check on page load if API key is already set and get uploaded filename
Promise.all([
  fetch('/status').then(r => r.json()),
  fetch('/api/config').then(r => r.json()).catch(() => ({uploaded_filename: 'resume.pdf'}))
]).then(([status, config]) => {
  if (status.api_key_configured) {
    apiKeyStatus.textContent = '✅ Configured';
    apiKeyStatus.className = 'api-key-status configured';
    apiKeyInput.disabled = true;
    document.getElementById('apiKeyBtn').disabled = true;
  }
  // Show the actual uploaded filename if it exists
  if (config.uploaded_filename) {
    fileName.textContent = config.uploaded_filename;
    uploadZone.classList.add('has-file');
    uploadedFile = true;  // Mark as having a file so Run button can be enabled
    if (apiKeyInput.disabled) runBtn.disabled = false;
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

runBtn.addEventListener('click', () => {
  if (eventSource) return;

  runBtn.disabled = true;
  runBtn.classList.add('running');
  const btnText = runBtn.querySelector('.btn-text');
  // Animate button dots with JS (CSS cannot animate content)
  let dotCount = 0;
  const dotTimer = setInterval(() => {
    dotCount = (dotCount + 1) % 4;
    btnText.textContent = '⟳ RUNNING' + '.'.repeat(dotCount);
  }, 500);
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
    // Fetch history and applied set in parallel
    const [histResp, appliedResp] = await Promise.all([
      fetch('/api/history'),
      fetch('/api/applied'),
    ]);
    const data = await histResp.json();
    const appliedData = await appliedResp.json();
    _appliedSet = new Set(appliedData.applied || []);
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

    let actionHtml;
    if (isApplied) {
      actionHtml = `<span class="history-applied">✅ Applied</span>`;
    } else if (jobUrl) {
      const safeUrl = escHtml(jobUrl);
      actionHtml = `<button class="history-apply" data-url="${safeUrl}" onclick="applyToJob(this.dataset.url, this)">🔗 Apply</button>`;
    } else {
      actionHtml = `<span class="history-apply no-url">🔗 No Link</span>`;
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
        <div style="display:flex;flex-direction:column;align-items:center;gap:6px;">${actionHtml}</div>
      </div>`;
  }
  historyContent.innerHTML = html;
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

function escHtml(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}
</script>
</body>
</html>
"""

    # ── Routes ──

    @app.route('/')
    def index():
        return render_template_string(GUI_HTML)

    @app.route('/healthz')
    def healthz():
        """Health check endpoint for HF Spaces."""
        return jsonify({'status': 'ok'})

    @app.route('/upload', methods=['POST'])
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

        # Save to data_dir for persistence (survives container restarts on HF Spaces)
        save_path = Path(config.resume_save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        file.save(str(save_path))
        _uploaded_filename = file.filename

        # Clear old results tracking for a fresh run
        _run_complete = False

        logger.info(f"CV '{_uploaded_filename}' uploaded and saved to {save_path}")
        return jsonify({'status': 'ok', 'filename': _uploaded_filename})

    @app.route('/set-api-key', methods=['POST'])
    def set_api_key():
        global _gui_api_key
        data = request.get_json()
        if not data or 'api_key' not in data:
            return jsonify({'status': 'error', 'error': 'No API key provided'}), 400

        key = data['api_key'].strip()
        if not key.startswith('sk-ant-'):
            return jsonify({'status': 'error', 'error': 'Invalid key format'}), 400

        _gui_api_key = key
        logger.info("API key configured via browser GUI")
        return jsonify({'status': 'ok'})

    @app.route('/run')
    def run_agent():
        global _output_queue, _run_thread, _run_complete, _gui_api_key, _uploaded_filename

        if _run_thread and _run_thread.is_alive():
            return jsonify({'error': 'Agent is already running'}), 409

        # Reset state
        _output_queue = queue.Queue()
        _run_complete = False

        # Use data_dir as the working directory for the subprocess
        project_root = Path(__file__).resolve().parent.parent
        work_dir = str(Path(config.data_dir).resolve())

        def generate():
            global _run_complete
            # Push initial status
            yield f"data: [SYSTEM] Starting agent with CV: {_uploaded_filename}\n\n"
            yield f"data: [SYSTEM] Analyzing resume, generating search keywords...\n\n"

            # Use key from browser GUI first, then fall back to config env var
            api_key = _gui_api_key or config.anthropic_api_key
            thread = threading.Thread(
                target=_run_agent_in_thread,
                args=(work_dir, api_key),
                daemon=True,
            )
            thread.start()
            _run_thread = thread

            while True:
                try:
                    line = _output_queue.get(timeout=1)
                    # Escape SSE formatting
                    safe_line = line.replace('\n', '\\n')
                    yield f"data: {safe_line}\n\n"
                except queue.Empty:
                    if _run_complete:
                        # Drain remaining
                        try:
                            while True:
                                line = _output_queue.get_nowait()
                                safe_line = line.replace('\n', '\\n')
                                yield f"data: {safe_line}\n\n"
                        except queue.Empty:
                            pass
                        yield "data: [SYSTEM] Agent completed.\n\n"
                        break
                    else:
                        # Keep-alive
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
    def get_results():
        data_dir = Path(config.data_dir)
        files = []

        # List generated output files from data_dir
        for pattern in ['jobs_*.docx', 'cv_*.pdf']:
            for f in data_dir.glob(pattern):
                files.append(f.name)

        # Get tracker stats
        stats = tracker.get_stats()

        # Count high-match from the tracker
        high_match = len(tracker.get_high_match(min_score=80))

        return jsonify({
            'files': sorted(files),
            'jobs_found': stats['total_jobs_reviewed'],
            'high_match': high_match,
            'cvs_generated': len([f for f in files if f.startswith('cv_')]),
            'stats': stats,
            'run_complete': _run_complete,
        })

    @app.route('/api/applied', methods=['GET'])
    def get_applied():
        return jsonify({'applied': sorted(_load_applied())})

    @app.route('/api/mark-applied', methods=['POST'])
    def mark_applied():
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'status': 'error', 'error': 'No URL provided'}), 400
        url = data['url'].strip()
        if not url:
            return jsonify({'status': 'error', 'error': 'Empty URL'}), 400
        newly = _mark_applied(url)
        logger.info(f"Job marked as applied: {url[:80]}...")
        return jsonify({'status': 'ok', 'newly_marked': newly})

    @app.route('/api/history')
    def get_history():
        all_jobs = tracker.load_all()
        # Filter out unscored jobs (score=0 means no description was available)
        all_jobs = [j for j in all_jobs if (j.get('ai_score') or 0) > 0]
        # Return most recent first, limit to 200
        all_jobs.reverse()
        return jsonify({'jobs': all_jobs[:200]})

    @app.route('/download/<path:filename>')
    def download_file(filename):
        # Check data_dir first, then fallback to project root
        data_dir = Path(config.data_dir)
        filepath = data_dir / filename
        if filepath.exists() and filepath.is_file():
            return send_file(str(filepath), as_attachment=True)
        # Fallback to project root
        project_root = Path(__file__).resolve().parent.parent
        filepath = project_root / filename
        if filepath.exists() and filepath.is_file():
            return send_file(str(filepath), as_attachment=True)
        return jsonify({'error': 'File not found'}), 404

    @app.route('/status')
    def status():
        s = _agent_status()
        s['api_key_configured'] = bool(_gui_api_key or config.anthropic_api_key)
        s['uploaded_filename'] = _uploaded_filename
        return jsonify(s)

    @app.route('/api/config')
    def api_config():
        return jsonify({
            'uploaded_filename': _uploaded_filename,
            'data_dir': config.data_dir,
            'is_hf_space': config.is_hf_space,
        })

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
