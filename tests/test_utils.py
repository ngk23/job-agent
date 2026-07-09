"""
Unit tests for Job Agent utilities.
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path

import pytest

from agent.models import AIResult, ApplicationResult, Job, Platform
from agent.utils import RateLimiter, ResumeHandler, retry_async


class TestRateLimiter:
    """Tests for RateLimiter class."""

    def test_initial_delay(self):
        limiter = RateLimiter(base_delay=2.0, max_delay=10.0)
        assert limiter.current_delay == 2.0
        assert limiter.base_delay == 2.0

    def test_failure_increases_delay(self):
        limiter = RateLimiter(base_delay=2.0, max_delay=10.0)
        limiter.failure()
        assert limiter.current_delay == 3.0  # 2.0 * 1.5
        assert limiter.failures == 1

    def test_success_decreases_delay(self):
        limiter = RateLimiter(base_delay=2.0, max_delay=10.0)
        limiter.current_delay = 4.0
        limiter.success()
        assert limiter.current_delay == 3.2  # 4.0 * 0.8

    def test_delay_caps_at_max(self):
        limiter = RateLimiter(base_delay=2.0, max_delay=10.0)
        for _ in range(10):
            limiter.failure()
        assert limiter.current_delay == 10.0

    @pytest.mark.asyncio
    async def test_wait_returns_without_error(self):
        limiter = RateLimiter(base_delay=0.1, max_delay=0.5)
        await limiter.wait()
        assert True  # No exception means success


class TestResumeHandler:
    """Tests for ResumeHandler class."""

    def test_init_without_path(self):
        handler = ResumeHandler()
        assert handler.resume_path is None
        assert handler.parsed_text == ""

    def test_init_with_path(self):
        handler = ResumeHandler("resume.pdf")
        assert handler.resume_path == Path("resume.pdf")
        assert handler.file_name == "resume.pdf"

    def test_load_nonexistent_file(self):
        handler = ResumeHandler("nonexistent_file.pdf")
        result = handler.load()
        assert result is False

    def test_load_txt_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Test resume content")
            f.flush()
            f.close()
            handler = ResumeHandler(f.name)
            result = handler.load()
            assert result is True
            assert handler.parsed_text == "Test resume content"

    def test_get_for_cover_letter_empty(self):
        handler = ResumeHandler()
        handler.parsed_text = ""
        assert handler.get_for_cover_letter() == "Resume on file"

    def test_get_for_cover_letter_truncates_long_text(self):
        handler = ResumeHandler()
        handler.parsed_text = "a" * 2000
        result = handler.get_for_cover_letter()
        assert len(result) == 1003  # 1000 chars + "..."


class TestModels:
    """Tests for data models."""

    def test_job_to_dict(self):
        job = Job(
            title="Software Engineer",
            company="Tech Corp",
            url="https://example.com/job",
            platform=Platform.LINKEDIN,
        )
        data = job.to_dict()
        assert data["title"] == "Software Engineer"
        assert data["company"] == "Tech Corp"
        assert data["platform"] == "linkedin"
        assert "applied" not in data

    def test_job_from_dict(self):
        data = {
            "title": "Backend Engineer",
            "company": "Startup Inc",
            "url": "https://example.com/job",
            "platform": "indeed",
        }
        job = Job.from_dict(data)
        assert job.title == "Backend Engineer"
        assert job.platform == Platform.INDEED

    def test_ai_result_defaults(self):
        result = AIResult(match_score=85)
        assert result.match_score == 85
        assert result.matching_skills == []
        assert result.cover_letter == ""

    def test_application_result_to_dict(self):
        job = Job(title="Test", company="Co", url="", platform=Platform.UNKNOWN)
        ai_result = AIResult(match_score=75, matching_skills=["Python", "JS"])
        result = ApplicationResult(
            timestamp="2024-01-01T00:00:00",
            job=job,
            ai_score=75,
            matching_skills=["Python", "JS"],
        )
        data = result.to_dict()
        assert data["ai_score"] == 75
        assert data["job"]["title"] == "Test"


class TestRetryAsync:
    """Tests for retry_async function."""

    @pytest.mark.asyncio
    async def test_successful_call(self):
        async def success_func(x):
            return x * 2

        result = await retry_async(success_func, 5, max_retries=3, context="test")
        assert result == 10

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary failure")
            return "success"

        result = await retry_async(
            flaky_func, max_retries=3, base_delay=0.1, context="test"
        )
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_all_retries(self):
        async def always_fails():
            raise ValueError("Always fails")

        with pytest.raises(ValueError):
            await retry_async(
                always_fails, max_retries=2, base_delay=0.1, context="test"
            )
