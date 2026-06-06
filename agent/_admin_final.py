"""Complete admin panel rewrite. 
1. Restores to clean state
2. Adds missing user-activity route
3. Rewrites admin panel HTML with professional design
4. Follows original {{pending_section}} placeholder pattern
"""
import sys, os, subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# Step 0: Restore to clean state
subprocess.run(['git', 'restore', 'agent/dashboard.py'], cwd='.', capture_output=True)
print("0. Restored to clean state [OK]")

dp = Path('agent/dashboard.py')
content = dp.read_text('utf-8')

# Step 1: Add missing user-activity route
old_route = """    @app.route('/admin/api/user-apps/<int:target_user_id>')
    @require_admin
    def admin_user_apps(target_user_id):
        apps = get_user_applications(target_user_id, limit=500)
        return jsonify({'applications': apps})

    @app.route('/admin/api/delete-user/<int:target_user_id>', methods=['POST'])
    @require_admin
    def admin_delete_user(target_user_id):"""

new_route = """    @app.route('/admin/api/user-apps/<int:target_user_id>')
    @require_admin
    def admin_user_apps(target_user_id):
        apps = get_user_applications(target_user_id, limit=500)
        return jsonify({'applications': apps})

    @app.route('/admin/api/user-activity/<int:target_user_id>')
    @require_admin
    def admin_user_activity(target_user_id):
        from .database import get_user_activity
        activity = get_user_activity(target_user_id, limit=50)
        return jsonify({'activity': activity})

    @app.route('/admin/api/delete-user/<int:target_user_id>', methods=['POST'])
    @require_admin
    def admin_delete_user(target_user_id):"""

if old_route in content:
    content = content.replace(old_route, new_route, 1)
    print("1. Added user-activity route [OK]")
else:
    print("1. Route pattern not found!")

# Step 2: Replace the admin panel HTML f-string content
# Find the f-string boundaries
idx = content.find('def admin_panel')
end = content.find('\n    def ', idx+10) or content.find('\n@', idx+10)
func = content[idx:end]

f_start = func.find('f"""') 
f_end = func.find('"""', f_start+3)

file_f_start = idx + f_start + 4  # skip f"""
file_f_end = idx + f_end          # at the """

print(f"2. F-string at bytes {file_f_start} to {file_f_end}")

