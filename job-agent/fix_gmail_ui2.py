# Fix remaining UI elements in dashboard.py for Gmail SMTP
# Run from the job-agent subdirectory

with open('agent/dashboard.py', 'r', encoding='utf-8') as f:
    content = f.read()

changes = 0

# 1. Fix HTML: resend-section class -> gmail-section
if 'resend-section' in content:
    content = content.replace('resend-section', 'gmail-section', 1)
    changes += 1
    print('1) Fixed class name')

# 2. Fix HTML: resendKeyInput id -> gmailUserInput
count = content.count('resendKeyInput')
if count > 0:
    content = content.replace('resendKeyInput', 'gmailUserInput', count)
    changes += 1
    print('2) Fixed ' + str(count) + ' occurrences of resendKeyInput')

# 3. Fix HTML: resendKeyStatus id -> gmailStatus
count = content.count('resendKeyStatus')
if count > 0:
    content = content.replace('resendKeyStatus', 'gmailStatus', count)
    changes += 1
    print('3) Fixed ' + str(count) + ' occurrences of resendKeyStatus')

# 4. Fix: re_... placeholder
if 're_... paste your Resend API key here' in content:
    content = content.replace(
        're_... paste your Resend API key here',
        'yourname@gmail.com',
        1
    )
    changes += 1
    print('4) Fixed placeholder text')

# 5. Fix JS: setResendKey function (replace the full function)
old_set = 'async function setResendKey()'
new_set = 'async function saveGmailCredentials()'
if old_set in content:
    content = content.replace(old_set, new_set, 1)
    changes += 1
    print('5) Fixed function name')

# 6. Fix JS: check for re_ prefix
old_check = "if (!key || !key.startsWith('re_'))"
new_check = "if (!user || !appPw)"
if old_check in content:
    content = content.replace(old_check, new_check, 1)
    changes += 1
    print('6) Fixed validation check')

# 7. Fix JS: alert text
old_alert = "alert('Invalid Resend API key (must start with re_)')"
new_alert = "alert('Please enter both Gmail address and app password')"
if old_alert in content:
    content = content.replace(old_alert, new_alert, 1)
    changes += 1
    print('7) Fixed alert text')

# 8. Fix JS: body JSON payload
old_body = "body: JSON.stringify({ resend_api_key: key })"
new_body = "body: JSON.stringify({ gmail_user: user, gmail_app_password: appPw })"
if old_body in content:
    content = content.replace(old_body, new_body, 1)
    changes += 1
    print('8) Fixed API body')

# 9. Fix JS: input disabled
old_disable = "document.getElementById('resendKeyInput').disabled = true"
new_disable = "document.getElementById('gmailUserInput').disabled = true;\n      document.getElementById('gmailAppPasswordInput').disabled = true"
if old_disable in content:
    content = content.replace(old_disable, new_disable, 1)
    changes += 1
    print('9) Fixed input disable')

# 10. Fix JS: key variable references
old_var = "const key = document.getElementById('gmailUserInput').value.trim();"
new_var = "const user = document.getElementById('gmailUserInput').value.trim();\n  const appPw = document.getElementById('gmailAppPasswordInput').value.trim();"
if old_var in content:
    content = content.replace(old_var, new_var, 1)
    changes += 1
    print('10) Fixed variable extraction')

# 11. Fix JS: appPw validation
# This should be already handled by checks 6 and 7
# But let's ensure we don't have the old key variable usage
content = content.replace('  const key = document', '  const user = document')
# Also fix placeholder
old_ph = 'placeholder="re_... paste your Resend API key here"'
new_ph = 'placeholder="yourname@gmail.com"'
if old_ph in content:
    content = content.replace(old_ph, new_ph, 1)
    changes += 1
    print('11) Fixed placeholder in HTML')

# 12. Fix JS: key variable used as argument
old_key_use = "  if (!key || !key.startsWith('re_'))"
if old_key_use in content:
    content = content.replace(old_key_use, "  if (!user || !appPw)", 1)
    changes += 1
    print('12) Fixed validation')

if changes > 0:
    with open('agent/dashboard.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('\nDone: ' + str(changes) + ' change(s) applied')
else:
    print('\nNo changes made')
