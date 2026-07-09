"""Feedback learning module for Job Agent.
Analyzes user feedback patterns and generates insights for agent self-improvement.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def get_feedback_patterns(days: int = 30) -> Dict[str, Any]:
    """Analyze feedback from the last N days and extract learning patterns."""
    from .database import get_db

    conn = get_db()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    rows = conn.execute(
        """SELECT jf.*, a.matching_skills, a.title, a.company
           FROM job_feedback jf
           LEFT JOIN applications a ON jf.application_id = a.id
           WHERE jf.created_at > ?
           ORDER BY jf.created_at DESC""",
        (cutoff,),
    ).fetchall()

    if not rows:
        return {"has_feedback": False, "insights": "No feedback data available yet."}

    records = [dict(r) for r in rows]

    # Analyze by company
    company_ratings = {}
    for r in records:
        company = r.get("company") or r.get("company", "") or "Unknown"
        if company not in company_ratings:
            company_ratings[company] = {"up": 0, "down": 0, "total": 0}
        if r["rating"] == 1:
            company_ratings[company]["up"] += 1
        elif r["rating"] == -1:
            company_ratings[company]["down"] += 1
        company_ratings[company]["total"] += 1

    # Analyze by job title keywords
    keyword_ratings = {}
    for r in records:
        title = (r.get("title") or r.get("job_title", "") or "").lower()
        words = set(title.split())
        for word in words:
            if len(word) < 3:
                continue
            if word not in keyword_ratings:
                keyword_ratings[word] = {"up": 0, "down": 0, "total": 0}
            if r["rating"] == 1:
                keyword_ratings[word]["up"] += 1
            elif r["rating"] == -1:
                keyword_ratings[word]["down"] += 1
            keyword_ratings[word]["total"] += 1

    # Extract skills from positive/negative feedback
    positive_skills = set()
    negative_skills = set()
    for r in records:
        skills_raw = r.get("matching_skills", "[]")
        if isinstance(skills_raw, str):
            try:
                skills = json.loads(skills_raw)
            except (json.JSONDecodeError, TypeError):
                skills = []
        else:
            skills = skills_raw or []
        if r["rating"] == 1:
            positive_skills.update(skills)
        elif r["rating"] == -1:
            negative_skills.update(skills)

    # Build insights
    insight_parts = []

    # Company insights
    good_companies = {
        c: d
        for c, d in company_ratings.items()
        if d["up"] > d["down"] and d["total"] >= 2
    }
    bad_companies = {
        c: d
        for c, d in company_ratings.items()
        if d["down"] >= d["up"] and d["total"] >= 2
    }

    if good_companies:
        top = sorted(
            good_companies.items(),
            key=lambda x: x[1]["up"] / x[1]["total"],
            reverse=True,
        )[:5]
        companies_str = ", ".join(
            f"{c} ({d['up']}/{d['total']} positive)" for c, d in top
        )
        insight_parts.append(f"Preferred companies: {companies_str}")

    if bad_companies:
        worst = sorted(
            bad_companies.items(),
            key=lambda x: x[1]["down"] / x[1]["total"],
            reverse=True,
        )[:3]
        companies_str = ", ".join(
            f"{c} ({d['down']}/{d['total']} negative)" for c, d in worst
        )
        insight_parts.append(f"Companies to deprioritize: {companies_str}")

    # Skill insights
    if positive_skills:
        insight_parts.append(
            f"Skills with positive feedback: {', '.join(sorted(positive_skills)[:10])}"
        )
    if negative_skills:
        insight_parts.append(
            f"Skills with negative feedback: {', '.join(sorted(negative_skills)[:5])}"
        )

    # Total stats
    total_up = sum(1 for r in records if r["rating"] == 1)
    total_down = sum(1 for r in records if r["rating"] == -1)
    insight_parts.append(
        f"Overall: {total_up} thumbs up, {total_down} thumbs down ({len(records)} total ratings)"
    )

    return {
        "has_feedback": True,
        "total_ratings": len(records),
        "thumbs_up": total_up,
        "thumbs_down": total_down,
        "insights": " | ".join(insight_parts),
        "good_companies": list(good_companies.keys())[:5],
        "bad_companies": list(bad_companies.keys())[:3],
        "positive_skills": list(positive_skills)[:10],
        "negative_skills": list(negative_skills)[:5],
    }


def get_feedback_insights_for_prompt(days: int = 30) -> str:
    """Get formatted feedback insights for AI prompt injection."""
    patterns = get_feedback_patterns(days=days)
    if not patterns.get("has_feedback"):
        return ""
    insights = patterns.get("insights", "")
    return f"""
<user_feedback_insights>
The following patterns were learned from user feedback on previous job recommendations:
{insights}
Use these insights to better prioritize jobs that match user preferences.
Jobs matching preferred companies or positive-feedback skills should score higher.
Jobs matching deprioritized companies or negative-feedback skills should score lower.
</user_feedback_insights>
"""


def get_feedback_insights_short() -> str:
    """Get a short one-line summary for terminal display."""
    patterns = get_feedback_patterns(days=7)
    if not patterns.get("has_feedback"):
        return "No feedback data yet"
    return f"{patterns['thumbs_up']}up {patterns['thumbs_down']}down - {patterns.get('insights', '')[:100]}"