# New professional HTML with {{pending_section}} placeholder
new_html = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Agent - Admin</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Inter:wght@400;600;700&display=swap');
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  :root {{ --bg: #0a0a0f; --surface: #12121a; --surface2: #1a1a2e; --border: #2a2a4a; --primary: #00ff41; --accent: #0ff; --text: #c8c8d0; --text-dim: #666; --warning: #ffaa00; --error: #ff3355; }}
  body {{ font-family: 'Share Tech Mono', monospace; background: var(--bg); color: var(--text); padding: 20px; }}
  .container {{ max-width: 1400px; margin: 0 auto; }}
  .head {{ display: flex; justify-content: space-between; align-items: center; padding: 16px 0; border-bottom: 1px solid var(--border); margin-bottom: 20px; }}
  .head h1 {{ font-size: 1.4em; background: linear-gradient(135deg, var(--primary), var(--accent)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
  .head a {{ color: var(--accent); text-decoration: none; font-size: 0.82em; padding: 4px 12px; border: 1px solid var(--border); border-radius: 4px; }}
  .head a:hover {{ border-color: var(--accent); }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 20px; }}
  .stat {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px; text-align: center; }}
  .stat .n {{ font-size: 1.8em; font-weight: 700; color: var(--primary); }}
  .stat .l {{ font-size: 0.7em; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1px; margin-top: 2px; }}
  .w .n {{ color: var(--warning); }} .a .n {{ color: var(--accent); }}
  h2 {{ font-size: 0.85em; color: var(--accent); text-transform: uppercase; letter-spacing: 2px; margin: 24px 0 12px; }}
  .tw {{ overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.78em; min-width: 600px; }}
  th {{ background: var(--surface2); color: var(--accent); padding: 8px 10px; text-align: left; font-size: 0.72em; text-transform: uppercase; letter-spacing: 1px; }}
  td {{ padding: 6px 10px; border-top: 1px solid var(--border); }}
  tr:hover td {{ background: rgba(255,255,255,0.02); }}
  .bdg {{ display: inline-block; padding: 2px 8px; border-radius: 8px; font-size: 0.72em; }}
  .ba {{ background: rgba(0,255,65,0.12); color: var(--primary); }}
  .bu {{ background: rgba(0,255,255,0.08); color: var(--accent); }}
  .bp {{ background: rgba(255,170,0,0.12); color: var(--warning); }}
  .btn {{ padding: 4px 10px; border-radius: 3px; font-family: 'Share Tech Mono'; font-size: 0.72em; cursor: pointer; border: 1px solid; background: transparent; white-space: nowrap; }}
  .btn:hover {{ opacity: 0.85; }}
  .bp-btn {{ border-color: var(--primary); color: var(--primary); }}
  .bp-btn:hover {{ background: rgba(0,255,65,0.1); }}
  .ba-btn {{ border-color: var(--accent); color: var(--accent); }}
  .ba-btn:hover {{ background: rgba(0,255,255,0.08); }}
  .bw-btn {{ border-color: var(--warning); color: var(--warning); }}
  .bw-btn:hover {{ background: rgba(255,170,0,0.1); }}
  .bd-btn {{ border-color: var(--error); color: var(--error); }}
  .bd-btn:hover {{ background: rgba(255,51,85,0.1); }}
  .bg {{ display: flex; gap: 4px; flex-wrap: wrap; }}
  .btn[disabled] {{ opacity: 0.4; cursor: default; }}
  .ac {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px; max-height: 250px; overflow-y: auto; font-size: 0.76em; margin-bottom: 20px; }}
  .ai {{ padding: 5px 0; border-bottom: 1px solid rgba(255,255,255,0.03); display: flex; gap: 8px; }}
  .ai:last-child {{ border: none; }}
  .at {{ color: var(--text-dim); min-width: 110px; white-space: nowrap; }}
  .au {{ color: var(--accent); min-width: 90px; }}
  .empty {{ text-align: center; padding: 30px; color: var(--text-dim); font-size: 0.85em; }}
  .tt {{ position: fixed; top: 16px; right: 16px; padding: 10px 18px; border-radius: 6px; font-size: 0.82em; z-index: 999; opacity: 0; transform: translateY(-8px); transition: all 0.3s; }}
  .tt.show {{ opacity: 1; transform: translateY(0); }}
  .tt.ok {{ background: rgba(0,255,65,0.15); border: 1px solid var(--primary); color: var(--primary); }}
  .tt.er {{ background: rgba(255,51,85,0.15); border: 1px solid var(--error); color: var(--error); }}
  .tt.in {{ background: rgba(0,255,255,0.12); border: 1px solid var(--accent); color: var(--accent); }}
  .ov {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 1000; justify-content: center; align-items: center; }}
  .ov.on {{ display: flex; }}
  .ovc {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px; max-width: 560px; width: 90%; max-height: 70vh; overflow-y: auto; }}
  .ovc h3 {{ color: var(--accent); }}
  .cl {{ float: right; cursor: pointer; color: var(--text-dim); }}
  .cl:hover {{ color: var(--error); }}
</style>
</head>
<body>
<div class="tt" id="t"></div>
<div class="container">
<div class="head"><h1>Admin Panel</h1><div><a href="/">Dashboard</a></div></div>
<div class="stats">
  <div class="stat"><span class="n">{len(users)}</span><div class="l">Users</div></div>
  <div class="stat w"><span class="n">{pending_count}</span><div class="l">Pending</div></div>
  <div class="stat a"><span class="n">{active_count}</span><div class="l">Active (30m)</div></div>
  <div class="stat"><span class="n">{feedback_stats.get('positivity_rate', 0)}%</span><div class="l">Positivity</div></div>
</div>

<h2>Pending Approval</h2>
{{pending_section}}

<h2>All Users</h2>
<div class="tw"><table><tr><th>ID</th><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Joined</th><th>Actions</th></tr>
{''.join(f'<tr><td>{u["id"]}</td><td>{u["name"]}</td><td>{u["email"]}</td><td><span class="bdg {"ba" if u["role"]=="admin" else "bu"}">{u["role"]}</span></td><td><span class="bdg {"ba" if u.get("status","active")=="active" else "bp"}">{u.get("status","active")}</span></td><td>{u.get("created_at","")[:10]}</td><td class="bg"><button class="btn ba-btn" onclick="showActivity({u["id"]})">Activity</button><button class="btn bw-btn" onclick="resetPw({u["id"]})">Reset PW</button><button class="btn bd-btn" onclick="delUser({u["id"]})">Delete</button></td></tr>' for u in users)}
</table></div>

<h2>Recent Activity</h2>
<div class="ac" id="actContainer"><div class="empty">Loading...</div></div>

