"""Temporary runner script.

Set your OPENROUTER_API_KEY environment variable before running.
"""
import os
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "agent", "run", "--headless"],
    cwd=os.path.dirname(os.path.abspath(__file__)),
    env=os.environ,
)
sys.exit(result.returncode)
