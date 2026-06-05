"""Temporary runner script."""
import os
import subprocess
import sys

os.environ["ANTHROPIC_API_KEY"] = "[REDACTED]"

result = subprocess.run(
    [sys.executable, "-m", "agent", "run", "--headless"],
    cwd=os.path.dirname(os.path.abspath(__file__)),
    env=os.environ,
)
sys.exit(result.returncode)