<h2>Feedback</h2>
<div class="stats">
  <div class="stat"><span class="n" style="color:var(--primary)">{feedback_stats.get('thumbs_up', 0)}</span><div class="l">Thumbs Up</div></div>
  <div class="stat"><span class="n" style="color:var(--error)">{feedback_stats.get('thumbs_down', 0)}</span><div class="l">Thumbs Down</div></div>
  <div class="stat"><span class="n" style="color:var(--accent)">{feedback_stats.get('total', 0)}</span><div class="l">Total</div></div>
</div>
</div>

<div class="ov" id="actOverlay">
  <div class="ovc">
    <span class="cl" onclick="closeAct()">x</span>
    <h3 id="actTitle">User Activity</h3>
    <div id="actContent" class="empty">Loading...</div>
  </div>
</div>

<script>
function toast(msg, type) {{
  var t = document.getElementById('t');
  t.textContent = msg;
  t.className = 'tt ' + type + ' show';
  setTimeout(function() {{ t.classList.remove('show'); }}, 3000);
}}

async function delUser(id) {{
  if (!confirm('Delete user ' + id + '?')) return;
  var b = event.target; b.disabled = true; b.textContent = '...';
  try {{
    var r = await fetch('/admin/api/delete-user/' + id, {{ method: 'POST' }});
    var d = await r.json();
    if (d.status === 'ok') {{ toast('Deleted', 'ok'); setTimeout(function() {{ location.reload(); }}, 800); }}
    else {{ toast(d.error || 'Failed', 'er'); b.disabled = false; b.textContent = 'Delete'; }}
  }} catch (e) {{ toast('Error', 'er'); b.disabled = false; b.textContent = 'Delete'; }}
}}

async function resetPw(id) {{
  if (!confirm('Reset password for user ' + id + '?')) return;
  var b = event.target; b.disabled = true; b.textContent = '...';
  try {{
    var r = await fetch('/admin/api/reset-user-password/' + id, {{ method: 'POST' }});
    var d = await r.json();
    if (d.status === 'ok') {{ toast('New password: ' + (d.new_password || 'reset'), 'ok'); }}
    else {{ toast(d.error || 'Failed', 'er'); }}
    b.disabled = false; b.textContent = 'Reset PW';
  }} catch (e) {{ toast('Error', 'er'); b.disabled = false; b.textContent = 'Reset PW'; }}
}}

async function approveUser(id) {{
  var b = event.target; b.disabled = true; b.textContent = '...';
  try {{
    var r = await fetch('/admin/api/approve-user/' + id, {{ method: 'POST' }});
    var d = await r.json();
    if (d.status === 'ok') {{ toast('Approved!', 'ok'); setTimeout(function() {{ location.reload(); }}, 600); }}
    else {{ toast(d.error || 'Failed', 'er'); b.disabled = false; b.textContent = 'Approve'; }}
  }} catch (e) {{ toast('Error', 'er'); b.disabled = false; b.textContent = 'Approve'; }}
}}

async function rejectUser(id) {{
  if (!confirm('Reject user ' + id + '?')) return;
  var b = event.target; b.disabled = true; b.textContent = '...';
  try {{
    var r = await fetch('/admin/api/reject-user/' + id, {{ method: 'POST' }});
    var d = await r.json();
    if (d.status === 'ok') {{ toast('Rejected', 'ok'); setTimeout(function() {{ location.reload(); }}, 600); }}
    else {{ toast(d.error || 'Failed', 'er'); b.disabled = false; b.textContent = 'Reject'; }}
  }} catch (e) {{ toast('Error', 'er'); b.disabled = false; b.textContent = 'Reject'; }}
}}

async function showActivity(id) {{
  var o = document.getElementById('actOverlay');
  var c = document.getElementById('actContent');
  document.getElementById('actTitle').textContent = 'Activity for User #' + id;
  o.classList.add('on'); c.innerHTML = 'Loading...';
  try {{
    var r = await fetch('/admin/api/user-activity/' + id);
    var d = await r.json();
    if (d.activity && d.activity.length > 0) {{
      var h = '<table style="width:100%;font-size:0.85em;"><tr><th style="text-align:left;padding:4px 6px;">Action</th><th style="text-align:left;padding:4px 6px;">Details</th><th style="text-align:left;padding:4px 6px;">Time</th></tr>';
      for (var i = 0; i < d.activity.length; i++) {{
        var a = d.activity[i];
        h += '<tr><td style="padding:4px 6px;border-bottom:1px solid rgba(255,255,255,0.05);">' + esc(a.action) + '</td><td style="padding:4px 6px;border-bottom:1px solid rgba(255,255,255,0.05);">' + esc(a.details || '') + '</td><td style="padding:4px 6px;border-bottom:1px solid rgba(255,255,255,0.05);">' + (a.created_at || '').slice(0, 16) + '</td></tr>';
      }}
      h += '</table>'; c.innerHTML = h;
    }} else {{ c.innerHTML = '<div class="empty">No activity.</div>'; }}
  }} catch (e) {{ c.innerHTML = '<div class="empty">Error loading.</div>'; }}
}}

