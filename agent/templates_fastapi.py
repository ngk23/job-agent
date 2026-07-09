"""
Shared HTML templates for Job Agent.
Used by both Flask (dashboard.py) and FastAPI (dashboard_fastapi.py).
"""

# ── Login Page ──
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
    --bg: #0a0a0f; --surface: #12121a; --surface2: #1a1a2e; --border: #2a2a4a;
    --primary: #00ff41; --accent: #0ff; --text: #c8c8d0; --text-dim: #666; --error: #ff3355;
  }
  body { font-family: 'Share Tech Mono', monospace; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
  .auth-box { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 40px; width: 100%; max-width: 420px; box-shadow: 0 0 60px rgba(0,255,65,0.05); }
  .auth-box h1 { font-size: 1.8em; text-align: center; margin-bottom: 8px; background: linear-gradient(135deg, var(--primary), var(--accent)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: 3px; text-transform: uppercase; }
  .auth-box .subtitle { text-align: center; color: var(--text-dim); font-size: 0.8em; margin-bottom: 30px; letter-spacing: 1px; }
  .auth-box label { display: block; font-size: 0.75em; color: var(--text-dim); letter-spacing: 1px; text-transform: uppercase; margin-bottom: 6px; margin-top: 16px; }
  .auth-box input { width: 100%; padding: 12px 14px; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text); font-family: 'Share Tech Mono', monospace; font-size: 0.9em; outline: none; transition: border-color 0.2s; }
  .auth-box input:focus { border-color: var(--primary); box-shadow: 0 0 10px rgba(0,255,65,0.15); }
  .auth-btn { width: 100%; padding: 14px; margin-top: 24px; background: transparent; border: 2px solid var(--primary); border-radius: 8px; color: var(--primary); font-family: 'Share Tech Mono', monospace; font-size: 1em; font-weight: 700; letter-spacing: 3px; text-transform: uppercase; cursor: pointer; transition: all 0.3s; }
  .auth-btn:hover { background: rgba(0,255,65,0.08); box-shadow: 0 0 20px rgba(0,255,65,0.2); }
  .auth-error { color: var(--error); font-size: 0.8em; text-align: center; margin-top: 12px; padding: 8px; background: rgba(255,51,85,0.08); border: 1px solid rgba(255,51,85,0.2); border-radius: 4px; display: none; }
  .auth-link { text-align: center; margin-top: 20px; font-size: 0.8em; color: var(--text-dim); }
  .auth-link a { color: var(--accent); text-decoration: none; } .auth-link a:hover { text-decoration: underline; }
  .google-btn { display: inline-flex; align-items: center; justify-content: center; padding: 10px 20px; background: #fff; border: 1px solid #dadce0; border-radius: 4px; color: #3c4043; font-family: 'Share Tech Mono', monospace; font-size: 0.85em; font-weight: 600; text-decoration: none; cursor: pointer; transition: all 0.2s; letter-spacing: 0.25px; }
  .google-btn:hover { background: #f8f9fa; box-shadow: 0 1px 3px rgba(0,0,0,0.15); border-color: #c6c6c6; }
  .hack-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.92); z-index: 9999; font-family: 'Share Tech Mono', monospace; overflow: hidden; }
  .hack-overlay.active { display: flex; flex-direction: column; align-items: center; justify-content: center; }
  #hackCanvas { position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: -1; opacity: 0.15; }
  .hack-terminal { background: rgba(0, 20, 0, 0.6); border: 1px solid var(--primary); border-radius: 8px; padding: 24px; width: 90%; max-width: 600px; max-height: 70vh; overflow: hidden; box-shadow: 0 0 40px rgba(0, 255, 65, 0.15); position: relative; }
  .hack-terminal-header { display: flex; align-items: center; gap: 8px; padding-bottom: 12px; border-bottom: 1px solid rgba(0, 255, 65, 0.2); margin-bottom: 12px; }
  .hack-dot { width: 10px; height: 10px; border-radius: 50%; } .hack-dot.red { background: #ff5f56; } .hack-dot.yellow { background: #ffbd2e; } .hack-dot.green { background: #27c93f; }
  .hack-terminal-title { color: var(--text-dim); font-size: 0.8em; letter-spacing: 2px; margin-left: 8px; }
  .hack-output { font-size: 0.85em; line-height: 1.6; color: var(--primary); min-height: 200px; max-height: 50vh; overflow-y: auto; padding: 4px 0; }
  .hack-output .line { opacity: 0; white-space: pre-wrap; word-break: break-all; animation: hackFadeIn 0.3s ease forwards; }
  .hack-output .line.success { color: var(--primary); } .hack-output .line.warning { color: #ffaa00; } .hack-output .line.error { color: var(--error); } .hack-output .line.info { color: var(--accent); } .hack-output .line.dim { color: var(--text-dim); } .hack-output .line.highlight { color: #f0f; }
  @keyframes hackFadeIn { to { opacity: 1; } }
  .hack-progress { margin-top: 16px; width: 100%; height: 4px; background: rgba(0, 255, 65, 0.1); border-radius: 2px; overflow: hidden; }
  .hack-progress-bar { height: 100%; width: 0%; background: linear-gradient(90deg, var(--primary), var(--accent)); border-radius: 2px; transition: width 0.3s ease; box-shadow: 0 0 10px rgba(0, 255, 65, 0.5); }
  .hack-cursor { display: inline-block; width: 8px; height: 14px; background: var(--primary); animation: hackBlink 0.8s step-end infinite; margin-left: 2px; vertical-align: middle; }
  @keyframes hackBlink { 50% { opacity: 0; } }
  .hack-granted { margin-top: 12px; font-size: 0.9em; text-align: center; display: none; letter-spacing: 3px; text-transform: uppercase; }
  .hack-granted.active { display: block; color: var(--primary); text-shadow: 0 0 20px rgba(0, 255, 65, 0.5); animation: hackPulse 0.5s ease-in-out 3; }
  @keyframes hackPulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.7; transform: scale(1.05); } }
</style>
</head>
<body>
<div class="auth-box">
  <h1>Job Agent</h1>
  <div class="subtitle">Sign in to your account</div>
  {pending_msg}
  <form action="/login" method="post" onsubmit="return handleLogin(event)">
    <label>Email</label>
    <input type="email" id="loginEmail" name="email" placeholder="you@example.com" required autocomplete="email">
    <label>Password</label>
    <input type="password" id="loginPassword" name="password" placeholder="&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;" required autocomplete="current-password">
    <button type="submit" class="auth-btn">SIGN IN</button>
    <div class="auth-error" id="loginError"></div>
  </form>
  <div class="auth-link">Don't have an account? <a href="/signup">Sign up</a></div>
  <div style="text-align:center;margin-top:10px;font-size:0.75em;"><a href="/forgot-password" style="color:var(--text-dim);text-decoration:none;">Forgot password?</a></div>
  <div style="text-align:center;margin-top:16px;padding-top:16px;border-top:1px solid var(--border);">
    <a href="/login/google" class="google-btn">
      <svg style="width:18px;height:18px;vertical-align:middle;margin-right:8px;" viewBox="0 0 24 24">
        <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/>
        <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
        <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
        <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
      </svg>
      Sign in with Google
    </a>
  </div>
</div>

<script>
async function handleLogin(e) {
  e.preventDefault();
  const email = document.getElementById('loginEmail').value.trim();
  const password = document.getElementById('loginPassword').value;
  const errorEl = document.getElementById('loginError');
  try {
    const resp = await fetch('/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
    const data = await resp.json();
    if (data.status === 'ok') { await showHackAnimation(email); window.location.href = '/'; }
    else { errorEl.textContent = data.error || 'Login failed'; errorEl.style.display = 'block'; }
  } catch (err) { errorEl.textContent = 'Error: ' + err.message; errorEl.style.display = 'block'; }
  return false;
}
function getHackLines(email) {
  return [
    { text: '[INIT] Establishing secure connection...', cls: 'info', delay: 100 },
    { text: '[OK]  Handshake complete (TLS 1.3)', cls: 'success', delay: 200 },
    { text: '[INIT] Locating target...', cls: 'info', delay: 150 },
    { text: '[!]   Target: ' + email, cls: 'warning', delay: 250 },
    { text: '[INIT] Scanning access points...', cls: 'info', delay: 120 },
    { text: '[!]   Firewall: SKYNET-ASM v4.2', cls: 'warning', delay: 200 },
    { text: '[INIT] Deploying bypass payload...', cls: 'info', delay: 150 },
    { text: '[OK]  IPS/IDS evasion successful', cls: 'success', delay: 250 },
    { text: '[INIT] Cracking credential vault...', cls: 'info', delay: 180 },
    { text: '[OK]  Decryption key obtained', cls: 'success', delay: 200 },
    { text: '[INIT] Injecting session token...', cls: 'info', delay: 150 },
    { text: '[OK]  Privilege escalation: ROOT', cls: 'success', delay: 250 },
    { text: '[INIT] Masking trace route...', cls: 'info', delay: 120 },
    { text: '[OK]  Proxy chain: ACTIVE', cls: 'success', delay: 200 },
    { text: '[SYS] Connection secured. Redirecting...', cls: 'highlight', delay: 300 },
  ];
}
async function showHackAnimation(email) {
  const overlay = document.getElementById('hackOverlay');
  const output = document.getElementById('hackOutput');
  const progressBar = document.getElementById('hackProgressBar');
  const granted = document.getElementById('hackGranted');
  overlay.classList.add('active'); output.innerHTML = ''; progressBar.style.width = '0%'; granted.classList.remove('active'); granted.style.display = 'none';
  const canvas = document.getElementById('hackCanvas'); const ctx = canvas.getContext('2d');
  canvas.width = window.innerWidth; canvas.height = window.innerHeight;
  const cols = Math.floor(canvas.width / 14); const drops = Array(cols).fill(1);
  const chars = 'ABCDEF0123456789<>!@#$%^&*()_+-=[]{}|;:,./<>?~`';
  function drawMatrix() { ctx.fillStyle = 'rgba(0, 0, 0, 0.05)'; ctx.fillRect(0, 0, canvas.width, canvas.height); ctx.fillStyle = '#00ff41'; ctx.font = '14px monospace';
    for (let i = 0; i < drops.length; i++) { const char = chars[Math.floor(Math.random() * chars.length)]; ctx.fillText(char, i * 14, drops[i] * 14); if (drops[i] * 14 > canvas.height && Math.random() > 0.975) drops[i] = 0; drops[i]++; } }
  const matrixInterval = setInterval(drawMatrix, 50);
  const lines = getHackLines(email);
  for (let i = 0; i < lines.length; i++) { const line = lines[i]; const div = document.createElement('div'); div.className = 'line ' + line.cls; div.textContent = line.text; output.appendChild(div); output.scrollTop = output.scrollHeight; progressBar.style.width = Math.round(((i + 1) / lines.length) * 100) + '%'; await new Promise(r => setTimeout(r, line.delay)); }
  granted.style.display = 'block'; granted.classList.add('active');
  await new Promise(r => setTimeout(r, 800)); clearInterval(matrixInterval); overlay.classList.remove('active');
}
</script>
<div class="hack-overlay" id="hackOverlay">
  <canvas id="hackCanvas"></canvas>
  <div class="hack-terminal">
    <div class="hack-terminal-header"><span class="hack-dot red"></span><span class="hack-dot yellow"></span><span class="hack-dot green"></span><span class="hack-terminal-title">ACCESS TERMINAL v2.1</span></div>
    <div class="hack-output" id="hackOutput"></div>
    <div class="hack-progress"><div class="hack-progress-bar" id="hackProgressBar"></div></div>
    <div class="hack-granted" id="hackGranted">ACCESS GRANTED</div>
  </div>
</div>
</body>
</html>"""


# ── Signup Page ──
SIGNUP_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Job Agent - Sign Up</title>
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
  .auth-error { color: var(--error); font-size: 0.8em; text-align: center; margin-top: 12px; padding: 8px; background: rgba(255,51,85,0.08); border: 1px solid rgba(255,51,85,0.2); border-radius: 4px; display: none; }
  .auth-link { text-align: center; margin-top: 20px; font-size: 0.8em; color: var(--text-dim); } .auth-link a { color: var(--accent); text-decoration: none; } .auth-link a:hover { text-decoration: underline; }
  .hack-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.92); z-index: 9999; font-family: 'Share Tech Mono', monospace; overflow: hidden; }
  .hack-overlay.active { display: flex; flex-direction: column; align-items: center; justify-content: center; }
  #hackCanvas { position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: -1; opacity: 0.15; }
  .hack-terminal { background: rgba(0, 20, 0, 0.6); border: 1px solid var(--primary); border-radius: 8px; padding: 24px; width: 90%; max-width: 600px; }
  .hack-terminal-header { display: flex; align-items: center; gap: 8px; padding-bottom: 12px; border-bottom: 1px solid rgba(0,255,65,0.2); margin-bottom: 12px; }
  .hack-dot { width: 10px; height: 10px; border-radius: 50%; } .hack-dot.red { background: #ff5f56; } .hack-dot.yellow { background: #ffbd2e; } .hack-dot.green { background: #27c93f; }
  .hack-terminal-title { color: var(--text-dim); font-size: 0.8em; letter-spacing: 2px; margin-left: 8px; }
  .hack-output { font-size: 0.85em; line-height: 1.6; color: var(--primary); min-height: 200px; max-height: 50vh; overflow-y: auto; padding: 4px 0; }
  .hack-output .line { opacity: 0; white-space: pre-wrap; word-break: break-all; animation: hackFadeIn 0.3s ease forwards; }
  .hack-output .line.success { color: var(--primary); } .hack-output .line.warning { color: #ffaa00; } .hack-output .line.error { color: var(--error); } .hack-output .line.info { color: var(--accent); } .hack-output .line.dim { color: var(--text-dim); } .hack-output .line.highlight { color: #f0f; }
  @keyframes hackFadeIn { to { opacity: 1; } }
  .hack-progress { margin-top: 16px; width: 100%; height: 4px; background: rgba(0, 255, 65, 0.1); border-radius: 2px; overflow: hidden; }
  .hack-progress-bar { height: 100%; width: 0%; background: linear-gradient(90deg, var(--primary), var(--accent)); border-radius: 2px; transition: width 0.3s ease; }
  .hack-granted { margin-top: 12px; font-size: 0.9em; text-align: center; display: none; letter-spacing: 3px; text-transform: uppercase; }
  .hack-granted.active { display: block; color: var(--primary); text-shadow: 0 0 20px rgba(0, 255, 65, 0.5); animation: hackPulse 0.5s ease-in-out 3; }
  @keyframes hackPulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.7; transform: scale(1.05); } }
</style>
</head>
<body>
<div class="auth-box">
  <h1>Job Agent</h1>
  <div class="subtitle">Create your account</div>
  <form id="signupForm" onsubmit="return handleSignup(event)">
    <label>Full Name</label><input type="text" id="signupName" placeholder="Your Name" required autocomplete="name">
    <label>Email</label><input type="email" id="signupEmail" placeholder="you@example.com" required autocomplete="email">
    <label>Password</label><input type="password" id="signupPassword" placeholder="At least 6 characters" required minlength="6" autocomplete="new-password">
    <button type="submit" class="auth-btn">CREATE ACCOUNT</button>
    <div class="auth-error" id="signupError"></div>
  </form>
  <div class="auth-link">Already have an account? <a href="/login">Sign in</a></div>
</div>

<script>
async function handleSignup(e) {
  e.preventDefault();
  const name = document.getElementById('signupName').value.trim();
  const email = document.getElementById('signupEmail').value.trim();
  const password = document.getElementById('signupPassword').value;
  const errorEl = document.getElementById('signupError');
  if (!name || !email || !password) { errorEl.textContent = 'All fields are required'; errorEl.style.display = 'block'; return false; }
  if (password.length < 6) { errorEl.textContent = 'Password must be at least 6 characters'; errorEl.style.display = 'block'; return false; }
  try {
    const resp = await fetch('/signup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, email, password }) });
    const data = await resp.json();
    if (data.status === 'ok') { await showHackAnimation(email); window.location.href = '/'; }
    else if (data.status === 'pending_approval') {
      document.getElementById('signupForm').style.display = 'none'; errorEl.style.display = 'none';
      const msg = document.createElement('div'); msg.style.cssText = 'text-align:center;padding:20px 0;';
      msg.innerHTML = '<div style="font-size:2em;margin-bottom:12px;">\u23f3</div><div style="color:var(--primary);font-size:1em;margin-bottom:8px;">Account Created!</div><div style="color:var(--text-dim);font-size:0.85em;line-height:1.5;">Your account is pending admin approval.<br>An admin will activate your account shortly.<br><br><a href="/login" style="color:var(--accent);">Back to login</a></div>';
      document.querySelector('.auth-box').appendChild(msg);
    }
    else { errorEl.textContent = data.error || 'Sign up failed'; errorEl.style.display = 'block'; }
  } catch (err) { errorEl.textContent = 'Error: ' + err.message; errorEl.style.display = 'block'; }
  return false;
}
function getHackLines(email) { return [
  { text: '[INIT] Establishing secure connection...', cls: 'info', delay: 100 },
  { text: '[OK]  Handshake complete', cls: 'success', delay: 200 },
  { text: '[INIT] Registering new identity...', cls: 'info', delay: 150 },
  { text: '[!]   Creating profile: ' + email, cls: 'warning', delay: 250 },
  { text: '[INIT] Generating keys...', cls: 'info', delay: 120 },
  { text: '[OK]  RSA-4096 keypair ready', cls: 'success', delay: 200 },
  { text: '[INIT] Encrypting data vault...', cls: 'info', delay: 150 },
  { text: '[OK]  AES-256-GCM active', cls: 'success', delay: 250 },
  { text: '[INIT] Registering with directory...', cls: 'info', delay: 180 },
  { text: '[OK]  Identity verified', cls: 'success', delay: 200 },
  { text: '[INIT] Configuring credentials...', cls: 'info', delay: 150 },
  { text: '[OK]  MFA enabled', cls: 'success', delay: 250 },
  { text: '[SYS] Identity established. Redirecting...', cls: 'highlight', delay: 300 },
];}
async function showHackAnimation(email) {
  const overlay = document.getElementById('hackOverlay'); const output = document.getElementById('hackOutput'); const progressBar = document.getElementById('hackProgressBar'); const granted = document.getElementById('hackGranted');
  overlay.classList.add('active'); output.innerHTML = ''; progressBar.style.width = '0%'; granted.classList.remove('active'); granted.style.display = 'none';
  const canvas = document.getElementById('hackCanvas'); const ctx = canvas.getContext('2d'); canvas.width = window.innerWidth; canvas.height = window.innerHeight;
  const cols = Math.floor(canvas.width / 14); const drops = Array(cols).fill(1); const chars = 'ABCDEF0123456789<>!@#$%^&*()_+-=[]{}|;:,./<>?~`';
  function drawMatrix() { ctx.fillStyle = 'rgba(0,0,0,0.05)'; ctx.fillRect(0,0,canvas.width,canvas.height); ctx.fillStyle = '#00ff41'; ctx.font = '14px monospace';
    for (let i = 0; i < drops.length; i++) { const c = chars[Math.floor(Math.random()*chars.length)]; ctx.fillText(c, i*14, drops[i]*14); if (drops[i]*14 > canvas.height && Math.random() > 0.975) drops[i] = 0; drops[i]++; } }
  const matrixInterval = setInterval(drawMatrix, 50);
  const lines = getHackLines(email);
  for (let i = 0; i < lines.length; i++) { const l = lines[i]; const d = document.createElement('div'); d.className = 'line ' + l.cls; d.textContent = l.text; output.appendChild(d); output.scrollTop = output.scrollHeight; progressBar.style.width = Math.round(((i+1)/lines.length)*100) + '%'; await new Promise(r => setTimeout(r, l.delay)); }
  granted.style.display = 'block'; granted.classList.add('active');
  await new Promise(r => setTimeout(r, 800)); clearInterval(matrixInterval); overlay.classList.remove('active');
}
</script>
<div class="hack-overlay" id="hackOverlay">
  <canvas id="hackCanvas"></canvas>
  <div class="hack-terminal">
    <div class="hack-terminal-header"><span class="hack-dot red"></span><span class="hack-dot yellow"></span><span class="hack-dot green"></span><span class="hack-terminal-title">ACCESS TERMINAL v2.1</span></div>
    <div class="hack-output" id="hackOutput"></div>
    <div class="hack-progress"><div class="hack-progress-bar" id="hackProgressBar"></div></div>
    <div class="hack-granted" id="hackGranted">ACCESS GRANTED</div>
  </div>
</div>
</body>
</html>"""


# ── Main GUI Dashboard ──
GUI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Job Agent - AI Job Search</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Inter:wght@400;600;700&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root { --bg: #0a0a0f; --surface: #12121a; --surface2: #1a1a2e; --border: #2a2a4a; --primary: #00ff41; --primary-dim: #00cc33; --accent: #0ff; --accent2: #f0f; --text: #c8c8d0; --text-dim: #666; --error: #ff3355; --warning: #ffaa00; }
  body { font-family: 'Share Tech Mono', monospace; background: var(--bg); color: var(--text); min-height: 100vh; overflow-x: hidden; }
  #matrixCanvas { position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 0; pointer-events: none; opacity: 0.08; }
  .container { position: relative; z-index: 1; max-width: 1000px; margin: 0 auto; padding: 30px 20px; }
  header { text-align: center; padding: 40px 0 30px; border-bottom: 1px solid var(--border); margin-bottom: 30px; }
  header h1 { font-size: 2.5em; font-weight: 700; background: linear-gradient(135deg, var(--primary), var(--accent), var(--accent2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; text-shadow: 0 0 40px rgba(0,255,65,0.2); letter-spacing: 4px; text-transform: uppercase; }
  header p { color: var(--text-dim); margin-top: 8px; font-size: 0.9em; letter-spacing: 2px; }
  header .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--primary); margin-right: 6px; animation: pulse-dot 2s infinite; }
  @keyframes pulse-dot { 0%, 100% { opacity: 1; box-shadow: 0 0 6px var(--primary); } 50% { opacity: 0.4; } }
  .user-bar { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 20px; margin-bottom: 20px; display: flex; align-items: center; gap: 12px; font-size: 0.8em; }
  .user-bar .user-name { color: var(--primary); font-weight: bold; } .user-bar .user-email { color: var(--text-dim); font-size: 0.9em; } .user-bar .user-spacer { flex: 1; }
  .user-bar a { color: var(--accent); text-decoration: none; padding: 4px 12px; border: 1px solid var(--border); border-radius: 4px; transition: all 0.2s; }
  .user-bar a:hover { border-color: var(--accent); background: rgba(0,255,255,0.08); }
  .user-bar .logout-btn { background: transparent; border: 1px solid var(--text-dim); border-radius: 4px; color: var(--text-dim); font-family: 'Share Tech Mono', monospace; font-size: 0.85em; padding: 4px 12px; cursor: pointer; transition: all 0.2s; }
  .user-bar .logout-btn:hover { border-color: var(--error); color: var(--error); }
  .upload-section { background: var(--surface); border: 2px dashed var(--border); border-radius: 16px; padding: 40px; text-align: center; transition: all 0.3s; margin-bottom: 24px; cursor: pointer; }
  .upload-section:hover, .upload-section.drag-over { border-color: var(--primary); background: var(--surface2); box-shadow: 0 0 30px rgba(0,255,65,0.1); }
  .upload-section.has-file { border-color: var(--primary); border-style: solid; background: var(--surface2); }
  .upload-section h3 { color: var(--text); font-size: 1.1em; margin-bottom: 6px; }
  .upload-section p { color: var(--text-dim); font-size: 0.85em; }
  .upload-section .file-info { display: none; margin-top: 12px; padding: 10px 16px; background: rgba(0,255,65,0.08); border: 1px solid var(--primary); border-radius: 8px; color: var(--primary); font-size: 0.9em; }
  .upload-section.has-file .file-info { display: inline-block; } .upload-section.has-file .upload-prompt { display: none; }
  #fileInput { display: none; }
  .region-section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 24px; margin-bottom: 20px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .region-label { color: var(--accent); font-size: 0.9em; letter-spacing: 1px; }
  .region-select { flex: 1; min-width: 220px; padding: 10px 14px; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text); font-family: 'Share Tech Mono', monospace; font-size: 0.85em; cursor: pointer; outline: none; appearance: none; }
  .region-select:focus { border-color: var(--accent); box-shadow: 0 0 12px rgba(0,255,255,0.15); }
  .region-select option, .region-select optgroup { background: var(--surface2); color: var(--text); }
  .region-status { font-size: 0.85em; color: var(--primary); padding: 4px 12px; background: rgba(0,255,65,0.06); border: 1px solid rgba(0,255,65,0.2); border-radius: 4px; }
  .run-section { text-align: center; margin-bottom: 24px; display: flex; gap: 12px; justify-content: center; align-items: center; flex-wrap: wrap; }
  .run-btn { font-family: 'Share Tech Mono', monospace; font-size: 1.1em; font-weight: 700; letter-spacing: 3px; text-transform: uppercase; padding: 16px 48px; border: 2px solid var(--primary); border-radius: 8px; background: transparent; color: var(--primary); cursor: pointer; transition: all 0.3s; }
  .run-btn:hover { background: rgba(0,255,65,0.08); box-shadow: 0 0 30px rgba(0,255,65,0.3); transform: translateY(-2px); }
  .run-btn:disabled { border-color: var(--text-dim); color: var(--text-dim); cursor: not-allowed; }
  .run-btn.running { animation: btn-pulse 1.5s infinite; }
  @keyframes btn-pulse { 0%, 100% { box-shadow: 0 0 10px rgba(0,255,65,0.3); } 50% { box-shadow: 0 0 40px rgba(0,255,65,0.6); } }
  .stop-btn { font-family: 'Share Tech Mono', monospace; font-size: 1em; font-weight: 700; padding: 16px 36px; border: 2px solid var(--error); border-radius: 8px; background: transparent; color: var(--error); cursor: pointer; display: none; }
  .stop-btn.visible { display: inline-block; }
  .stop-btn:hover { background: rgba(255,51,85,0.12); box-shadow: 0 0 25px rgba(255,51,85,0.3); }
  .terminal-section { background: #050510; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; margin-bottom: 24px; display: none; }
  .terminal-section.active { display: block; }
  .terminal-header { background: var(--surface); padding: 10px 16px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 8px; }
  .terminal-dot { width: 10px; height: 10px; border-radius: 50%; } .terminal-dot.red { background: #ff5f56; } .terminal-dot.yellow { background: #ffbd2e; } .terminal-dot.green { background: #27c93f; }
  .terminal-title { color: var(--text-dim); font-size: 0.8em; margin-left: 8px; }
  .terminal-body { padding: 16px; height: 350px; overflow-y: auto; font-size: 0.85em; line-height: 1.5; color: var(--primary); }
  .terminal-line { white-space: pre-wrap; word-break: break-all; opacity: 0; animation: fadeInLine 0.3s ease forwards; }
  @keyframes fadeInLine { to { opacity: 1; } }
  .terminal-line.system { color: var(--accent); } .terminal-line.error { color: var(--error); } .terminal-line.ok { color: var(--primary); }
  .terminal-cursor { display: inline-block; width: 8px; height: 14px; background: var(--primary); animation: blink 1s step-end infinite; margin-left: 2px; }
  @keyframes blink { 50% { opacity: 0; } }
  .results-section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 24px; display: none; margin-bottom: 24px; }
  .results-section.active { display: block; }
  .results-section h2 { color: var(--primary); font-size: 1.2em; margin-bottom: 16px; letter-spacing: 2px; text-transform: uppercase; }
  .results-section h2::before { content: '> '; color: var(--accent); }
  .results-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .result-stat { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; text-align: center; }
  .result-stat .value { font-size: 2em; font-weight: 700; color: var(--primary); }
  .result-stat .label { font-size: 0.75em; color: var(--text-dim); margin-top: 4px; text-transform: uppercase; }
  .result-files { display: flex; flex-wrap: wrap; gap: 8px; }
  .result-file { display: inline-flex; align-items: center; gap: 8px; padding: 8px 16px; background: var(--surface2); border: 1px solid var(--border); border-radius: 6px; color: var(--text); text-decoration: none; font-size: 0.85em; transition: all 0.2s; }
  .result-file:hover { border-color: var(--primary); color: var(--primary); }
  .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid var(--border); border-top-color: var(--primary); border-radius: 50%; animation: spin 0.8s linear infinite; vertical-align: middle; margin-right: 8px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .history-toggle { display: block; width: 100%; padding: 12px 20px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; color: var(--accent); font-family: 'Share Tech Mono', monospace; font-size: 0.95em; cursor: pointer; margin-bottom: 24px; text-align: center; }
  .history-toggle:hover { border-color: var(--accent); background: var(--surface2); }
  .history-section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; display: none; margin-bottom: 24px; max-height: 500px; overflow-y: auto; }
  .history-section.active { display: block; }
  .history-item { display: flex; align-items: center; gap: 12px; padding: 12px; border-bottom: 1px solid var(--border); }
  .history-item:hover { background: var(--surface2); }
  .history-score { min-width: 48px; height: 48px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 1em; color: #fff; }
  .history-score.high { background: #10b981; } .history-score.mid { background: #f59e0b; } .history-score.low { background: #ef4444; }
  .history-info { flex: 1; min-width: 0; }
  .history-info .title { font-size: 0.9em; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .history-info .company { font-size: 0.8em; color: var(--accent); margin-top: 2px; }
  .history-info .meta { font-size: 0.7em; color: var(--text-dim); margin-top: 2px; display: flex; gap: 10px; }
  .history-platform { padding: 2px 8px; border-radius: 4px; background: var(--surface2); color: var(--text-dim); font-size: 0.7em; text-transform: uppercase; }
  .history-skills { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
  .history-skill-tag { background: rgba(0,255,65,0.1); color: var(--primary); padding: 2px 8px; border-radius: 10px; font-size: 0.7em; }
  .history-empty { text-align: center; padding: 40px; color: var(--text-dim); }
  .history-apply { display: inline-flex; align-items: center; gap: 4px; padding: 4px 12px; background: rgba(0,255,255,0.1); border: 1px solid var(--accent); border-radius: 4px; color: var(--accent); font-family: 'Share Tech Mono', monospace; font-size: 0.72em; text-decoration: none; cursor: pointer; white-space: nowrap; }
  .history-apply:hover { background: rgba(0,255,255,0.25); }
  .history-applied { display: inline-flex; align-items: center; gap: 4px; padding: 4px 12px; background: rgba(0,255,65,0.12); border: 1px solid var(--primary); border-radius: 4px; color: var(--primary); font-size: 0.72em; cursor: default; }
  .history-loading { text-align: center; padding: 20px; color: var(--text-dim); }
  .history-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 12px 0; margin-bottom: 8px; border-bottom: 1px solid var(--border); }
  .filter-group { display: flex; align-items: center; gap: 6px; }
  .filter-label { color: var(--text-dim); font-size: 0.75em; text-transform: uppercase; }
  .filter-select { padding: 4px 8px; background: var(--bg); border: 1px solid var(--border); border-radius: 4px; color: var(--text); font-family: 'Share Tech Mono', monospace; font-size: 0.78em; cursor: pointer; }
  .filter-select:focus { border-color: var(--accent); }
  .filter-count { margin-left: auto; color: var(--text-dim); font-size: 0.75em; }
  .filter-count .num { color: var(--accent); font-weight: 700; }
  .clear-history-btn { padding: 4px 12px; background: transparent; border: 1px solid var(--warning); border-radius: 4px; color: var(--warning); font-family: 'Share Tech Mono', monospace; font-size: 0.72em; cursor: pointer; }
  .clear-history-btn:hover { background: rgba(255,170,0,0.12); }
  .history-save { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; background: transparent; border: 1px solid var(--border); border-radius: 4px; color: var(--text-dim); font-size: 0.72em; cursor: pointer; }
  .history-save:hover { border-color: var(--warning); color: var(--warning); }
  .history-save.saved { border-color: var(--warning); color: var(--warning); background: rgba(255,170,0,0.12); }
  .history-save.disabled { opacity: 0.3; cursor: not-allowed; }
  .fb-btn { display: inline-flex; align-items: center; justify-content: center; padding: 4px 8px; background: transparent; border: 1px solid var(--border); border-radius: 4px; color: var(--text-dim); font-family: 'Share Tech Mono', monospace; font-size: 0.8em; cursor: pointer; }
  .fb-btn:hover { border-color: var(--accent); background: rgba(0,255,255,0.06); }
  .fb-btn.up:hover { border-color: var(--primary); color: var(--primary); }
  .fb-btn.down:hover { border-color: var(--error); color: var(--error); }
  .fb-btn.active.up { border-color: var(--primary); color: var(--primary); background: rgba(0,255,65,0.15); }
  .fb-btn.active.down { border-color: var(--error); color: var(--error); background: rgba(255,51,85,0.15); }
  .feedback-summary { display: flex; align-items: center; gap: 16px; padding: 10px 20px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 20px; font-size: 0.8em; }
  .feedback-summary .fs-label { color: var(--text-dim); letter-spacing: 1px; text-transform: uppercase; font-size: 0.75em; }
  .feedback-summary .fs-stats { display: flex; gap: 14px; flex: 1; }
  .fs-stat .num.up { color: var(--primary); } .fs-stat .num.down { color: var(--error); } .fs-stat .num.rate { color: var(--accent); }
  .feedback-summary .fs-empty { color: var(--text-dim); font-style: italic; }
  @media (max-width: 600px) { header h1 { font-size: 1.5em; } .run-btn { padding: 14px 24px; font-size: 0.9em; } .terminal-body { height: 250px; } }
</style>
</head>
<body>
<canvas id="matrixCanvas"></canvas>
<div class="container">
  <header><h1>Job Agent</h1><p><span class="status-dot"></span> AI-Powered Job Search &bull; CV Generator</p></header>
  <div class="user-bar"><span>👤</span><span class="user-name">{{ user.name }}</span><span class="user-email">{{ user.email }}</span><span class="user-spacer"></span>{% if user.role == 'admin' %}<a href="/admin">🛡️ Admin</a>{% endif %}<a href="/change-password">🔑 Change PW</a><button class="logout-btn" onclick="logoutUser()">🚪 Logout</button></div>
  <div class="feedback-summary" id="feedbackSummary"><span class="fs-label">Your Feedback:</span><div class="fs-loading" id="fsLoading">Loading...</div><div class="fs-stats" id="fsStats" style="display:none;"><span class="fs-stat"><span class="num up" id="fsUp">0</span> <span class="lbl">Good</span></span><span class="fs-stat"><span class="num down" id="fsDown">0</span> <span class="lbl">Skip</span></span><span class="fs-stat"><span class="num rate" id="fsRate">0%</span> <span class="lbl">Positivity</span></span></div><div class="fs-empty" id="fsEmpty" style="display:none;">No ratings yet</div></div>
  <div class="upload-section" id="uploadZone"><div class="upload-prompt"><span style="font-size:3em">📄</span><h3>Drop your CV here or click to upload</h3><p>Supports PDF format (max 10MB)</p></div><div class="file-info"><span id="fileName">resume.pdf</span> loaded</div><input type="file" id="fileInput" accept=".pdf"></div>
  <div class="region-section"><label class="region-label">🌍 Region:</label><select class="region-select" id="regionSelect" onchange="setRegion(this.value)"><optgroup label="Broad Regions"><option value="Remote" selected>Remote (Worldwide)</option><option value="Europe">All Europe</option></optgroup><optgroup label="Western Europe"><option value="Germany">Germany</option><option value="France">France</option><option value="United Kingdom">United Kingdom</option><option value="Netherlands">Netherlands</option><option value="Switzerland">Switzerland</option><option value="Ireland">Ireland</option></optgroup><optgroup label="North America"><option value="United States">United States</option><option value="Canada">Canada</option></optgroup><optgroup label="Asia Pacific"><option value="India">India</option><option value="Australia">Australia</option><option value="Singapore">Singapore</option><option value="Japan">Japan</option></optgroup></select><span class="region-status" id="regionStatus">🌐 Remote</span></div>
  <div class="run-section"><button class="run-btn" id="runBtn" disabled><span class="btn-text">▶ RUN AGENT</span></button><button class="stop-btn" id="stopBtn" onclick="stopAgent()">■ STOP</button></div>
  <div class="terminal-section" id="terminalSection"><div class="terminal-header"><span class="terminal-dot red"></span><span class="terminal-dot yellow"></span><span class="terminal-dot green"></span><span class="terminal-title" id="terminalTitle">Agent Console</span></div><div class="terminal-body" id="terminalBody"><span class="terminal-cursor"></span></div></div>
  <div class="results-section" id="resultsSection"><h2>Results</h2><div class="results-grid" id="resultsGrid"></div><div class="result-files" id="resultFiles"></div></div>
  <button class="history-toggle" id="historyToggle" onclick="toggleHistory()">📋 VIEW SCORING HISTORY</button>
  <div class="history-section" id="historySection">
    <div class="history-filters" id="historyFilters" style="display:none;">
      <div class="filter-group"><span class="filter-label">Sort:</span><select class="filter-select" id="sortSelect" onchange="applyFiltersAndSort()"><option value="score-desc">Score ↓</option><option value="score-asc">Score ↑</option><option value="date-desc" selected>Newest</option><option value="date-asc">Oldest</option></select></div>
      <div class="filter-group"><span class="filter-label">Score:</span><select class="filter-select" id="scoreFilter" onchange="applyFiltersAndSort()"><option value="all">All</option><option value="high">80%+</option><option value="mid">60-79%</option><option value="low">50-59%</option></select></div>
      <div class="filter-group"><span class="filter-label">Status:</span><select class="filter-select" id="statusFilter" onchange="applyFiltersAndSort()"><option value="all">All</option><option value="unapplied">Unapplied</option><option value="applied">Applied</option><option value="saved">Saved ⭐</option></select></div>
      <span class="filter-count" id="filterCount"></span>
      <button class="clear-history-btn" id="clearHistoryBtn" onclick="clearHistory()">🗑 CLEAR</button>
    </div>
    <div id="historyContent"><div class="history-loading">Loading history...</div></div>
  </div>
</div>

<script>
const canvas = document.getElementById('matrixCanvas'); const ctx = canvas.getContext('2d');
function resizeCanvas() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; } resizeCanvas(); window.addEventListener('resize', resizeCanvas);
const chars = 'アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン0123456789ABCDEF';
const fontSize = 14; const columns = canvas.width / fontSize; const drops = Array(Math.floor(columns)).fill(1);
function drawMatrix() { ctx.fillStyle = 'rgba(10, 10, 15, 0.05)'; ctx.fillRect(0, 0, canvas.width, canvas.height); ctx.fillStyle = '#00ff41'; ctx.font = fontSize + 'px monospace'; for (let i = 0; i < drops.length; i++) { const char = chars[Math.floor(Math.random() * chars.length)]; ctx.fillText(char, i * fontSize, drops[i] * fontSize); if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) drops[i] = 0; drops[i]++; } }
setInterval(drawMatrix, 50);

const uploadZone = document.getElementById('uploadZone'); const fileInput = document.getElementById('fileInput'); const fileName = document.getElementById('fileName'); const runBtn = document.getElementById('runBtn'); let uploadedFile = null;
uploadZone.addEventListener('click', () => fileInput.click());
uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); uploadZone.classList.add('drag-over'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
uploadZone.addEventListener('drop', (e) => { e.preventDefault(); uploadZone.classList.remove('drag-over'); if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]); });
fileInput.addEventListener('change', () => { if (fileInput.files.length > 0) handleFile(fileInput.files[0]); });
async function handleFile(file) { if (!file.name.endsWith('.pdf')) { alert('Please upload a PDF file'); return; } uploadedFile = file; fileName.textContent = file.name; uploadZone.classList.add('has-file'); const fd = new FormData(); fd.append('file', file); try { const r = await fetch('/upload', { method: 'POST', body: fd }); const d = await r.json(); if (d.status === 'ok') runBtn.disabled = false; else alert('Upload failed: ' + (d.error || 'Unknown error')); } catch (err) { alert('Upload failed: ' + err.message); } }

async function setRegion(value) { if (!value) return; try { const r = await fetch('/set-region', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ region: value }) }); const d = await r.json(); if (d.status === 'ok') document.getElementById('regionStatus').textContent = '🌐 ' + d.region; } catch (err) {} }
fetch('/status').then(r => r.json()).then(status => { if (status.selected_region) { const opts = document.getElementById('regionSelect').querySelectorAll('option'); for (const o of opts) { if (o.value === status.selected_region) { o.selected = true; document.getElementById('regionStatus').textContent = '🌐 ' + status.selected_region; break; } } } });

