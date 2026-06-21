# Fix dashboard.py: replace Resend admin panel UI with Gmail SMTP fields
import sys

with open('C:/Users/N Gokul Krishna/Downloads/job-agent/agent/dashboard.py', 'r', encoding='utf-8') as f:
    content = f.read()

changes = 0

# 1. Fix route handler: change resend_api_key check to gmail_user/gmail_app_password check
old1 = "        if not data or not data.get('resend_api_key'):\n            return jsonify({'status': 'error', 'error': 'API key required'}), 400"
new1 = "        if not data or not data.get('gmail_user') or not data.get('gmail_app_password'):\n            return jsonify({'status': 'error', 'error': 'Gmail user and app password required'}), 400"
if old1 in content:
    content = content.replace(old1, new1, 1)
    changes += 1
    print("1) Fixed route handler check")
else:
    print("1) Route handler check NOT found")

# 2. Fix admin panel HTML: replace Resend section with Gmail SMTP section
old2 = '''  <div class="resend-section" style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:20px;">
    <h3 style="color:var(--accent);margin-bottom:12px;font-size:0.95em;letter-spacing:1px;">@ Email Notifications (Resend)</h3>
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
      <input type="password" id="resendKeyInput" placeholder="re_... paste your Resend API key here"
        style="flex:1;min-width:200px;padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'Share Tech Mono',monospace;font-size:0.85em;outline:none;">
      <button onclick="setResendKey()" style="padding:8px 16px;background:transparent;border:1px solid var(--accent);border-radius:4px;color:var(--accent);font-family:'Share Tech Mono',monospace;font-size:0.85em;cursor:pointer;">SAVE</button>
      <span id="resendKeyStatus" style="font-size:0.8em;color:var(--text-dim);">Not configured</span>
    </div>
  </div>'''

new2 = '''  <div class="gmail-section" style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:20px;">
    <h3 style="color:var(--accent);margin-bottom:12px;font-size:0.95em;letter-spacing:1px;">@ Email Notifications (Gmail SMTP)</h3>
    <div style="display:flex;flex-direction:column;gap:8px;">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <span style="color:var(--text-dim);font-size:0.8em;min-width:90px;">Gmail address:</span>
        <input type="email" id="gmailUserInput" placeholder="yourname@gmail.com"
          style="flex:1;min-width:200px;padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'Share Tech Mono',monospace;font-size:0.85em;outline:none;">
      </div>
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <span style="color:var(--text-dim);font-size:0.8em;min-width:90px;">App password:</span>
        <input type="password" id="gmailAppPasswordInput" placeholder="16-char Gmail app password"
          style="flex:1;min-width:200px;padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'Share Tech Mono',monospace;font-size:0.85em;outline:none;">
      </div>
      <div style="display:flex;align-items:center;gap:10px;">
        <button onclick="saveGmailCredentials()" style="padding:8px 16px;background:transparent;border:1px solid var(--accent);border-radius:4px;color:var(--accent);font-family:'Share Tech Mono',monospace;font-size:0.85em;cursor:pointer;">SAVE</button>
        <span id="gmailStatus" style="font-size:0.8em;color:var(--text-dim);">Not configured</span>
      </div>
    </div>
  </div>'''

if old2 in content:
    content = content.replace(old2, new2, 1)
    changes += 1
    print("2) Fixed admin panel HTML")
else:
    print("2) Admin panel HTML NOT found")

# 3. Fix JS function: replace setResendKey with saveGmailCredentials
old3 = '''async function setResendKey() {
  const key = document.getElementById('resendKeyInput').value.trim();
  if (!key || !key.startsWith('re_')) {
    alert('Invalid Resend API key (must start with re_)');
    return;
  }
  const statusEl = document.getElementById('resendKeyStatus');
  statusEl.textContent = 'Saving...';
  try {
    const resp = await fetch('/admin/api/set-resend-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resend_api_key: key })
    });
    const data = await resp.json();
    if (data.status === 'ok') {
      statusEl.textContent = 'Configured';
      statusEl.style.color = 'var(--primary)';
      document.getElementById('resendKeyInput').disabled = true;
    } else {
      statusEl.textContent = 'Failed: ' + (data.error || 'Unknown');
    }
  } catch (err) {
    statusEl.textContent = 'Error: ' + err.message;
  }
}'''

new3 = '''async function saveGmailCredentials() {
  const user = document.getElementById('gmailUserInput').value.trim();
  const appPw = document.getElementById('gmailAppPasswordInput').value.trim();
  if (!user || !appPw) {
    alert('Please enter both Gmail address and app password');
    return;
  }
  if (!user.includes('@')) {
    alert('Please enter a valid Gmail address');
    return;
  }
  const statusEl = document.getElementById('gmailStatus');
  statusEl.textContent = 'Saving...';
  try {
    const resp = await fetch('/admin/api/set-resend-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gmail_user: user, gmail_app_password: appPw })
    });
    const data = await resp.json();
    if (data.status === 'ok') {
      statusEl.textContent = 'Configured';
      statusEl.style.color = 'var(--primary)';
      document.getElementById('gmailUserInput').disabled = true;
      document.getElementById('gmailAppPasswordInput').disabled = true;
    } else {
      statusEl.textContent = 'Failed: ' + (data.error || 'Unknown');
    }
  } catch (err) {
    statusEl.textContent = 'Error: ' + err.message;
  }
}'''

if old3 in content:
    content = content.replace(old3, new3, 1)
    changes += 1
    print("3) Fixed JS function")
else:
    print("3) JS function NOT found")

if changes > 0:
    with open('C:/Users/N Gokul Krishna/Downloads/job-agent/agent/dashboard.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Done: %d change(s) applied" % changes)
else:
    print("No changes were applied")
