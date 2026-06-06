"""Rewrite admin panel with simpler f-string expressions"""
import sys, os
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

dp = Path('agent/dashboard.py')
content = dp.read_text('utf-8')

# Find admin_panel f-string boundaries
idx = content.find('def admin_panel')
end = content.find('\n    def ', idx+10) or content.find('\n@', idx+10)
func = content[idx:end]
f_start = func.find('f"""')
f_end = func.find('"""', f_start+3)
file_f_start = idx + f_start + 4
file_f_end = idx + f_end

print(f"Replacing f-string at bytes {file_f_start} to {file_f_end}")

# Build new HTML - use simple expressions to avoid nesting issues
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
  .head h1 {{ font-size: 1.4em; background: linear-gradient(135deg, var(--primary), var(--accent)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: 2px; }}
  .head a {{ color: var(--accent); text-decoration: none; font-size: 0.85em; padding: 4px 12px; border: 1px solid var(--border); border-radius: 4px; }}
  .head a:hover {{ border-color: var(--accent); background: rgba(0,255,255,0.08); }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 20px; }}
  .stat {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; text-align: center; }}
  .stat .n {{ font-size: 1.8em; font-weight: 700; color: var(--primary); display: block; }}
  .stat .l {{ font-size: 0.7em; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1px; }}
  .stat.w .n {{ color: var(--warning); }}
  .stat.a .n {{ color: var(--accent); }}
  h2 {{ font-size: 0.85em; color: var(--accent); text-transform: uppercase; letter-spacing: 2px; margin: 24px 0 12px; }}
  .tw {{ overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.78em; min-width: 600px; }}
  th {{ background: var(--surface2); color: var(--accent); padding: 8px 10px; text-align: left; font-size: 0.75em; text-transform: uppercase; letter-spacing: 1px; white-space: nowrap; }}
  td {{ padding: 6px 10px; border-top: 1px solid var(--border); }}
  tr:hover td {{ background: rgba(255,255,255,0.02); }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 8px; font-size: 0.75em; }}
  .badge-a {{ background: rgba(0,255,65,0.12); color: var(--primary); }}
  .badge-u {{ background: rgba(0,255,255,0.08); color: var(--accent); }}
  .badge-p {{ background: rgba(255,170,0,0.12); color: var(--warning); }}
  .btn {{ padding: 4px 10px; border-radius: 3px; font-family: 'Share Tech Mono'; font-size: 0.75em; cursor: pointer; border: 1px solid; background: transparent; white-space: nowrap; transition: all 0.2s; }}
  .btn-p {{ border-color: var(--primary); color: var(--primary); }}
  .btn-p:hover {{ background: rgba(0,255,65,0.12); }}
  .btn-a {{ border-color: var(--accent); color: var(--accent); }}
  .btn-a:hover {{ background: rgba(0,255,255,0.1); }}
  .btn-w {{ border-color: var(--warning); color: var(--warning); }}
  .btn-w:hover {{ background: rgba(255,170,0,0.12); }}
  .btn-d {{ border-color: var(--error); color: var(--error); }}
  .btn-d:hover {{ background: rgba(255,51,85,0.12); }}
  .btn:disabled {{ opacity: 0.4; cursor: not-allowed; }}
  .ac {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 20px; max-height: 250px; overflow-y: auto; font-size: 0.76em; }}
  .ai {{ padding: 5px 0; border-bottom: 1px solid rgba(255,255,255,0.03); display: flex; gap: 8px; }}
  .ai:last-child {{ border: none; }}
  .at {{ color: var(--text-dim); white-space: nowrap; min-width: 110px; }}
  .au {{ color: var(--accent); min-width: 90px; }}
  .empty {{ text-align: center; padding: 30px; color: var(--text-dim); font-size: 0.85em; }}
  .toast {{ position: fixed; top: 16px; right: 16px; padding: 10px 18px; border-radius: 6px; font-size: 0.82em; z-index: 9999; opacity: 0; transform: translateY(-8px); transition: all 0.3s; pointer-events: none; }}
  .toast.s {{ opacity: 1; transform: translateY(0); }}
  .toast.ok {{ background: rgba(0,255,65,0.15); border: 1px solid var(--primary); color: var(--primary); }}
  .toast.err {{ background: rgba(255,51,85,0.15); border: 1px solid var(--error); color: var(--error); }}
  .toast.inf {{ background: rgba(0,255,255,0.12); border: 1px solid var(--accent); color: var(--accent); }}
  .ov {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 1000; justify-content: center; align-items: center; }}
  .ov.on {{ display: flex; }}
  .ovc {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px; max-width: 560px; width: 90%; max-height: 70vh; overflow-y: auto; }}
  .ovc h3 {{ color: var(--accent); margin-bottom: 10px; }}
  .ovx {{ float: right; cursor: pointer; color: var(--text-dim); font-size: 1.3em; }}
  .ovx:hover {{ color: var(--error); }}