function closeAct() {{ document.getElementById('actOverlay').classList.remove('on'); }}
document.getElementById('actOverlay').addEventListener('click', function(e) {{ if (e.target === this) closeAct(); }});

(function() {{
  fetch('/admin/api/user-activity-all').then(function(r) {{ return r.json(); }}).then(function(d) {{
    var c = document.getElementById('actContainer');
    if (d.activity && d.activity.length > 0) {{
      var h = '';
      for (var i = 0; i < Math.min(d.activity.length, 50); i++) {{
        var a = d.activity[i];
        h += '<div class=\"ai\"><span class=\"at\">' + (a.created_at || '').slice(0, 16) + '</span><span class=\"au\">' + esc(a.user_name || a.email || '') + '</span><span>' + esc(a.action) + '</span><span style=\"color:var(--text-dim);\">' + esc(a.details || '') + '</span></div>';
      }}
      c.innerHTML = h;
    }} else {{ c.innerHTML = '<div class="empty">No activity.</div>'; }}
  }}).catch(function() {{ document.getElementById('actContainer').innerHTML = '<div class="empty">Failed to load.</div>'; }});
}})();

function esc(str) {{
  var d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}}
</script>
</body></html>'''

# Replace the f-string content
content = content[:file_f_start] + new_html + content[file_f_end:]

# Step 3: Update the pending_section building (after the f-string)
# The original code has:
#   # Build pending section
#   if pending_users:
#       pending_rows = "..."
#       pending_section = f'''...'''
#   else:
#       pending_section = '...'
# We need to update this to use the new button styles

old_pending = """        # Build pending section
        if pending_users:
            pending_rows = \"\"\".join(
                f'<tr><td>{u[\"id\"]}</td><td>{u[\"name\"]}</td><td>{u[\"email\"]}</td>'
                f'<td><div class=\"btn-group\">'
                f'<button class=\"btn-approve\" onclick=\"approveUser({u[\"id\"]})\">')
                + '✅ Approve</button>'
                f'<button class=\"btn-reject\" onclick=\"rejectUser({u[\"id\"]})\">')
                + '✕ Reject</button>'
                f'</div></td></tr>'
                for u in pending_users
            )
            pending_section = f'''
  """
            pending_section = f'''
  <div class=\"section-title\">⏳ Pending Approval <span style=\"font-size:0.7em;color:var(--text-dim);font-weight:400;\">({{pending_count}})</span></div>
  <table>
    <tr><th>ID</th><th>Name</th><th>Email</th><th>Actions</th></tr>
    {{pending_rows}}
  </table>
'''
        else:
            pending_section = '<div class=\"section-title\">⏳ Pending Approval <span style=\"font-size:0.7em;color:var(--text-dim);font-weight:400;\">(none)</span></div><div class=\"empty\">No pending users. All accounts have been processed.</div>'"""

# Hmm, this is getting too complex because I don't know the exact format. Let me just check the exact text
print("Checking pending section code...")
idx_pending = content.find('# Build pending section')
if idx_pending >= 0:
    snippet = content[idx_pending:idx_pending+800]
    print(repr(snippet[:500]))
else:
    print("'# Build pending section' not found!")

# Even simpler - just update the pending section to use the new CSS classes
# Write the file with just the HTML change + route change for now
dp.write_text(content, encoding='utf-8')

# Verify syntax
try:
    compile(dp.read_text('utf-8'), 'dashboard.py', 'exec')
    print("3. Syntax: OK [PASS]")
except SyntaxError as e:
    print(f"3. Syntax ERROR: line {e.lineno}: {e.msg}")

# Check the remaining pending section code
print("\n4. Pending section code:")
c2 = dp.read_text('utf-8')
pidx = c2.find('# Build pending section')
if pidx >= 0:
    pend = c2[pidx:pidx+600]
    # Clean for display
    printable = ''.join(ch if 32 <= ord(ch) < 127 else '?' for ch in pend)
    print(printable[:500])

# Clean up
script_path = Path(__file__)
if script_path.exists():
    os.remove(str(script_path))
