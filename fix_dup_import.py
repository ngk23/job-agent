"""Remove duplicate import in google_login route."""
import re

path = "job-agent/agent/dashboard.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Find the duplicate import pattern
old = (
    "        from .oauth import get_google_oauth, is_google_oauth_configured\n"
    "        if not is_google_oauth_configured():\n"
    "            return jsonify({'status': 'error', 'error': 'Google Sign-In not configured'}), 501\n"
    "        from .oauth import get_google_oauth\n"
    "        oauth = get_google_oauth()"
)
new = (
    "        from .oauth import get_google_oauth, is_google_oauth_configured\n"
    "        if not is_google_oauth_configured():\n"
    "            return jsonify({'status': 'error', 'error': 'Google Sign-In not configured'}), 501\n"
    "        oauth = get_google_oauth()"
)

if old in content:
    content = content.replace(old, new, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK: Duplicate import removed")
else:
    # Try with \r\n line endings
    old_crlf = old.replace("\n", "\r\n")
    new_crlf = new.replace("\n", "\r\n")
    if old_crlf in content:
        content = content.replace(old_crlf, new_crlf, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("OK: Duplicate import removed (CRLF)")
    else:
        print("FAIL: Pattern not found")
        # Debug: show context around 'get_google_oauth'
        idx = content.find("get_google_oauth, is_google_oauth_configured")
        if idx >= 0:
            print(f"Found combined import at index {idx}")
            print(repr(content[idx:idx+400]))