let eventSource = null;
runBtn.addEventListener('click', () => { if (eventSource) return; runBtn.disabled = true; runBtn.classList.add('running'); document.getElementById('stopBtn').classList.add('visible'); const btnText = runBtn.querySelector('.btn-text'); let dc = 0; const dt = setInterval(() => { dc = (dc + 1) % 4; btnText.textContent = '⟳ RUNNING' + '.'.repeat(dc); }, 500); document.getElementById('terminalSection').classList.add('active'); document.getElementById('resultsSection').classList.remove('active'); document.getElementById('terminalBody').innerHTML = ''; eventSource = new EventSource('/run'); eventSource.onmessage = (e) => { const lines = e.data.split('\n'); for (const line of lines) { if (!line) continue; appendTerminalLine(line); } }; eventSource.onerror = () => { eventSource.close(); eventSource = null; clearInterval(dt); runBtn.classList.remove('running'); document.getElementById('stopBtn').classList.remove('visible'); runBtn.querySelector('.btn-text').textContent = '▶ RUN AGAIN'; runBtn.disabled = !uploadedFile; fetchResults(); }; });
function appendTerminalLine(text) { const cursor = document.getElementById('terminalBody').querySelector('.terminal-cursor'); if (cursor) cursor.remove(); const div = document.createElement('div'); div.className = 'terminal-line'; if (text.startsWith('[ERROR]')) div.classList.add('error'); else if (text.startsWith('[SYSTEM]') || text.includes('PHASE')) div.classList.add('system'); else if (text.includes('[OK]')) div.classList.add('ok'); div.textContent = text; document.getElementById('terminalBody').appendChild(div); document.getElementById('terminalBody').scrollTop = document.getElementById('terminalBody').scrollHeight; const nc = document.createElement('span'); nc.className = 'terminal-cursor'; document.getElementById('terminalBody').appendChild(nc); }
async function stopAgent() { try { await fetch('/stop', { method: 'POST' }); } catch (err) {} }
async function fetchResults() { try { const r = await fetch('/results'); const d = await r.json(); if (d.files && d.files.length) { document.getElementById('resultsSection').classList.add('active'); const g = document.getElementById('resultsGrid'); g.innerHTML = ''; [{ v: d.stats?.total_jobs_reviewed || 0, l: 'Jobs Found' }, { v: d.stats?.high_match || 0, l: 'High Match' }, { v: d.files.length, l: 'Files' }].forEach(s => { const dv = document.createElement('div'); dv.className = 'result-stat'; dv.innerHTML = '<div class="value">' + s.v + '</div><div class="label">' + s.l + '</div>'; g.appendChild(dv); }); const rf = document.getElementById('resultFiles'); rf.innerHTML = ''; d.files.forEach(f => { const a = document.createElement('a'); a.className = 'result-file'; a.href = '/download/' + encodeURIComponent(f); a.textContent = f; rf.appendChild(a); }); } } catch (err) {} }

