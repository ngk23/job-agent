"""
Unit tests for config and tracker modules.
"""

import json
import tempfile
from pathlib import Path

import pytest

from agent.config import AppConfig, get_env, load_profile
from agent.models import AIResult, Job, Platform
from agent.tracker import ApplicationTracker


class TestAppConfig:
    """Tests for AppConfig."""

    def test_defaults(self):
        config = AppConfig()
        assert config.min_score == 70
        assert config.headless is False

    def test_env_override(self):
        import os

        os.environ["MIN_SCORE"] = "85"

        config = AppConfig()
        assert config.min_score == 85

        # Cleanup
        del os.environ["MIN_SCORE"]

    def test_is_valid_without_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        config = AppConfig()
        assert config.is_valid is False

    def test_is_valid_with_api_key(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
        config = AppConfig()
        assert config.is_valid is True


class TestLoadProfile:
    """Tests for load_profile function."""

    def test_loads_valid_profile(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "name": "Test User",
                    "email": "test@example.com",
                    "skills": ["Python", "JavaScript"],
                    "target_roles": ["Software Engineer"],
                },
                f,
            )
            f.flush()
            f.seek(0)
            profile = load_profile(f.name)
            assert profile["name"] == "Test User"
            assert profile["email"] == "test@example.com"
            f.close()  # Close before unlink on Windows

    def test_raises_on_missing_fields(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "name": "Test User",
                    # Missing email, skills, target_roles
                },
                f,
            )
            f.flush()
            f.close()
            with pytest.raises(ValueError, match="missing required fields"):
                load_profile(f.name)

    def test_raises_on_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            load_profile("/nonexistent/path/profile.json")


class TestApplicationTracker:
    """Tests for ApplicationTracker."""

    def setup_method(self):
        """Create temporary log file."""
        self.temp_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self.temp_file.write("[]")
        self.temp_file.flush()
        self.tracker = ApplicationTracker(self.temp_file.name)

    def teardown_method(self):
        """Clean up temp file."""
        try:
            Path(self.temp_file.name).unlink()
        except:
            pass

    def test_save_and_load(self):
        job = Job(
            title="Engineer",
            company="Corp",
            url="http://example.com",
            platform=Platform.LINKEDIN,
        )
        ai_result = AIResult(
            match_score=80, matching_skills=["Python"], cover_letter="Test letter"
        )

        self.tracker.save(job, ai_result)

        history = self.tracker.load_all()
        assert len(history) == 1
        assert history[0]["job"]["title"] == "Engineer"
        assert history[0]["ai_score"] == 80

    def test_get_stats_empty(self):
        stats = self.tracker.get_stats()
        assert stats["total_jobs_reviewed"] == 0

    def test_get_stats_with_data(self):
        job = Job(
            title="Engineer",
            company="Corp",
            url="http://example.com",
            platform=Platform.LINKEDIN,
        )
        ai_result = AIResult(match_score=75)

        self.tracker.save(job, ai_result)
        self.tracker.save(job, ai_result)

        stats = self.tracker.get_stats()
        assert stats["total_jobs_reviewed"] == 2
        assert stats["average_match_score"] == 75.0

    def test_get_recent(self):
        job = Job(
            title="Engineer",
            company="Corp",
            url="http://example.com",
            platform=Platform.LINKEDIN,
        )
        ai_result = AIResult(match_score=70)

        for i in range(5):
            self.tracker.save(job, ai_result)

        recent = self.tracker.get_recent(limit=3)
        assert len(recent) == 3

    def test_clear(self):
        # Create a fresh tracker with its own file path to avoid conflicts
        import uuid

        temp_path = f"logs/test_clear_{uuid.uuid4().hex[:8]}.json"
        tracker = ApplicationTracker(temp_path)

        job = Job(
            title="Engineer",
            company="Corp",
            url="http://example.com",
            platform=Platform.LINKEDIN,
        )
        ai_result = AIResult(match_score=70)

        tracker.save(job, ai_result)
        assert len(tracker.load_all()) == 1

        tracker.clear()
        assert len(tracker.load_all()) == 0

        # Cleanup
        try:
            Path(temp_path).unlink(missing_ok=True)
        except:
            pass
