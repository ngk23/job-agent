"""
Patch script to add Session Log feature to dashboard.py.
Adds: imports, login logging in /login route, admin API endpoint, and UI section.
"""
import re

with open('agent/dashboard.py', 'r', encoding='utf-8') as f:
    content = f.read()

changes_made = []

# 1. Add log_login_attempt and get_login_logs to imports
old_imports = (
    '    create_password_reset_token,\n'
    '    get_user_by_reset_token,\n'
    '    use_password_reset_token,\n'
    '    cleanup_expired_tokens,\n'
    ')'
)
new_imports = (
    '    create_password_reset_token,\n'
    '    get_user_by_reset_token,\n'
    '    use_password_reset_token,\n'
    '    cleanup_expired_tokens,\n'
    '    log_login_attempt,\n'
    '    get_login_logs,\n'
    ')'
)

if old_imports in content:
    content = content.replace(old_imports, new_imports)
    changes_made.append('1. Added log_login_attempt and get_login_logs imports')
else:
    print('1. FAILED - could not find import block')
    # Try alternate - find the import block differently
    idx = content.find('cleanup_expired_tokens,')
    if idx > 0:
        print(f'   Found cleanup_expired_tokens at position {idx}')
        # Add after this line
        insert_pos = idx + len('cleanup_expired_tokens,')
        content = (
            content[:insert_pos] +
            '\n    log_login_attempt,\n    get_login_logs,' +
            content[insert_pos:]
        )
        changes_made.append('1. Added log_login_attempt and get_login_logs imports (alt)')

# 2. Add login logging in the /login POST route
# Find the line where successful login logs
old_login_success = (
    '        if not result:\n'
    '            return jsonify({\'status\': \'error\', \'error\': \'Invalid email or password\'}), 401\n'
    '        logger.info(f"User logged in: {email}")\n'
    '        return jsonify({\'status\': \'ok\', \'user\': {\'name\': result[\'name\'], \'email\': result[\'email\']}})'
)

new_login_success = (
    '        if not result:\n'
    '            return jsonify({\'status\': \'error\', \'error\': \'Invalid email or password\'}), 401\n'
    '        logger.info(f"User logged in: {email}")\n'
    '        # Log successful login\n'
    '        log_login_attempt(\n'
    '            email=email,\n'
    '            success=True,\n'
    '            user_id=result.get(\'id\'),\n'
    '            ip_address=request.remote_addr or \'\',\n'
    '            user_agent=request.user_agent.string if request.user_agent else \'\',\n'
    '        )\n'
    '        return jsonify({\'status\': \'ok\', \'user\': {\'name\': result[\'name\'], \'email\': result[\'email\']}})'
)

if old_login_success in content:
    content = content.replace(old_login_success, new_login_success)
    changes_made.append('2. Added login logging on successful login')
else:
    print('2. FAILED - could not find successful login block')

# Also log failed login attempts
old_login_failed = (
    '        if isinstance(result, dict) and result.get(\'error\'):\n'
    '            if result[\'error\'] == \'pending\':\n'
    '                return jsonify({\'status\': \'error\', \'error\': \'⏳ Your account is pending admin approval. Please wait for an admin to activate it.\'}), 403\n'
    '            elif result[\'error\'] == \'rejected\':\n'
    '                return jsonify({\'status\': \'error\', \'error\': \'❌ Your account registration was rejected by the admin.\'}), 403'
)

new_login_failed = (
    '        if isinstance(result, dict) and result.get(\'error\'):\n'
    '            if result[\'error\'] == \'pending\':\n'
    '                log_login_attempt(email=email, success=False, details=\'pending approval\', ip_address=request.remote_addr or \'\', user_agent=request.user_agent.string if request.user_agent else \'\')\n'
    '                return jsonify({\'status\': \'error\', \'error\': \'⏳ Your account is pending admin approval. Please wait for an admin to activate it.\'}), 403\n'
    '            elif result[\'error\'] == \'rejected\':\n'
    '                log_login_attempt(email=email, success=False, details=\'rejected\', ip_address=request.remote_addr or \'\', user_agent=request.user_agent.string if request.user_agent else \'\')\n'
    '                return jsonify({\'status\': \'error\', \'error\': \'❌ Your account registration was rejected by the admin.\'}), 403'
)

if old_login_failed in content:
    content = content.replace(old_login_failed, new_login_failed)
    changes_made.append('3. Added login logging on pending/rejected login attempts')
else:
    print('3. FAILED - could not find pending/rejected block')

