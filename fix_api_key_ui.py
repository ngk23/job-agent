"""Fix: Remove API key input UI from dashboard - make it static."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

path = 'agent/dashboard.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

changes = 0

# 1. Replace HTML api-key-section (with input/button/status) with static text
old_html = '''  <div class="api-key-section" id="apiKeySection">
    <label>🔑 API Key:</label>
    <input type="password" class="api-key-input" id="apiKeyInput"
      placeholder="sk-ant-... paste your Anthropic API key here"
      autocomplete="off" spellcheck="false">
    <button class="api-key-btn" id="apiKeyBtn" onclick="setApiKey()">SAVE</button>
    <span class="api-key-status missing" id="apiKeyStatus">⚠️ Not set</span>
  </div>'''

new_html = '''  <div class="api-key-section" id="apiKeySection">
    <label>🔑 API Key:</label>
    <span style="color:var(--primary);font-size:0.85em;">✅ Configured in environment</span>
  </div>'''

if old_html in content:
    content = content.replace(old_html, new_html)
    changes += 1
    print(f'[1/5] Replaced API key HTML section')
else:
    # Try with different whitespace
    old_html2 = '''<div class="api-key-section" id="apiKeySection">
    <label>\U0001f511 API Key:</label>
    <input type="password" class="api-key-input" id="apiKeyInput"
      placeholder="sk-ant-... paste your Anthropic API key here"
      autocomplete="off" spellcheck="false">
    <button class="api-key-btn" id="apiKeyBtn" onclick="setApiKey()">SAVE</button>
    <span class="api-key-status missing" id="apiKeyStatus">\u26a0\ufe0f Not set</span>
  </div>'''
    if old_html2 in content:
        content = content.replace(old_html2, new_html)
        changes += 1
        print(f'[1/5] Replaced API key HTML section (variant 2)')
    else:
        print(f'[1/5] SKIP - HTML pattern not found')

# 2. Remove the JS const declarations and setApiKey function
old_js = '''const apiKeyInput = document.getElementById('apiKeyInput');
const apiKeyStatus = document.getElementById('apiKeyStatus');

async function setApiKey() {
  const key = apiKeyInput.value.trim();
  if (!key || !key.startsWith('sk-ant-')) {
    apiKeyStatus.textContent = '\u26a0\ufe0f Invalid key (must start with sk-ant-)';
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
      apiKeyStatus.textContent = '\u2705 Configured';
      apiKeyStatus.className = 'api-key-status configured';
      apiKeyInput.type = 'password';
      apiKeyInput.disabled = true;
      document.getElementById('apiKeyBtn').disabled = true;
      // Enable run button if CV is also uploaded
      if (uploadedFile) runBtn.disabled = false;
    } else {
      apiKeyStatus.textContent = '\u26a0\ufe0f ' + (data.error || 'Failed');
      apiKeyStatus.className = 'api-key-status missing';
    }
  } catch (err) {
    apiKeyStatus.textContent = '\u26a0\ufe0f Error: ' + err.message;
    apiKeyStatus.className = 'api-key-status missing';
  }
}

// \u2500\u2500 Region Selector \u2500\u2500'''

if old_js in content:
    content = content.replace(old_js, '// \u2500\u2500 Region Selector \u2500\u2500')
    changes += 1
    print(f'[2/5] Removed setApiKey JS function')
else:
    print(f'[2/5] SKIP - JS function pattern not found')

# 3. Update the /status fetch handler - remove apiKeyInput references
old_status = '''// Check on page load if API key is already set (don't pre-load uploaded CV)
fetch('/status').then(r => r.json()).then(status => {
  if (status.api_key_configured) {
    apiKeyStatus.textContent = '\u2705 Configured';
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
        regionStatus.textContent = '\U0001f310 ' + status.selected_region;
        break;
      }
    }
  }
});'''

new_status = '''// Restore previously selected region on page load
fetch('/status').then(r => r.json()).then(status => {
  if (status.selected_region) {
    const options = regionSelect.querySelectorAll('option');
    for (const opt of options) {
      if (opt.value === status.selected_region) {
        opt.selected = true;
        regionStatus.textContent = '\U0001f310 ' + status.selected_region;
        break;
      }
    }
  }
});'''

if old_status in content:
    content = content.replace(old_status, new_status)
    changes += 1
    print(f'[3/5] Updated /status fetch handler')
else:
    print(f'[3/5] SKIP - status handler pattern not found')

# 4. Update runBtn.disabled line
old_run = "runBtn.disabled = !apiKeyInput.disabled;"
new_run = "runBtn.disabled = false;"
if old_run in content:
    content = content.replace(old_run, new_run)
    changes += 1
    print(f'[4/5] Updated run button logic')
else:
    print(f'[4/5] SKIP - run button pattern not found')

# 5. Remove CSS for .api-key-input and .api-key-btn
old_css_input = '''  .api-key-input {
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
  }'''

# Just remove the input button CSS block and btn CSS block
old_btn_css = '''  .api-key-btn {
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
  }'''

if old_css_input in content:
    content = content.replace(old_css_input, '')
    changes += 1
    print(f'[5/5] Removed input CSS')
elif old_btn_css in content:
    content = content.replace(old_btn_css, '')
    changes += 1
    print(f'[5/5] Removed btn CSS')

# Write back
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print(f'\nTotal changes: {changes}')

# Verify
if 'apiKeyInput' in content or 'apiKeyStatus' in content or 'setApiKey()' in content:
    remaining = []
    if 'apiKeyInput' in content: remaining.append('apiKeyInput')
    if 'apiKeyStatus' in content: remaining.append('apiKeyStatus')
    if 'setApiKey()' in content: remaining.append('setApiKey()')
    if 'api-key-input' in content: remaining.append('api-key-input')
    if 'api-key-btn' in content: remaining.append('api-key-btn')
    print(f'WARNING: Still present: {", ".join(remaining)}')
else:
    print('ALL CLEAN: No remaining API key input UI references')

# Compile check
try:
    compile(content, 'dashboard.py', 'exec')
    print('PYTHON SYNTAX: OK')
except SyntaxError as e:
    print(f'PYTHON SYNTAX ERROR: {e}')