</style>
</head>
<body>
<div class="toast" id="t"></div>
<div class="container">

<div class="head">
  <h1>Admin Panel</h1>
  <div><a href="/">Dashboard</a></div>
</div>

<div class="stats">
  <div class="stat"><span class="n">{len(users)}</span><span class="l">Users</span></div>
  <div class="stat w"><span class="n">{pending_count}</span><span class="l">Pending</span></div>
  <div class="stat a"><span class="n">{active_count}</span><span class="l">Active</span></div>
  <div class="stat"><span class="n">{feedback_stats.get('positivity_rate', 0)}%</span><span class="l">Positivity</span></div>
</div>

<h2>Pending Approval</h2>
'''

# Add pending users section separately (not inside an f-string expression)
if True:  # Just for indentation
    pending_table_rows = ''.join(
        f'<tr><td>{u["id"]}</td><td>{u["name"]}</td><td>{u["email"]}</td><td>{u.get("created_at","")[:10]}</td><td class="btn-group"><button class="btn btn-p" onclick="approveUser({u["id"]})">Approve</button><button class="btn btn-d" onclick="rejectUser({u["id"]})">Reject</button></td></tr>'
        for u in eval("pending_users") 
    ) if eval("pending_users") else '<div class="empty">No users pending approval.</div>'

# Actually, we can't use eval inside a string replacement. Let me just insert a placeholder and handle it in the f-string.

# Let me take a completely different approach - build the HTML as simple parts
# The pending section uses a simple conditional
pending_html = '{"" if pending_users else '<div class="empty">No users pending approval.</div>'}' + '\n'
# No, even simpler. Let me not use nested f-strings at all.

# Actually, looking at this more carefully, the simplest approach is:
# In the f-string, use {pending_section} where pending_section is pre-built in Python

# Let me check the original code to see how it handled this
# The original had: if pending_users: ... in Python, then embedded the HTML

# OK let me just build the HTML with a simpler approach - split the pending section out

new_html_cont = '''
  <div class="tw">
    <table>
      <tr><th>ID</th><th>Name</th><th>Email</th><th>Registered</th><th>Actions</th></tr>
