"""
Configuration management for Job Agent.
Supports environment variables, YAML config, and profile JSON.
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def get_env(key: str, default: str = "") -> str:
    """Get configuration from environment variable with fallback."""
    return os.environ.get(key, default)


def validate_config(config: "AppConfig") -> bool:
    """Validate configuration (no-op; kept for backward compatibility)."""
    return True


def validate_config_run(config: "AppConfig") -> bool:
    """Validate configuration specifically for the 'run' command (requires API key or Ollama)."""
    if config.ollama_base_url:
        return True  # Ollama is local — no API key needed
    if not config.openrouter_api_key and not config.groq_api_key:
        print("[ERROR] No AI provider configured. Set either:")
        print('   OLLAMA_BASE_URL="http://localhost:11434"   (local LLM — $0 cost, recommended)')
        print('   — or —')
        print('   OPENROUTER_API_KEY="sk-or-..."   (via OpenRouter, free tier available)')
        print('   — or —')
        print('   GROQ_API_KEY="gsk_..."           (via Groq, faster free tier, 30 req/min)')
        print("Get a free key at https://console.groq.com")
        return False
    return True


@dataclass
class AppConfig:
    """Main application configuration."""

    # API Keys
    openrouter_api_key: str = ""
    groq_api_key: str = ""

    # Ollama (local LLM, $0 cost)
    ollama_base_url: str = ""
    ollama_model: str = "qwen3"

    # Profile
    profile_path: str = "profiles/profile.json"

    # Browser
    headless: bool = False
    save_session: bool = True

    # Search & scoring settings
    min_score: int = 70
    resume_path: Optional[str] = None

    # Rate limiting
    rate_limit_base_delay: float = 3.0
    rate_limit_max_delay: float = 60.0

    # Dashboard
    dashboard_port: int = 8080
    dashboard_host: str = "127.1.1.1"

    # Database
    database_url: str = ""  # PostgreSQL connection string (empty = use SQLite)

    # Data directory for persistent storage (HF Spaces uses /data)
    data_dir: str = "."

    # Keyword generation from resume (always-on: auto-generates search keywords from resume)
    auto_keywords: bool = True

    # Word export settings
    word_export_path: str = "job_listings.docx"
    max_job_search: int = 0  # max jobs to search per platform (0 = unlimited)

    def __post_init__(self):
        """Load config from environment variables."""
        self.openrouter_api_key = get_env("OPENROUTER_API_KEY", self.openrouter_api_key)
        self.groq_api_key = get_env("GROQ_API_KEY", self.groq_api_key)
        self.ollama_base_url = get_env("OLLAMA_BASE_URL", self.ollama_base_url)
        self.ollama_model = get_env("OLLAMA_MODEL", self.ollama_model)
        self.profile_path = get_env("PROFILE_PATH", self.profile_path)
        self.resume_path = get_env("RESUME_PATH", self.resume_path) or self.resume_path
        self.headless = get_env("HEADLESS", "false").lower() == "true" or self.headless
        self.min_score = int(get_env("MIN_SCORE", str(self.min_score)))
        self.rate_limit_base_delay = float(get_env("RATE_LIMIT_BASE_DELAY", str(self.rate_limit_base_delay)))
        self.rate_limit_max_delay = float(get_env("RATE_LIMIT_MAX_DELAY", str(self.rate_limit_max_delay)))
        self.dashboard_port = int(get_env("DASHBOARD_PORT", str(self.dashboard_port)))
        self.dashboard_host = get_env("DASHBOARD_HOST", self.dashboard_host)
        self.data_dir = get_env("DATA_DIR", self.data_dir)
        self.database_url = get_env("DATABASE_URL", self.database_url)
        self.word_export_path = get_env("WORD_EXPORT_PATH", self.word_export_path)
        self.auto_keywords = get_env("AUTO_KEYWORDS", "true").lower() != "false" and self.auto_keywords
        self.max_job_search = int(get_env("MAX_JOB_SEARCH", str(self.max_job_search)))

        # Auto-detect Hugging Face Spaces environment
        # /data is the persistent volume shared across all replicas
        if get_env("SPACE_ID") or get_env("HF_SPACE", "").lower() == "true":
            self.dashboard_host = "0.0.0.0"
            self.dashboard_port = 7860
            self.data_dir = get_env("DATA_DIR", "/data")

    @property
    def logs_dir(self) -> str:
        """Get the logs directory path."""
        return os.path.join(self.data_dir, "logs")

    @property
    def sessions_dir(self) -> str:
        """Get the browser sessions directory path."""
        return os.path.join(self.data_dir, "logs", "sessions")

    @property
    def profiles_dir(self) -> str:
        """Get the profiles directory path."""
        return os.path.join(self.data_dir, "profiles")

    @property
    def applications_path(self) -> str:
        """Get the applications log file path."""
        return os.path.join(self.data_dir, "logs", "applications.json")

    @property
    def applied_path(self) -> str:
        """Get the applied jobs file path."""
        return os.path.join(self.data_dir, "logs", "applied.json")

    @property
    def resume_save_path(self) -> str:
        """Get the resume save path."""
        return os.path.join(self.data_dir, "resume.pdf")

    @property
    def is_hf_space(self) -> bool:
        """Check if running on Hugging Face Spaces."""
        return bool(get_env("SPACE_ID") or get_env("HF_SPACE", "").lower() == "true")

    @property
    def is_valid(self) -> bool:
        """Check if configuration is valid for running."""
        return bool(self.openrouter_api_key)


def load_profile(path: str = "profiles/profile.json") -> Dict[str, Any]:
    """Load and validate user profile from JSON file."""
    profile_path = Path(path)
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found at {path}. Please create profiles/profile.json")

    with open(profile_path) as f:
        profile = json.load(f)

    # Validate required fields
    required = ["name", "email", "skills", "target_roles"]
    missing = [f for f in required if f not in profile]
    if missing:
        raise ValueError(f"Profile missing required fields: {', '.join(missing)}")

    # Override from environment variables if set
    if get_env("USER_EMAIL"):
        logger.info("Overriding email from USER_EMAIL env var")
        profile["email"] = get_env("USER_EMAIL")
    if get_env("USER_PHONE"):
        logger.info("Overriding phone from USER_PHONE env var")
        profile["phone"] = get_env("USER_PHONE")

    return profile


def load_config() -> AppConfig:
    """Load application configuration from all sources."""
    return AppConfig()
