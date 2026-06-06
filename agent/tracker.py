"""
Application tracker for job applications.
Supports per-user JSON files via user_id parameter.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .models import ApplicationResult, Job, AIResult


class ApplicationTracker:
    """Track and persist job application results.
    
    Supports per-user storage: if user_id is provided, saves to
    applications_{user_id}.json to isolate each user's results.
    When running as a subprocess, uses the USER_ID env var.
    """
    
    def __init__(self, log_path: Optional[str] = None, data_dir: Optional[str] = None, user_id: Optional[int] = None):
        # Auto-detect user_id from env if not provided (subprocess mode)
        if user_id is None:
            env_uid = os.environ.get("USER_ID", "")
            user_id = int(env_uid) if env_uid.isdigit() else None
        self.user_id = user_id
        
        if log_path:
            self.log_path = Path(log_path)
        elif data_dir:
            if user_id:
                self.log_path = Path(data_dir) / "logs" / f"applications_{user_id}.json"
            else:
                self.log_path = Path(data_dir) / "logs" / "applications.json"
        else:
            if user_id:
                self.log_path = Path(f"logs/applications_{user_id}.json")
            else:
                self.log_path = Path("logs/applications.json")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
    
    def save(self, job: Job, ai_result: AIResult):
        """Save a scored job result."""
        history = self.load_all()
        
        result = ApplicationResult(
            timestamp=datetime.now().isoformat(),
            job=job,
            ai_score=ai_result.match_score,
            matching_skills=ai_result.matching_skills,
            concerns=ai_result.concerns,
            cover_letter=ai_result.cover_letter,
        )
        
        history.append(result.to_dict())
        self.log_path.write_text(json.dumps(history, indent=2))
    
    def load_all(self) -> List[dict]:
        """Load all application results."""
        if not self.log_path.exists():
            return []
        
        try:
            content = self.log_path.read_text().strip()
            if not content:
                return []
            
            data = json.loads(content)
            if not isinstance(data, list):
                return [data]
            return data
        except (json.JSONDecodeError, IOError) as e:
            return []
    
    def get_stats(self) -> dict:
        """Get statistics about scored jobs."""
        history = self.load_all()
        
        total = len(history)
        scores = [r.get("ai_score", 0) or 0 for r in history if r.get("ai_score") is not None]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        platforms = {}
        for r in history:
            platform = r.get("job", {}).get("platform", "unknown")
            platforms[platform] = platforms.get(platform, 0) + 1
        
        return {
            "total_jobs_reviewed": total,
            "average_match_score": round(avg_score, 1),
            "by_platform": platforms,
        }
    
    def get_recent(self, limit: int = 10) -> List[dict]:
        """Get most recent application results."""
        history = self.load_all()
        return history[-limit:] if history else []
    
    def get_high_match(self, min_score: int = 80) -> List[dict]:
        """Get jobs with high match scores."""
        history = self.load_all()
        return [r for r in history if (r.get("ai_score", 0) or 0) >= min_score]
    
    def clear(self):
        """Clear all application history."""
        if self.log_path.exists():
            self.log_path.unlink()