"""Launcher script - runs the job agent.

Set your OPENROUTER_API_KEY environment variable before running:
    export OPENROUTER_API_KEY="sk-or-..."
    python run_agent.py
"""
import os
import sys
import subprocess

# Run the agent: search, score, generate CVs, export to Word + PDF
cmd = [sys.executable, "-m", "agent", "run", "--headless"]
result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
sys.exit(result.returncode)