# 3. Add admin session-logs API endpoint
# Find the admin_reset_user_password route and add session-logs endpoint after it
old_reset_end = (
    '    @app.route(\'/admin/api/reset-user-password/<int:target_user_id>\', methods=[\'POST\'])\n'
    '    @require_admin\n'
    '    def admin_reset_user_password(target_user_id):\n'
    '        """Admin reset user password."""\n'
    '        data = request.get_json()\n'
    '        if not data or \'password\' not in data:\n'
    '            return jsonify({\'status\': \'error\', \'error\': \'Password required\'}), 400\n'
    '        pw = data[\'password\'].strip()\n'
    '        if len(pw) < 6:\n'
    '            return jsonify({\'status\': \'error\', \'error\': \'Password must be at least 6 characters\'}), 400\n'
    '        user = get_user_by_id(target_user_id)\n'
    '        if not user:\n'
    '            return jsonify({\'status\': \'error\', \'error\': \'User not found\'}), 404\n'
    '        new_hash = hash_password(pw)\n'
    '        ok = update_user_password(target_user_id, new_hash)\n'
    '        if ok:\n'
    '            logger.info(f"Admin reset password for user {target_user_id}")\n'
    '            return jsonify({\'status\': \'ok\'})\n'
    '        return jsonify({\'status\': \'error\', \'error\': \'Failed\'}), 500'
)

new_reset_end = (
    '    @app.route(\'/admin/api/reset-user-password/<int:target_user_id>\', methods=[\'POST\'])\n'
    '    @require_admin\n'
    '    def admin_reset_user_password(target_user_id):\n'
    '        """Admin reset user password."""\n'
    '        data = request.get_json()\n'
    '        if not data or \'password\' not in data:\n'
    '            return jsonify({\'status\': \'error\', \'error\': \'Password required\'}), 400\n'
    '        pw = data[\'password\'].strip()\n'
    '        if len(pw) < 6:\n'
    '            return jsonify({\'status\': \'error\', \'error\': \'Password must be at least 6 characters\'}), 400\n'
    '        user = get_user_by_id(target_user_id)\n'
    '        if not user:\n'
    '            return jsonify({\'status\': \'error\', \'error\': \'User not found\'}), 404\n'
    '        new_hash = hash_password(pw)\n'
    '        ok = update_user_password(target_user_id, new_hash)\n'
    '        if ok:\n'
    '            logger.info(f"Admin reset password for user {target_user_id}")\n'
    '            return jsonify({\'status\': \'ok\'})\n'
    '        return jsonify({\'status\': \'error\', \'error\': \'Failed\'}), 500\n'
    '\n'
    '    @app.route(\'/admin/api/session-logs\')\n'
    '    @require_admin\n'
    '    def admin_session_logs():\n'
    '        """Get session/login logs (admin only)."""\n'
    '        logs = get_login_logs(limit=200)\n'
    '        return jsonify({\'logs\': logs})'
)

if old_reset_end in content:
    content = content.replace(old_reset_end, new_reset_end)
    changes_made.append('4. Added /admin/api/session-logs API endpoint')
else:
    print('4. FAILED - could not find admin_reset_user_password endpoint')
    # Try to find an alternative
    idx = content.find('def admin_reset_user_password')
    if idx > 0:
        print(f'   Found admin_reset_user_password at position {idx}')

# 5. Add Session Log section to admin panel HTML
# Find the "Recent Applications" section and add Session Log before it
old_recent_apps = (
    '  <div class=\"section-title\">📋 Recent Applications <span style=\"font-size:0.7em;color:var(--text-dim);font-weight:400;\">(all users)</span></div>'
)

new_session_log_and_apps = (
    '  <div class=\"section-title\">🕐 Session Logs <span style=\"font-size:0.7em;color:var(--text-dim);font-weight:400;\">(recent 200 logins)</span></div>\n'
    '  <div style=\"margin-bottom:12px;\">\n'
    '    <button onclick="toggleSessionLogs()" style=\"padding:6px 16px;background:transparent;border:1px solid var(--accent);border-radius:4px;color:var(--accent);font-family:\'Share Tech Mono\',monospace;font-size:0.8em;cursor:pointer;transition:all 0.2s;\">\n'
    '      📋 Show Session Logs\n'
    '    </button>\n'
    '  </div>\n'
    '  <div id=\"sessionLogSection\" style=\"display:none;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:24px;overflow-x:auto;\">\n'
    '    <div id=\"sessionLogContent\" style=\"font-size:0.8em;color:var(--text-dim);text-align:center;padding:20px;\">Loading...</div>\n'
    '  </div>\n'
    '\n'
    '  <div class=\"section-title\">📋 Recent Applications <span style=\"font-size:0.7em;color:var(--text-dim);font-weight:400;\">(all users)</span></div>'
)

if old_recent_apps in content:
    content = content.replace(old_recent_apps, new_session_log_and_apps)
    changes_made.append('5. Added Session Log toggle section to admin panel')
else:
    print('5. FAILED - could not find recent applications section')

# 6. Add JavaScript functions for session logs and failed login counters
# Find the end of the admin panel script section (before </script>)
old_script_end = (
    '  return false;\n'
    '}}\n'
    '</script>\n'
    '</body></html>"""'
)

