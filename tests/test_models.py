"""
Unit tests for models module.
"""

import pytest
from agent.models import Job, Platform, AIResult, ApplicationResult


class TestJob:
    """Tests for Job model."""
    
    def test_job_creation(self):
        job = Job(
            title="Software Engineer",
            company="TechCorp",
            url="https://linkedin.com/jobs/view/123",
            platform=Platform.LINKEDIN,
            location="San Francisco",
            description="Build awesome things",
        )
        assert job.title == "Software Engineer"
        assert job.company == "TechCorp"
        assert job.platform == Platform.LINKEDIN
    
    def test_job_to_dict(self):
        job = Job(title="Backend Dev", company="Startup", url="http://example.com", platform=Platform.INDEED)
        data = job.to_dict()
        
        assert data["title"] == "Backend Dev"
        assert data["platform"] == "indeed"
    
    def test_job_from_dict(self):
        data = {
            "title": "Frontend Dev",
            "company": "WebCo",
            "url": "https://example.com/job",
            "platform": "glassdoor",
            "location": "Remote",
            "description": "Great opportunity",
        }
        job = Job.from_dict(data)
        
        assert job.title == "Frontend Dev"
        assert job.platform == Platform.GLASSDOOR
    
    def test_job_from_dict_unknown_platform(self):
        data = {"title": "Dev", "company": "Co", "url": "", "platform": "unknown_platform"}
        job = Job.from_dict(data)
        assert job.platform == Platform.UNKNOWN


class TestAIResult:
    """Tests for AIResult model."""
    
    def test_ai_result_defaults(self):
        result = AIResult(match_score=85)
        assert result.match_score == 85
        assert result.matching_skills == []
        assert result.concerns == []
        assert result.cover_letter == ""
    
    def test_ai_result_full(self):
        result = AIResult(
            match_score=92,
            matching_skills=["Python", "AWS", "Docker"],
            concerns=["May require relocation"],
            cover_letter="Dear Hiring Manager...",
        )
        assert len(result.matching_skills) == 3
    
    def test_ai_result_to_dict(self):
        result = AIResult(match_score=80, matching_skills=["Java"])
        data = result.to_dict()
        assert data["match_score"] == 80
        assert data["matching_skills"] == ["Java"]


class TestApplicationResult:
    """Tests for ApplicationResult model."""
    
    def test_application_result_creation(self):
        job = Job(title="Engineer", company="Corp", url="", platform=Platform.LINKEDIN)
        ai = AIResult(match_score=75)
        
        result = ApplicationResult(
            timestamp="2024-01-15T10:30:00",
            job=job,
            ai_score=75,
            matching_skills=["Python"],
            cover_letter="I am excited...",
        )
        
        assert result.timestamp == "2024-01-15T10:30:00"
        assert result.cover_letter == "I am excited..."
    
    def test_application_result_to_dict(self):
        job = Job(title="Dev", company="Co", url="http://x.com", platform=Platform.UNKNOWN)
        ai = AIResult(match_score=65)
        
        result = ApplicationResult(
            timestamp="2024-01-01T00:00:00",
            job=job,
            ai_score=65,
        )
        
        data = result.to_dict()
        assert data["ai_score"] == 65
        assert data["job"]["title"] == "Dev"
    
    def test_application_result_from_dict(self):
        data = {
            "timestamp": "2024-02-01T12:00:00",
            "job": {"title": "Senior Dev", "company": "BigCo", "url": "", "platform": "linkedin"},
            "ai_score": 88,
            "matching_skills": ["Go", "Kubernetes"],
            "concerns": [],
            "cover_letter": "Your company stands out...",
        }
        
        result = ApplicationResult.from_dict(data)
        assert result.job.title == "Senior Dev"
        assert result.ai_score == 88