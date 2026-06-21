"""
AI integration for job application tailoring.
Uses OpenRouter (via OpenAI SDK) for all AI operations.
"""

import json
import logging
from typing import Dict, Any, List, Optional

from .models import AIResult, Job
from .config import AppConfig

logger = logging.getLogger(__name__)


class AIClient:
    """Client for AI integration via OpenRouter (free models)."""
    
    # OpenRouter free model (Meta Llama 3.3 70B - reliable, good for CV writing & JSON)

    def __init__(self, config: AppConfig):
        self.config = config
        self.feedback_insights = ""
        self.openai_client = None
        if config.openrouter_api_key:
            from openai import OpenAI
            self.openai_client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=config.openrouter_api_key,
                default_headers={
                    "HTTP-Referer": "https://github.com/job-agent",
                    "X-Title": "Job Application Agent",
                },
            )

    def _call(self, prompt: str, max_tokens: int = 2000) -> str:
        """Send a prompt to the AI and return the text response.
        Uses OpenRouter via the OpenAI SDK."""
        if self.openai_client:
            response = self.openai_client.chat.completions.create(
                model="meta-llama/llama-3.3-70b-instruct:free",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content.strip()
        raise EnvironmentError("No API key configured. Set OPENROUTER_API_KEY")

    def _strip_fences(self, text: str) -> str:
        """Strip markdown code fences from AI response."""
        text = text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:].strip()
        return text.strip()

    @property
    def is_available(self) -> bool:
        return self.openai_client is not None
    
    def generate_cv(self, profile: Dict[str, Any], jobs: List[Dict[str, Any]], score_range: str, resume_text: str = "") -> str:
        """Generate a tailored CV for a group of jobs in a score range.
        
        Args:
            profile: User profile dict
            jobs: List of job dicts with 'title', 'company', 'description' keys
            score_range: Score range label (e.g. '96-100')
            resume_text: Optional resume text for reference
        
        Returns:
            Generated CV as a formatted string
        """
        if not self.is_available:
            raise EnvironmentError("No API key configured. Set OPENROUTER_API_KEY")
        
        skills_str = ', '.join(profile.get('skills', []))
        roles_str = ', '.join(profile.get('target_roles', []))
        education = profile.get('education', {})
        bachelor = profile.get('bachelor', {})
        
        # Build job summary for context
        job_summaries = []
        for j in jobs:
            desc_preview = (j.get('description', '') or '')[:200]
            job_summaries.append(f"- {j.get('title', 'Unknown')} at {j.get('company', 'Unknown')}: {desc_preview}")
        jobs_context = '\n'.join(job_summaries)
        
        resume_section = f"\n## Candidate Resume (first 1500 chars)\n{resume_text[:1500]}" if resume_text else ""
        
        prompt = f"""You are a professional CV/resume writer. Generate a complete, polished CV (curriculum vitae) for the following candidate, tailored for jobs in the {score_range}% match range.

## Candidate Profile
Name: {profile.get('name', 'Unknown')}
Email: {profile.get('email', '')}
Phone: {profile.get('phone', '')}
Location: {profile.get('address', profile.get('preferred_location', ''))}
LinkedIn: {profile.get('linkedin_url', '')}
GitHub: {profile.get('github_url', '')}
Portfolio: {profile.get('portfolio_url', profile.get('website', ''))}
Current Title: {profile.get('current_title', '')}
Current Company: {profile.get('current_company', '')}
Work Authorization: {profile.get('work_authorization', '')}

Skills: {skills_str}
Experience Summary: {profile.get('experience_summary', 'Not specified')}

Education:
- {education.get('degree', 'N/A')} — {education.get('school', 'N/A')} ({education.get('year', 'N/A')})
{f"- {bachelor.get('degree', 'N/A')} — {bachelor.get('school', 'N/A')} ({bachelor.get('year', 'N/A')})" if bachelor else ''}
{resume_section}

## Jobs in {score_range}% Match Range
{jobs_context}

## Instructions
Generate a professional CV that:
1. Starts with contact info (name, email, phone, location, LinkedIn, GitHub)
2. Has a strong Professional Summary (3-4 sentences) highlighting relevant skills for these specific roles
3. Lists Skills in organized categories relevant to the job types above
4. Has a detailed Work Experience section with bullet points showing achievements and technologies
5. Has an Education section
6. Tailors the language and emphasis to match the common themes in the {score_range}% jobs listed above
7. Uses action verbs and quantified achievements where possible
8. Is clean, professional, and ATS-friendly
9. Is 1-2 pages in length

Return ONLY the CV text, properly formatted with clear sections. Do not include any meta-commentary."""

        cv_text = self._call(prompt, max_tokens=4000)
        cv_text = self._strip_fences(cv_text)
        return cv_text
    
    def analyze_resume_for_keywords(self, resume_text: str, current_roles: Optional[List[str]] = None) -> List[str]:
        """
        Analyze the resume to suggest the best job title keywords to search for.
        
        Args:
            resume_text: Parsed text from the resume/CV
            current_roles: Current target roles from profile (for reference)
        
        Returns:
            List of suggested target role titles to search for
        """
        if not self.is_available:
            raise EnvironmentError("No API key configured. Set OPENROUTER_API_KEY")
        
        current_roles_str = ', '.join(current_roles) if current_roles else 'Not specified'
        
        prompt = f"""You are an expert career coach and job search strategist. A candidate has provided their resume/CV below.

## Current Resume (first 2500 chars)
{resume_text[:2500]}

## Current Search Keywords
{current_roles_str}

## Task
Analyze this resume carefully and suggest 5-8 targeted job titles/roles to search for on job boards. These should:
- Closely match the candidate's actual skills, experience, and education from the resume
- Be specific and commonly used on job boards (e.g. "AI Engineer", "Computer Vision Engineer")
- Cover different but relevant angles of the candidate's profile
- Include both broader and more niche roles where appropriate

Return ONLY a JSON array of strings, like:
["Role 1", "Role 2", "Role 3"]
Do not include any other text or explanation."""

        text = self._call(prompt, max_tokens=500)
        text = self._strip_fences(text)
        
        try:
            roles = json.loads(text.strip())
            if isinstance(roles, list):
                return [str(r).strip() for r in roles if r]
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse AI response as JSON: {text[:100]}...")
        
        return current_roles or ["Software Engineer"]
    
    def score_by_title_only(self, profile: Dict[str, Any], job: Job, resume_text: str = "") -> AIResult:
        """Score a job using only its title/company when no description is available.
        Uses a simpler prompt that scores based on title + skills alignment.
        """
        if not self.is_available:
            raise EnvironmentError("No API key configured. Set OPENROUTER_API_KEY")

        skills_str = ', '.join(profile.get('skills', []))
        roles_str = ', '.join(profile.get('target_roles', []))
        education = profile.get('education', {})
        resume_section = f"\n## Candidate Resume (first 800 chars)\n{resume_text[:800]}" if resume_text else ""

        _fb_section = f"\n## Learning from Past User Feedback\n{self.feedback_insights}\n" if getattr(self, 'feedback_insights', '') else ""

        prompt = f"""You are a professional career coach helping score a quick job match.
{_fb_section}
## Candidate Profile
Name: {profile.get('name', 'Unknown')}
Skills: {skills_str}
Experience: {profile.get('experience_summary', 'Not specified')}
Target roles: {roles_str}
Education: {education.get('degree', 'Not specified')} from {education.get('school', 'Not specified')}
{resume_section}

## Job Listing (Title Only - no description available)
Title: {job.title}
Company: {job.company}

## Task
Score this job match from 0-100 based ONLY on the job title and company. The job description was not available, so:
- If the title clearly relates to AI, ML, Data Science, or Engineering (matching the candidate's skills), score in the 50-75 range
- If the title is somewhat related, score in the 20-49 range
- If the title seems unrelated, score 5-19
- List 1-2 likely matching skills based on the title alone
- Note in concerns that "No job description available"

Respond in JSON only:
{{
  "match_score": <int 0-100>,
  "matching_skills": ["...", "..."],
  "concerns": ["No job description available"],
  "cover_letter": "Based on the job title, I believe my background in {skills_str} aligns well with this role. I would be excited to contribute my expertise to {job.company}."
}}"""

        text = self._call(prompt, max_tokens=1000)
        text = self._strip_fences(text)

        data = json.loads(text)
        return AIResult(
            match_score=data.get("match_score", 0),
            matching_skills=data.get("matching_skills", []),
            concerns=data.get("concerns", ["No job description available"]),
            cover_letter=data.get("cover_letter", ""),
        )

    def extract_full_profile(self, resume_text: str) -> Dict[str, Any]:
        """
        Extract full candidate profile from resume text using AI.
        Returns a dict with name, email, phone, linkedin, address, skills,
        experience, education, and suggested target roles.
        """
        if not self.is_available:
            raise EnvironmentError("No API key configured. Set OPENROUTER_API_KEY")

        prompt = f"""You are an expert resume parser. Extract a structured profile from the following resume/CV text.

## Resume Text
{resume_text[:3000]}

## Task
Extract the following fields from the resume. Return ONLY a valid JSON object with these fields:
{{
  "name": "Full name",
  "email": "email address",
  "phone": "phone number",
  "linkedin_url": "LinkedIn URL if found",
  "github_url": "GitHub URL if found",
  "address": "City, Country",
  "current_title": "Most recent job title",
  "current_company": "Most recent employer",
  "experience_summary": "2-3 sentence summary of work experience and background",
  "skills": ["skill1", "skill2", ...],
  "education": {{"degree": "Degree name", "school": "School name", "year": "Graduation year"}},
  "bachelor": {{"degree": "Bachelor's degree if any", "school": "School name", "year": "Year"}},
  "target_roles": ["5-8 suggested job titles to search for based on this resume"]
}}

Rules:
- If a field is not found, use empty string or empty array as appropriate
- Skills should be comprehensive (10-25 skills)
- target_roles should be specific job titles commonly used on job boards (e.g. "Data Analyst", "Business Intelligence Analyst")
- experience_summary should mention years of experience, key domains, and notable achievements
- Do not include any text outside the JSON object
"""

        text = self._call(prompt, max_tokens=1500)
        text = self._strip_fences(text)

        data = json.loads(text)
        return data

    def tailor_application(self, profile: Dict[str, Any], job: Job, resume_text: str = "") -> AIResult:
        """Use AI to score job match and write tailored cover letter."""
        if not self.is_available:
            raise EnvironmentError("No API key configured. Set OPENROUTER_API_KEY")
        
        skills_str = ', '.join(profile.get('skills', []))
        roles_str = ', '.join(profile.get('target_roles', []))
        education = profile.get('education', {})
        resume_section = f"\n## Candidate Resume (first 1000 chars)\n{resume_text[:1000]}" if resume_text else ""
        
        _fb_section = f"\n## Learning from Past User Feedback\n{self.feedback_insights}\n" if getattr(self, 'feedback_insights', '') else ""

        prompt = f"""You are a professional career coach helping tailor a job application.
{_fb_section}
## Candidate Profile
Name: {profile.get('name', 'Unknown')}
Skills: {skills_str}
Experience: {profile.get('experience_summary', 'Not specified')}
Target roles: {roles_str}
Preferred salary: {profile.get('salary_range', 'Not specified')}
Education: {education.get('degree', 'Not specified')} from {education.get('school', 'Not specified')}
{resume_section}

## Job Listing
Title: {job.title}
Company: {job.company}
Location: {job.location or 'Remote/Unknown'}
Description: {job.description[:2000] if job.description else 'Not available'}

## Tasks
1. Score this job match from 0-100 based on skills and role alignment.
2. List 3 key matching skills from the candidate's profile.
3. List any major mismatches or concerns.
4. Write a concise, tailored cover letter (3 short paragraphs, no fluff, highlight specific achievements).

Respond in JSON only:
{{
  "match_score": <int 0-100>,
  "matching_skills": ["...", "...", "..."],
  "concerns": ["..."],
  "cover_letter": "..."
}}"""

        text = self._call(prompt, max_tokens=1500)
        text = self._strip_fences(text)

        data = json.loads(text)
        return AIResult(
            match_score=data.get("match_score", 0),
            matching_skills=data.get("matching_skills", []),
            concerns=data.get("concerns", []),
            cover_letter=data.get("cover_letter", ""),
        )