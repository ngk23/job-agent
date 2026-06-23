"""Wrap the usage check in /run route with try/except to silently fall through on DB errors."""
import re

with open("agent/dashboard.py", "r", encoding="utf-8") as f:
    content = f.read()

if "USAGE_CHECK_SAFE" in content:
    print("ALREADY_PATCHED")
    exit(0)

# Find the usage check section and wrap it in try/except
old_block = """        # Check daily usage limits before starting
        init_usage_table()
        current_user_id = get_user_id()
        if current_user_id:
            usage_check = can_run_search(current_user_id)
            if not usage_check.get('allowed', False):
                reason = usage_check.get('reason', 'Daily limit reached')
                logger.warning(f"User {current_user_id} blocked by usage limits: {reason}")
                return jsonify({
                    'status': 'error',
                    'error': reason,
                    'usage_blocked': True,
                    'usage_info': usage_check,
                }), 429
            increment_search_count(current_user_id)

        # Reset state"""

new_block = """        # Check daily usage limits before starting
        try:
            init_usage_table()
            current_user_id = get_user_id()
            if current_user_id:
                usage_check = can_run_search(current_user_id)
                if not usage_check.get('allowed', False):
                    reason = usage_check.get('reason', 'Daily limit reached')
                    logger.warning(f"User {current_user_id} blocked by usage limits: {reason}")
                    return jsonify({
                        'status': 'error',
                        'error': reason,
                        'usage_blocked': True,
                        'usage_info': usage_check,
                    }), 429
                increment_search_count(current_user_id)
        except Exception as e:
            logger.error(f"Usage check failed (allowing run): {e}")

        # Reset state"""

if old_block in content:
    content = content.replace(old_block, new_block)
    print("Fixed: usage check wrapped in try/except")
else:
    print("WARNING: Pattern not found - checking for alternatives...")
    # Try to find the code by anchor
    if "init_usage_table()" in content:
        idx = content.index("init_usage_table()")
        print(f"Found init_usage_table() at position {idx}")
        print(content[idx-50:idx+400])
    exit(1)

# Add marker
content = content.replace("# FIXED_GROQ_BUGS ─────────────────────────────────────────────────────────────",
                          "# FIXED_GROQ_BUGS ─────────────────────────────────────────────────────────────\n# USAGE_CHECK_SAFE")

with open("agent/dashboard.py", "w", encoding="utf-8") as f:
    f.write(content)

print("PATCHED")