new_script_end = (
    '  return false;\n'
    '}}\n'
    '\n'
    'let _sessionLogsVisible = false;\n'
    'async function toggleSessionLogs() {{\n'
    '  const section = document.getElementById(\'sessionLogSection\');\n'
    '  const btn = event.target;\n'
    '  if (_sessionLogsVisible) {{\n'
    '    section.style.display = \'none\';\n'
    '    btn.textContent = \'📋 Show Session Logs\';\n'
    '    _sessionLogsVisible = false;\n'
    '    return;\n'
    '  }}\n'
    '  section.style.display = \'block\';\n'
    '  btn.textContent = \'📋 Hide Session Logs\';\n'
    '  _sessionLogsVisible = true;\n'
    '  document.getElementById(\'sessionLogContent\').innerHTML = \'<span class=\"spinner\" style=\"display:inline-block;width:12px;height:12px;border:2px solid var(--border);border-top-color:var(--primary);border-radius:50%;animation:spin 0.8s linear infinite;vertical-align:middle;margin-right:8px;\"></span> Loading...\';\n'
    '  try {{\n'
    '    const resp = await fetch(\'/admin/api/session-logs\');\n'
    '    const data = await resp.json();\n'
    '    const logs = data.logs || [];\n'
    '    if (logs.length === 0) {{\n'
    '      document.getElementById(\'sessionLogContent\').innerHTML = \'<div style=\"text-align:center;padding:20px;color:var(--text-dim);\">No login records yet.</div>\';\n'
    '      return;\n'
    '    }}\n'
    '    const failedCount = logs.filter(l => l.success === 0).length;\n'
    '    let html = \'<div style=\"margin-bottom:10px;display:flex;gap:16px;flex-wrap:wrap;\">\'\n'
    '      + \'<span style=\"color:var(--accent);font-size:0.85em;\">Total Logins: <strong style=\"color:var(--text);\">\' + logs.length + \'</strong></span>\'\n'
    '      + \'<span style=\"color:var(--warning);font-size:0.85em;\">Failed: <strong style=\"color:var(--error);\">\' + failedCount + \'</strong></span>\'\n'
    '      + \'</div>\';\n'
    '    html += \'<table style=\"width:100%;border-collapse:collapse;font-size:0.8em;\">\'\n'
    '      + \'<tr style=\"background:var(--surface2);color:var(--accent);font-size:0.75em;text-transform:uppercase;letter-spacing:1px;\">\'\n'
    '      + \'<th style=\"padding:6px 8px;text-align:left;\">Time</th>\'\n'
    '      + \'<th style=\"padding:6px 8px;text-align:left;\">Email</th>\'\n'
    '      + \'<th style=\"padding:6px 8px;text-align:left;\">User</th>\'\n'
    '      + \'<th style=\"padding:6px 8px;text-align:center;\">Status</th>\'\n'
    '      + \'<th style=\"padding:6px 8px;text-align:left;\">IP</th>\'\n'
    '      + \'<th style=\"padding:6px 8px;text-align:left;\">Details</th>\'\n'
    '      + \'</tr>\';\n'
    '    for (const log of logs) {{\n'
    '      const ts = (log.created_at || \'\').slice(0, 19).replace(\'T\', \' \');\n'
    '      const statusIcon = log.success === 1 ? \'✅\' : \'❌\';\n'
    '      const statusColor = log.success === 1 ? \'var(--primary)\' : \'var(--error)\';\n'
    '      const userName = log.user_name || \'—\';\n'
    '      const details = log.details || \'\';\n'
    '      html += \'<tr style=\"border-top:1px solid var(--border);\">\'\n'
    '        + \'<td style=\"padding:6px 8px;color:var(--text-dim);white-space:nowrap;\">\' + ts + \'</td>\'\n'
    '        + \'<td style=\"padding:6px 8px;\">\' + escHtml(log.email || \'\') + \'</td>\'\n'
    '        + \'<td style=\"padding:6px 8px;color:var(--primary);\">\' + escHtml(userName) + \'</td>\'\n'
    '        + \'<td style=\"padding:6px 8px;text-align:center;color:\' + statusColor + \';\">\' + statusIcon + \'</td>\'\n'
    '        + \'<td style=\"padding:6px 8px;color:var(--text-dim);font-size:0.9em;\">\' + escHtml(log.ip_address || \'\') + \'</td>\'\n'
    '        + \'<td style=\"padding:6px 8px;color:var(--text-dim);font-size:0.9em;\">\' + escHtml(details) + \'</td>\'\n'
    '        + \'</tr>\';\n'
    '    }}\n'
    '    html += \'</table>\';\n'
    '    document.getElementById(\'sessionLogContent\').innerHTML = html;\n'
    '  }} catch (err) {{\n'
    '    document.getElementById(\'sessionLogContent\').innerHTML = \'<div style=\"text-align:center;padding:20px;color:var(--error);\">Error: \' + err.message + \'</div>\';\n'
    '  }}\n'
    '}}\n'
    '</script>\n'
    '</body></html>"""'
)

if old_script_end in content:
    content = content.replace(old_script_end, new_script_end)
    changes_made.append('6. Added JS functions for session log toggle and rendering')
else:
    print('6. FAILED - could not find script end')
    # Try partial match
    idx = content.find('return false;\\n}}\\n</script>\\n</body></html>"""')
    if idx > 0:
        print(f'   Found script end at position {idx}')
    else:
        idx = content.find('</script>')
        print(f'   Found </script> at position {idx}')

with open('agent/dashboard.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Changes made:')
for c in changes_made:
    print(f'  ✓ {c}')

if not changes_made:
    print('  ❌ No changes were applied!')