async function logoutUser() { await fetch('/logout', { method: 'POST' }); window.location.href = '/login'; }
let _allHistoryJobs = []; let _appliedSet = new Set(); let _savedSet = new Set(); let _feedbackMap = new Map();
async function toggleHistory() { const btn = document.getElementById('historyToggle'); const hs = document.getElementById('historySection'); if (hs.classList.contains('active')) { hs.classList.remove('active'); btn.textContent = '📋 VIEW SCORING HISTORY'; return; } hs.classList.add('active'); btn.textContent = '📋 HIDE SCORING HISTORY'; await renderHistory(); }
async function renderHistory() { const hc = document.getElementById('historyContent'); hc.innerHTML = '<div class="history-loading"><span class="spinner"></span> Loading...</div>'; try { const [hr, ar, sr, fr] = await Promise.all([fetch('/api/history'), fetch('/api/applied'), fetch('/api/saved'), fetch('/api/user-feedback').catch(() => ({ json: () => ({ feedback: [] }) }))]); const fd = await fr.json(); _feedbackMap = new Map((fd.feedback || []).map(f => [String(f.application_id), f.rating])); const hd = await hr.json(); const ad = await ar.json(); const sd = await sr.json(); _appliedSet = new Set(ad.applied || []); _savedSet = new Set(sd.saved || []); _allHistoryJobs = (hd.jobs || []).filter(j => (j.ai_score || 0) >= 50); if (_allHistoryJobs.length === 0) { hc.innerHTML = '<div class="history-empty">No scoring history yet.</div>'; document.getElementById('historyFilters').style.display = 'none'; return; } document.getElementById('historyFilters').style.display = 'flex'; applyFiltersAndSort(); } catch (err) { hc.innerHTML = '<div class="history-empty">Failed to load: ' + err.message + '</div>'; } }
function applyFiltersAndSort() { const sv = document.getElementById('sortSelect').value; const scv = document.getElementById('scoreFilter').value; const stv = document.getElementById('statusFilter').value; let f = _allHistoryJobs.filter(j => { const s = j.ai_score || 0; if (scv === 'high' && s < 80) return false; if (scv === 'mid' && (s < 60 || s >= 80)) return false; if (scv === 'low' && s >= 60) return false; const ju = j.job?.url || ''; const ia = ju && _appliedSet.has(ju); if (stv === 'applied' && !ia) return false; if (stv === 'unapplied' && ia) return false; const jid = j.id; const isv = jid && _savedSet.has(jid); if (stv === 'saved' && !isv) return false; return true; }); f.sort((a, b) => { switch (sv) { case 'score-desc': return (b.ai_score||0) - (a.ai_score||0); case 'score-asc': return (a.ai_score||0) - (b.ai_score||0); case 'date-desc': return (b.timestamp||'').localeCompare(a.timestamp||''); default: return 0; } }); document.getElementById('filterCount').innerHTML = '<span class="num">' + f.length + '</span> / ' + _allHistoryJobs.length + ' jobs'; _renderJobList(f); }
function _renderJobList(jobs) { if (jobs.length === 0) { document.getElementById('historyContent').innerHTML = '<div class="history-empty">No jobs match.</div>'; return; } let h = ''; for (const j of jobs) { const s = j.ai_score||0; const sc = s>=80?'high':(s>=50?'mid':'low'); const p = j.job?.platform||'unknown'; const sk = (j.matching_skills||[]).slice(0,3); const d = (j.timestamp||'').slice(0,10); const ju = j.job?.url||''; const ia = ju&&_appliedSet.has(ju); const jid = j.id; const isv = jid&&_savedSet.has(jid); let ah = ia?'<span class="history-applied">✅ Applied</span>':(ju?'<a class="history-apply" href="'+ju.replace(/"/g,'&quot;')+'" target="_blank" onclick="markApplied(this.href,this)">🔗 Apply</a>':'<span class="history-apply" style="opacity:0.35">No Link</span>'); let sh = s>=80?'<button class="history-save'+(isv?' saved':'')+'" onclick="toggleSave('+jid+',this)">'+(isv?'⭐ Saved':'☆ Save')+'</button>':'<span class="history-save disabled">☆ Save</span>'; h += '<div class="history-item"><div class="history-score '+sc+'">'+s+'</div><div class="history-info"><div class="title">'+escHtml(j.job?.title||'Unknown')+'</div><div class="company">'+escHtml(j.job?.company||'Unknown')+'</div><div class="meta"><span class="history-platform">'+escHtml(p)+'</span><span>'+d+'</span></div><div class="history-skills">'+sk.map(s=>'<span class="history-skill-tag">'+escHtml(s)+'</span>').join('')+'</div></div><div style="display:flex;flex-direction:column;align-items:center;gap:6px"><div class="feedback-group"><button class="fb-btn up'+(_feedbackMap.get(String(jid))===1?' active':'')+'" onclick="submitFeedback('+jid+',1,this)">[+] Good</button><button class="fb-btn down'+(_feedbackMap.get(String(jid))===-1?' active':'')+'" onclick="submitFeedback('+jid+',-1,this)">[-] Skip</button></div>'+sh+ah+'</div></div>'; } document.getElementById('historyContent').innerHTML = h; }
async function submitFeedback(aid, r, btn) { if (btn.classList.contains('loading')) return; btn.classList.add('loading'); const cr = _feedbackMap.get(String(aid)); const nr = (cr===r)?0:r; try { const rp = await fetch('/api/feedback', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({rating:nr,application_id:aid}) }); const d = await rp.json(); if (d.status==='ok') { if (nr===0) _feedbackMap.delete(String(aid)); else _feedbackMap.set(String(aid), nr); applyFiltersAndSort(); } } catch(e){} btn.classList.remove('loading'); loadFeedbackSummary(); }
async function toggleSave(aid, btn) { const isv = _savedSet.has(aid); try { if (isv) { const r = await fetch('/api/unsave-job', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({application_id:aid}) }); const d = await r.json(); if (d.status==='ok') { _savedSet.delete(aid); btn.classList.remove('saved'); btn.innerHTML='☆ Save'; applyFiltersAndSort(); } } else { const r = await fetch('/api/save-job', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({application_id:aid}) }); const d = await r.json(); if (d.status==='ok') { _savedSet.add(aid); btn.classList.add('saved'); btn.innerHTML='⭐ Saved'; applyFiltersAndSort(); } } } catch(e){} }
async function markApplied(url, el) { try { const r = await fetch('/api/mark-applied', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({url:url}) }); const d = await r.json(); if (d.status==='ok') { _appliedSet.add(url); if (el&&el.parentNode) { const b = document.createElement('span'); b.className='history-applied'; b.textContent='✅ Applied'; el.parentNode.replaceChild(b, el); } applyFiltersAndSort(); } } catch(e){} }
async function clearHistory() { if (!confirm('Clear all history?')) return; try { const r = await fetch('/api/clear-history', { method:'POST' }); const d = await r.json(); if (d.status==='ok') { _allHistoryJobs=[]; _appliedSet=new Set(); _savedSet=new Set(); document.getElementById('historyContent').innerHTML='<div class="history-empty">History cleared.</div>'; document.getElementById('historyFilters').style.display='none'; } } catch(e){} }
function escHtml(s) { const d = document.createElement('div'); d.textContent = s||''; return d.innerHTML; }
async function loadFeedbackSummary() { try { const r = await fetch('/api/my-feedback-stats'); const d = await r.json(); document.getElementById('fsLoading').style.display='none'; if (d.total>0) { document.getElementById('fsUp').textContent=d.thumbs_up; document.getElementById('fsDown').textContent=d.thumbs_down; document.getElementById('fsRate').textContent=d.positivity_rate+'%'; document.getElementById('fsStats').style.display='flex'; } else document.getElementById('fsEmpty').style.display='block'; } catch(e){} }
</script>
</body>
</html>"""
