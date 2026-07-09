"""
Data models for Job Agent.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class Platform(Enum):
    """Supported job platforms."""

    LINKEDIN = "linkedin"
    INDEED = "indeed"
    GLASSDOOR = "glassdoor"
    MONSTER = "monster"
    REED = "reed"
    ADZUNA = "adzuna"
    UNKNOWN = "unknown"


@dataclass
class Job:
    """Represents a job listing."""

    title: str
    company: str
    url: str
    platform: Platform = Platform.UNKNOWN
    location: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "company": self.company,
            "url": self.url,
            "platform": (
                self.platform.value
                if isinstance(self.platform, Platform)
                else self.platform
            ),
            "location": self.location,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        platform = data.get("platform", "unknown")
        if isinstance(platform, str):
            try:
                platform = Platform(platform)
            except ValueError:
                platform = Platform.UNKNOWN
        return cls(
            title=data.get("title", "Unknown"),
            company=data.get("company", "Unknown"),
            url=data.get("url", ""),
            platform=platform,
            location=data.get("location", ""),
            description=data.get("description", ""),
        )


@dataclass
class AIResult:
    """Result from AI cover letter tailoring."""

    match_score: int
    matching_skills: List[str] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)
    cover_letter: str = ""

    def to_dict(self) -> dict:
        return {
            "match_score": self.match_score,
            "matching_skills": self.matching_skills,
            "concerns": self.concerns,
            "cover_letter": self.cover_letter,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AIResult":
        return cls(
            match_score=data.get("match_score", 0),
            matching_skills=data.get("matching_skills", []),
            concerns=data.get("concerns", []),
            cover_letter=data.get("cover_letter", ""),
        )


@dataclass
class ApplicationResult:
    """Result of a job application attempt."""

    timestamp: str
    job: Job
    ai_score: int
    matching_skills: List[str] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)
    cover_letter: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "job": self.job.to_dict() if isinstance(self.job, Job) else self.job,
            "ai_score": self.ai_score,
            "matching_skills": self.matching_skills,
            "concerns": self.concerns,
            "cover_letter": self.cover_letter,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ApplicationResult":
        job_data = data.get("job", {})
        if isinstance(job_data, dict):
            job = Job.from_dict(job_data)
        else:
            job = job_data
        return cls(
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            job=job,
            ai_score=data.get("ai_score", 0),
            matching_skills=data.get("matching_skills", []),
            concerns=data.get("concerns", []),
            cover_letter=data.get("cover_letter", ""),
        )