'''

# Build pending rows as a separate Python variable
pending_rows_str = ''.join(
    f'<tr><td>{u["id"]}</td><td>{u["name"]}</td><td>{u["email"]}</td><td>{u.get("created_at","")[:10]}</td><td><button class="btn btn-p" onclick="approveUser({u["id"]})">Approve</button><button class="btn btn-d" onclick="rejectUser({u["id"]})">Reject</button></td></tr>'
    for u in eval("pending_users")
) if True else ''

# Hmm, this eval approach won't work for string replacement. Let me think differently.

# Actually the simplest approach: put the f-string expression as a separate variable
# and embed it as {pending_section} in the HTML

# But wait - the entire HTML is ONE big f-string. So I need to embed Python expressions
# using {}. The issue was with nested f-strings.

# Let me try the simplest approach: just put everything in one f-string but avoid
# nested f-strings entirely. Use simple conditionals.

new_html_full = '''<!DOCTYPE html>
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
  .head h1 {{ font-size: 1.4em; background: linear-gradient(135deg, var(--primary), var(--accent)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: 2px; }}
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
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 8px; font-size: 0.72em; }}
  .ba {{ background: rgba(0,255,65,0.12); color: var(--primary); }}
  .bu {{ background: rgba(0,255,255,0.08); color: var(--accent); }}
  .bp {{ background: rgba(255,170,0,0.12); color: var(--warning); }}
  .btn {{ padding: 4px 10px; border-radius: 3px; font-family: 'Share Tech Mono'; font-size: 0.72em; cursor: pointer; border: 1px solid; background: transparent; white-space: nowrap; }}
  .btn:hover {{ opacity: 0.8; }}
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
  .toast {{ position: fixed; top: 16px; right: 16px; padding: 10px 18px; border-radius: 6px; font-size: 0.82em; z-index: 999; opacity: 0; transform: translateY(-8px); transition: all 0.3s; }}
  .toast.show {{ opacity: 1; transform: translateY(0); }}
  .toast.ok {{ background: rgba(0,255,65,0.15); border: 1px solid var(--primary); color: var(--primary); }}
  .toast.er {{ background: rgba(255,51,85,0.15); border: 1px solid var(--error); color: var(--error); }}
  .toast.in {{ background: rgba(0,255,255,0.12); border: 1px solid var(--accent); color: var(--accent); }}
  .ov {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 1000; justify-content: center; align-items: center; }}
  .ov.on {{ display: flex; }}
  .ovc {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px; max-width: 560px; width: 90%; max-height: 70vh; overflow-y: auto; }}
  .ovc h3 {{ color: var(--accent); }}
  .cl {{ float: right; cursor: pointer; color: var(--text-dim); font-size: 1.2em; }}
  .cl:hover {{ color: var(--error); }}
</style>
</head>
<body>
<div class="toast" id="t"></div>
<div class="container">
<div class="head"><h1>Admin Panel</h1><div><a href="/">Dashboard</a></div></div>
<div class="stats">
  <div class="stat"><span class="n">{len(users)}</span><div class="l">Users</div></div>
  <div class="stat w"><span class="n">{pending_count}</span><div class="l">Pending</div></div>
  <div class="stat a"><span class="n">{active_count}</span><div class="l">Active</div></div>
  <div class="stat"><span class="n">{feedback_stats.get('positivity_rate', 0)}%</span><div class="l">Positivity</div></div>
</div>

<h2>Pending Approval</h2>
'''

# Build pending section as a simple Python conditional
if eval("1"):  # placeholder - will be replaced with actual logic
    pass

# Actually, let me just build the full HTML string directly in Python
# and then compute the pending section separately

# I'll restructure the admin_panel function to compute pending_section first
# and then embed it as {pending_section} in the HTML

# Let me read the original code and see how to best modify it
# The original admin_panel function is:
# def admin_panel():
#     users = get_all_users()
#     pending_users = get_pending_users()
#     pending_count = len(pending_users)
#     feedback_stats = get_feedback_summary()
#     active_count = get_active_users_count(minutes=30)
#     html = f"""..."""
#     # Build pending section
#     if pending_users:
#         ...
#     return render_template_string(html)

# Wait! The ORIGINAL code had the pending section BUILT IN PYTHON, not inside the f-string!
# Then it was EMBEDDED as {pending_section} in the HTML!
# My rewrite removed that pattern!

# Let me check the original code again
orig = content[:file_f_start-4]  # Before f"""
print(f"\nFirst 100 chars before f-string: {repr(orig[-100:])}")
print(f"\nLast 100 chars after f-string: {repr(content[file_f_end:file_f_end+100])}")

# I need to read the original admin_panel code structure more carefully!
