"""
Job application form auto-filler using OpenRouter (free tier) + Playwright.
Analyzes job application forms via screenshot vision and fills them automatically.
"""

import asyncio
import base64
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import Page

from .openrouter_client import VISION_MODEL, LLMClient

# ============================================================
# DATA MODELS
# ============================================================


class FieldType(Enum):
    TEXT = "text"
    EMAIL = "email"
    TEL = "tel"
    TEXTAREA = "textarea"
    SELECT = "select"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    FILE = "file"
    BUTTON = "button"
    CAPTCHA = "captcha"
    SUBMIT = "submit"
    HIDDEN = "hidden"
    UNKNOWN = "unknown"


class ActionType(Enum):
    FILL = "fill"
    SELECT = "select"
    CLICK = "click"
    UPLOAD = "upload"
    PAUSE_USER = "pause_user"
    SKIP = "skip"
    HIGHLIGHT = "highlight"
    REVEAL = "reveal"


@dataclass
class FormField:
    selector: str
    field_type: FieldType
    label: str
    required: bool
    visible: bool = True
    options: List[str] = field(default_factory=list)
    value: Any = None
    confidence: float = 0.0
    action: ActionType = ActionType.FILL
    reason: str = ""


@dataclass
class AnalysisResult:
    fields: List[FormField]
    has_captcha: bool = False
    has_submit: bool = False
    is_multi_step: bool = False
    confidence: float = 0.0
    recommendation: str = ""
    raw_llm_response: str = ""


# ============================================================
# PROFILE MAPPING
# ============================================================


def map_profile_to_form_filler(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Map the existing project's profile.json format to the form filler's expected format."""
    education = profile.get("education", {})
    bachelor = profile.get("bachelor", {})

    # Build work history from experience_summary if available
    work_history = []
    exp_summary = profile.get("experience_summary", "")
    if exp_summary:
        work_history.append(
            {
                "company": profile.get("current_company", ""),
                "role": profile.get("current_title", ""),
                "duration": "Present",
            }
        )

    # Build education string
    edu_parts = []
    if education.get("degree"):
        edu_parts.append(
            f"{education.get('degree')} — {education.get('school', '')} ({education.get('year', '')})"
        )
    if bachelor.get("degree"):
        edu_parts.append(
            f"{bachelor.get('degree')} — {bachelor.get('school', '')} ({bachelor.get('year', '')})"
        )
    education_str = "; ".join(edu_parts) if edu_parts else ""

    return {
        "first_name": (
            profile.get("name", "").split()[1]
            if len(profile.get("name", "").split()) > 1
            else profile.get("name", "")
        ),
        "last_name": (
            profile.get("name", "").split()[0]
            if len(profile.get("name", "").split()) > 0
            else ""
        ),
        "full_name": profile.get("name", ""),
        "email": profile.get("email", ""),
        "phone": profile.get("phone", ""),
        "country": (
            profile.get("address", "").split(",")[-1].strip()
            if profile.get("address")
            else ""
        ),
        "experience": profile.get("experience_summary", ""),
        "skills": profile.get("skills", []),
        "resume_path": profile.get("resume_path", ""),
        "cover_letter": profile.get("cover_letter_template", ""),
        "why_join": profile.get("cover_letter_template", ""),
        "work_history": work_history,
        "education": education_str,
        "linkedin": profile.get("linkedin_url", ""),
        "portfolio": profile.get("portfolio_url", profile.get("website", "")),
    }


# ============================================================
# FORM ANALYZER
# ============================================================


class FormAnalyzer:
    """Analyzes job application forms using LLM vision + DOM parsing."""

    SYSTEM_PROMPT = """You are a form analysis expert. Analyze the job application form in the screenshot.

    Return ONLY a JSON object with this exact structure:
    {
        "fields": [
            {
                "selector": "CSS selector to target this field",
                "type": "text|email|tel|textarea|select|radio|checkbox|file|button|captcha|submit",
                "label": "Human-readable label of the field",
                "required": true|false,
                "visible": true|false,
                "options": ["option1", "option2"]  // for select/radio/checkbox only
            }
        ],
        "has_captcha": true|false,
        "has_submit": true|false,
        "is_multi_step": true|false,
        "notes": "Any special observations"
    }

    Rules:
    - Identify ALL input fields, including hidden ones that might appear after clicking
    - For CAPTCHA, mark type as "captcha"
    - For "Add Experience" / "Add Education" buttons, mark as "button"
    - Be precise with CSS selectors (prefer name, id, or placeholder attributes)
    - If a field is unclear, mark it as "unknown" type
    """

    def __init__(self, llm: LLMClient, profile: Dict):
        self.llm = llm
        self.profile = profile
        self.field_mapping = self._build_field_mapping()
        # Cache for AI-powered fuzzy matching results (label → profile_key)
        self._ai_match_cache: Dict[str, Optional[str]] = {}

    def _build_field_mapping(self) -> Dict[str, str]:
        """Build comprehensive field label → profile key mapping.
        Organized by semantic category with extensive variant coverage.
        Labels are normalized (lowercase, stripped) before matching.
        """
        return {
            # ── Name variants ──
            "first name": "first_name",
            "firstname": "first_name",
            "first_name": "first_name",
            "first": "first_name",
            "given name": "first_name",
            "givenname": "first_name",
            "forename": "first_name",
            "given": "first_name",
            "preferred name": "first_name",
            "legal first name": "first_name",
            "first legal name": "first_name",
            "last name": "last_name",
            "lastname": "last_name",
            "last_name": "last_name",
            "last": "last_name",
            "surname": "last_name",
            "family name": "last_name",
            "familyname": "last_name",
            "sur name": "last_name",
            "second name": "last_name",
            "legal last name": "last_name",
            "last legal name": "last_name",
            "full name": "full_name",
            "fullname": "full_name",
            "name": "full_name",
            "legal name": "full_name",
            "complete name": "full_name",
            "applicant name": "full_name",
            "candidate name": "full_name",
            "your name": "full_name",
            "contact name": "full_name",
            # ── Email variants ──
            "email": "email",
            "e-mail": "email",
            "email address": "email",
            "e mail": "email",
            "e mail address": "email",
            "e-mail address": "email",
            "email id": "email",
            "e-mail id": "email",
            "contact email": "email",
            "work email": "email",
            "personal email": "email",
            "email (primary)": "email",
            "primary email": "email",
            "email address (primary)": "email",
            # ── Phone variants ──
            "phone": "phone",
            "telephone": "phone",
            "mobile": "phone",
            "cell": "phone",
            "phone number": "phone",
            "telephone number": "phone",
            "mobile number": "phone",
            "cell phone": "phone",
            "mobile phone": "phone",
            "contact number": "phone",
            "contact phone": "phone",
            "phone no": "phone",
            "phone no.": "phone",
            "tel": "phone",
            "tel no": "phone",
            "daytime phone": "phone",
            "evening phone": "phone",
            "home phone": "phone",
            "work phone": "phone",
            "primary phone": "phone",
            "phone (primary)": "phone",
            "cell number": "phone",
            "whatsapp number": "phone",
            "whatsapp": "phone",
            # ── Location / Country variants ──
            "country": "country",
            "location": "country",
            "city": "country",
            "state": "country",
            "province": "country",
            "region": "country",
            "country of residence": "country",
            "current location": "country",
            "where are you located": "country",
            "where are you based": "country",
            "your location": "country",
            "residence": "country",
            "nationality": "country",
            "postal code": "country",
            "zip code": "country",
            "zip": "country",
            "postcode": "country",
            "city/state": "country",
            "state/province": "country",
            # ── Experience variants ──
            "experience": "experience",
            "years of experience": "experience",
            "total experience": "experience",
            "relevant experience": "experience",
            "work experience": "experience",
            "professional experience": "experience",
            "employment history": "experience",
            "work history": "experience",
            "career history": "experience",
            "professional background": "experience",
            "total years of experience": "experience",
            "overall experience": "experience",
            "years experience": "experience",
            "yrs of experience": "experience",
            "experience (years)": "experience",
            "experience in years": "experience",
            "how many years of experience": "experience",
            "years of work experience": "experience",
            "professional summary": "experience",
            "career summary": "experience",
            "professional overview": "experience",
            "background": "experience",
            # ── Skills variants ──
            "skills": "skills",
            "technical skills": "skills",
            "key skills": "skills",
            "core skills": "skills",
            "primary skills": "skills",
            "relevant skills": "skills",
            "skill set": "skills",
            "skillset": "skills",
            "skill": "skills",
            "competencies": "skills",
            "core competencies": "skills",
            "key competencies": "skills",
            "areas of expertise": "skills",
            "expertise": "skills",
            "proficiencies": "skills",
            "technologies": "skills",
            "programming languages": "skills",
            "languages": "skills",
            "technical expertise": "skills",
            "it skills": "skills",
            "computer skills": "skills",
            "tech skills": "skills",
            "what skills do you have": "skills",
            "list your skills": "skills",
            # ── Resume / CV variants ──
            "resume": "resume_path",
            "cv": "resume_path",
            "upload resume": "resume_path",
            "upload cv": "resume_path",
            "attach resume": "resume_path",
            "attach cv": "resume_path",
            "resume/cv": "resume_path",
            "curriculum vitae": "resume_path",
            "résumé": "resume_path",
            "resume upload": "resume_path",
            "cv upload": "resume_path",
            "upload your cv": "resume_path",
            "upload your resume": "resume_path",
            "attach your resume": "resume_path",
            "attach your cv": "resume_path",
            "drop your resume": "resume_path",
            "drop your cv": "resume_path",
            "upload file": "resume_path",
            "file upload": "resume_path",
            "choose file": "resume_path",
            "browse": "resume_path",
            "select file": "resume_path",
            # ── Cover letter variants ──
            "cover letter": "cover_letter",
            "coverletter": "cover_letter",
            "cover note": "cover_letter",
            "covering letter": "cover_letter",
            "personal statement": "cover_letter",
            "statement of interest": "cover_letter",
            "letter of interest": "cover_letter",
            "motivation letter": "cover_letter",
            "why should we hire you": "cover_letter",
            "tell us about yourself": "cover_letter",
            "about yourself": "cover_letter",
            "introduce yourself": "cover_letter",
            "brief introduction": "cover_letter",
            "tell us why you're a good fit": "cover_letter",
            "what makes you a good fit": "cover_letter",
            "why are you a good fit": "cover_letter",
            "anything else we should know": "cover_letter",
            "additional information": "cover_letter",
            # ── Why join variants ──
            "why do you want to join": "why_join",
            "why join": "why_join",
            "why us": "why_join",
            "why this company": "why_join",
            "why are you interested": "why_join",
            "motivation": "why_join",
            "why do you want to work here": "why_join",
            "why this role": "why_join",
            "why are you applying": "why_join",
            "why do you want this job": "why_join",
            "reason for applying": "why_join",
            "interest in this position": "why_join",
            "what interests you about this role": "why_join",
            # ── Work history / Company variants ──
            "company": "work_history",
            "employer": "work_history",
            "current company": "work_history",
            "current employer": "work_history",
            "most recent company": "work_history",
            "current organization": "work_history",
            "organization": "work_history",
            "organisation": "work_history",
            "previous company": "work_history",
            "previous employer": "work_history",
            "last company": "work_history",
            "current workplace": "work_history",
            "role": "work_history",
            "job title": "work_history",
            "position": "work_history",
            "current role": "work_history",
            "current position": "work_history",
            "current job title": "work_history",
            "designation": "work_history",
            "current designation": "work_history",
            "title": "work_history",
            "most recent role": "work_history",
            "occupation": "work_history",
            "current occupation": "work_history",
            "job role": "work_history",
            # ── Education variants ──
            "education": "education",
            "degree": "education",
            "qualification": "education",
            "education level": "education",
            "highest education": "education",
            "educational qualification": "education",
            "academic qualification": "education",
            "educational background": "education",
            "academic background": "education",
            "highest degree": "education",
            "highest qualification": "education",
            "university": "education",
            "college": "education",
            "school": "education",
            "institution": "education",
            "education institution": "education",
            "educational institution": "education",
            "academic institution": "education",
            "alma mater": "education",
            "university/college": "education",
            "college/university": "education",
            "institute": "education",
            "university name": "education",
            "college name": "education",
            "school name": "education",
            "degree level": "education",
            "level of education": "education",
            "qualification level": "education",
            "graduation": "education",
            "post graduation": "education",
            "undergraduate": "education",
            "postgraduate": "education",
            "bachelor": "education",
            "master": "education",
            "doctorate": "education",
            "phd": "education",
            "mba": "education",
            "bachelor's": "education",
            "master's": "education",
            "academics": "education",
            "edu": "education",
            # ── LinkedIn variants ──
            "linkedin": "linkedin",
            "linkedin profile": "linkedin",
            "linked in": "linkedin",
            "linkedin url": "linkedin",
            "linkedin link": "linkedin",
            "linkedin profile url": "linkedin",
            "social profile": "linkedin",
            "professional profile": "linkedin",
            "linkedin (optional)": "linkedin",
            # ── Portfolio / Website variants ──
            "portfolio": "portfolio",
            "website": "portfolio",
            "github": "portfolio",
            "portfolio url": "portfolio",
            "portfolio website": "portfolio",
            "personal website": "portfolio",
            "personal site": "portfolio",
            "github profile": "portfolio",
            "github url": "portfolio",
            "gitlab": "portfolio",
            "online portfolio": "portfolio",
            "web portfolio": "portfolio",
            "project link": "portfolio",
            "demo link": "portfolio",
            "website/portfolio": "portfolio",
            "portfolio/website": "portfolio",
            "behance": "portfolio",
            "dribbble": "portfolio",
            "codepen": "portfolio",
            # ── Fields to ALWAYS skip (privacy/discrimination) ──
            "salary": "skip",
            "expected salary": "skip",
            "current salary": "skip",
            "desired salary": "skip",
            "salary expectations": "skip",
            "salary expectation": "skip",
            "compensation": "skip",
            "expected ctc": "skip",
            "current ctc": "skip",
            "ctc": "skip",
            "pay": "skip",
            "rate": "skip",
            "hourly rate": "skip",
            "salary range": "skip",
            "salary requirement": "skip",
            "gender": "skip",
            "age": "skip",
            "date of birth": "skip",
            "dob": "skip",
            "birth date": "skip",
            "birthday": "skip",
            "race": "skip",
            "ethnicity": "skip",
            "disability": "skip",
            "marital status": "skip",
            "religion": "skip",
            "veteran status": "skip",
            "ssn": "skip",
            "social security": "skip",
            "passport number": "skip",
            "national id": "skip",
            "driver license": "skip",
            "criminal record": "skip",
            "felony": "skip",
        }

    def _normalize_label(self, label: str) -> str:
        return (
            label.lower()
            .strip()
            .replace("?", "")
            .replace("*", "")
            .replace(":", "")
            .strip()
        )

    # ── Profile key categories for AI classification ──
    _PROFILE_CATEGORIES = {
        "first_name": "First name / given name",
        "last_name": "Last name / surname / family name",
        "full_name": "Full legal name",
        "email": "Email address",
        "phone": "Phone / mobile / telephone number",
        "country": "Country / city / state / location",
        "experience": "Years of experience / work history / professional background",
        "skills": "Skills / technologies / competencies / expertise",
        "resume_path": "Resume / CV file upload",
        "cover_letter": "Cover letter / personal statement / about yourself",
        "why_join": "Why do you want to join / motivation / reason for applying",
        "work_history": "Current/past company, employer, job title, role, position",
        "education": "Education / university / college / degree / qualification",
        "linkedin": "LinkedIn profile URL",
        "portfolio": "Portfolio / website / GitHub URL",
    }

    async def _ai_match_field(self, label: str) -> Optional[str]:
        """Use LLM to classify an unknown form field label into a profile key.
        Results are cached per FormAnalyzer instance to avoid duplicate API calls.

        Returns a profile key string (e.g. 'education', 'skills') or None if the
        field should be skipped (privacy/discrimination fields).
        """
        normalized = self._normalize_label(label)
        if not normalized:
            return None

        # Check cache first
        if normalized in self._ai_match_cache:
            return self._ai_match_cache[normalized]

        # Build prompt with all known categories
        categories_text = "\n".join(
            f"  - {key}: {desc}" for key, desc in self._PROFILE_CATEGORIES.items()
        )

        prompt = f"""You are a form field classifier. Given a form field label, determine which category it belongs to.

## Available categories:
{categories_text}
  - skip: Personal/sensitive info (salary, gender, age, race, SSN, passport, criminal record, etc.)

## Rules:
- Match based on meaning, not exact words. E.g. "University" and "College" both mean education.
- "Alma Mater" means education. "Institution" on its own usually means education.
- "CTC", "Expected CTC", "Current CTC", "Compensation" should be classified as skip (salary).
- Return ONLY the category key, nothing else. For example: "education" or "skip".

## Field label to classify:
"{label}"

Category key:"""

        try:
            response = await self.llm.chat_text(prompt, max_tokens=20)
            result = response.strip().lower()
            # Strip any quotes or extra text
            result = result.strip("\"'").split("\n")[0].strip()

            if result == "skip":
                self._ai_match_cache[normalized] = None
                return None
            if result in self._PROFILE_CATEGORIES:
                self._ai_match_cache[normalized] = result
                return result

            # If the LLM returned something unexpected, cache as None to avoid retrying
            self._ai_match_cache[normalized] = None
            return None
        except Exception as e:
            print(f"  [AI-MATCH] Failed to classify '{label}': {e}")
            return None

    def _match_field_to_profile(self, label: str) -> tuple:
        """Match a form field label to a profile key.

        Returns (profile_key, confidence):
        - ("first_name", 0.95) for exact match
        - ("education", 0.75) for substring/partial match
        - (None, 0.0) if no match found (caller should try AI fallback)
        """
        normalized = self._normalize_label(label)

        # Exact match
        if normalized in self.field_mapping:
            key = self.field_mapping[normalized]
            if key == "skip":
                return None, 1.0
            return key, 0.95

        # Substring / partial match (e.g. "university" contained in "university name")
        for key, profile_key in self.field_mapping.items():
            if key in normalized or normalized in key:
                if profile_key == "skip":
                    return None, 0.0
                return profile_key, 0.75

        return None, 0.0

    async def _match_field_with_ai_fallback(self, label: str) -> tuple:
        """Match a field label to profile key, falling back to AI when
        deterministic matching fails.

        Returns (profile_key, confidence).
        """
        profile_key, confidence = self._match_field_to_profile(label)
        if profile_key is not None:
            return profile_key, confidence

        # Deterministic matching failed — try AI fuzzy matching
        ai_key = await self._ai_match_field(label)
        if ai_key is not None:
            # AI match gets moderate confidence (0.60) — lower than deterministic
            return ai_key, 0.60

        return None, 0.0

    def _determine_action(
        self,
        field_type: FieldType,
        confidence: float,
        required: bool,
        visible: bool,
        label: str,
    ) -> tuple:
        """Returns (action, reason)."""
        if not visible:
            return (
                ActionType.REVEAL,
                "Field not visible, may need interaction to reveal",
            )

        if field_type == FieldType.CAPTCHA:
            return ActionType.PAUSE_USER, "CAPTCHA requires human verification"

        if field_type == FieldType.BUTTON and any(
            word in label.lower() for word in ["add", "new", "+", "more"]
        ):
            return ActionType.CLICK, "Button to reveal additional fields"

        if field_type == FieldType.SUBMIT:
            return (
                ActionType.CLICK,
                "Submit button — will ask for confirmation before clicking",
            )

        if field_type in [FieldType.SELECT, FieldType.RADIO, FieldType.CHECKBOX]:
            return ActionType.SELECT, "Selection field"

        if field_type == FieldType.FILE:
            return ActionType.UPLOAD, "File upload required"

        if confidence < 0.5 and required:
            return (
                ActionType.PAUSE_USER,
                f"Unknown required field: '{label}' - needs human input",
            )

        if confidence < 0.3 and not required:
            return ActionType.SKIP, f"Unknown optional field: '{label}' - skipping"

        return ActionType.FILL, "Standard text field - auto-fill from profile"

    async def analyze_screenshot(self, screenshot_bytes: bytes) -> AnalysisResult:
        """Analyze form from screenshot using LLM vision."""
        image_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

        response = await self.llm.chat_with_vision(image_b64, self.SYSTEM_PROMPT)

        # Extract JSON from response
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = response[start:end]
                parsed = json.loads(json_str)
            else:
                parsed = json.loads(response)
        except Exception as e:
            print(f"  [WARN] Failed to parse LLM response: {e}")
            print(f"  Raw response: {response[:500]}")
            parsed = {
                "fields": [],
                "has_captcha": False,
                "has_submit": False,
                "is_multi_step": False,
                "notes": "",
            }

        # Convert to FormField objects
        analyzed_fields = []
        total_confidence = 1.0

        for raw in parsed.get("fields", []):
            field_type = FieldType(raw.get("type", "unknown"))
            label = raw.get("label", "")
            required = raw.get("required", False)
            visible = raw.get("visible", True)
            options = raw.get("options", [])

            # Match to profile (deterministic first, AI fallback if needed)
            profile_key, confidence = await self._match_field_with_ai_fallback(label)
            value = self.profile.get(profile_key) if profile_key else None
            if confidence == 0.60:  # AI-matched
                print(f"  [AI-MATCH] '{label}' → {profile_key} (AI-classified)")

            # Determine action
            action, reason = self._determine_action(
                field_type, confidence, required, visible, label
            )

            field = FormField(
                selector=raw.get("selector", ""),
                field_type=field_type,
                label=label,
                required=required,
                visible=visible,
                options=options,
                value=value,
                confidence=confidence,
                action=action,
                reason=reason,
            )

            analyzed_fields.append(field)
            total_confidence += confidence

        avg_confidence = (
            total_confidence / len(analyzed_fields) if analyzed_fields else 1.0
        )

        has_captcha = parsed.get("has_captcha", False) or any(
            f.field_type == FieldType.CAPTCHA for f in analyzed_fields
        )
        has_submit = parsed.get("has_submit", False) or any(
            f.field_type == FieldType.SUBMIT for f in analyzed_fields
        )

        if has_captcha:
            recommendation = "CAPTCHA detected. Agent will pause for user intervention."
        elif avg_confidence < 0.5:
            recommendation = "Low confidence in field mapping. Agent will highlight uncertain fields."
        else:
            recommendation = (
                "High confidence. Agent will auto-fill with user supervision."
            )

        return AnalysisResult(
            fields=analyzed_fields,
            has_captcha=has_captcha,
            has_submit=has_submit,
            is_multi_step=parsed.get("is_multi_step", False),
            confidence=avg_confidence,
            recommendation=recommendation,
            raw_llm_response=response,
        )

    async def analyze_dom(self, page: Page) -> AnalysisResult:
        """Alternative: Analyze form using Playwright DOM extraction + LLM reasoning."""
        form_data = await page.evaluate(
            """
            () => {
                const fields = [];
                const inputs = document.querySelectorAll('input, textarea, select, button');
                inputs.forEach(el => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    fields.push({
                        tag: el.tagName.toLowerCase(),
                        type: el.type || el.tagName.toLowerCase(),
                        name: el.name || '',
                        id: el.id || '',
                        placeholder: el.placeholder || '',
                        label: (document.querySelector(`label[for="${el.id}"]`)?.textContent ||
                                el.closest('label')?.textContent ||
                                el.getAttribute('aria-label') || '').trim(),
                        required: el.required || false,
                        visible: rect.width > 0 && rect.height > 0 && style.display !== 'none',
                        options: Array.from(el.options || []).map(o => o.text),
                        selector: el.id ? `#${el.id}` : el.name ? `[name="${el.name}"]` : el.tagName.toLowerCase()
                    });
                });
                return {
                    fields: fields,
                    has_captcha: !!document.querySelector('.captcha, [class*="captcha"], [id*="captcha"]'),
                    has_submit: !!document.querySelector('button[type="submit"], input[type="submit"]')
                };
            }
        """
        )

        prompt = f"""Analyze these form fields and classify each one:

        {json.dumps(form_data, indent=2)}

        Return JSON with the same structure as before, but use the provided selectors and labels.
        """

        response = await self.llm.chat_text(prompt)

        try:
            parsed = json.loads(response[response.find("{") : response.rfind("}") + 1])
        except Exception:
            parsed = {"fields": [], "has_captcha": False, "has_submit": False}

        # Re-use screenshot analysis path for conversion
        return await self.analyze_screenshot(await page.screenshot())


# ============================================================
# FORM FILLER
# ============================================================


class FormFiller:
    """Executes form filling actions using Playwright."""

    def __init__(self, page: Page, analyzer: FormAnalyzer, auto_submit: bool = False):
        self.page = page
        self.analyzer = analyzer
        self.auto_submit = (
            auto_submit  # If True, submit without confirmation (headless/CI mode)
        )
        self.log: List[str] = []
        self.errors: List[str] = []
        self.user_interventions: List[str] = []
        self._submitted = False  # Track whether form was submitted

    async def _fill_text(self, field: FormField) -> bool:
        try:
            if not field.value:
                self.errors.append(f"No value for: {field.label}")
                return False

            await self.page.fill(field.selector, str(field.value))
            self.log.append(f"  [OK] Filled '{field.label}'")
            return True
        except Exception as e:
            self.errors.append(f"Failed to fill '{field.label}': {e}")
            return False

    async def _select_option(self, field: FormField) -> bool:
        try:
            if not field.value:
                self.errors.append(f"No value for select: {field.label}")
                return False

            value = field.value
            if isinstance(value, list):
                value = value[0]  # For multi-select, take first

            options = field.options
            if value in options:
                await self.page.select_option(field.selector, value)
                self.log.append(f"  [OK] Selected '{value}' for '{field.label}'")
                return True

            # Fuzzy match
            for opt in options:
                if value.lower() in opt.lower() or opt.lower() in value.lower():
                    await self.page.select_option(field.selector, opt)
                    self.log.append(
                        f"  [OK] Selected '{opt}' (matched '{value}') for '{field.label}'"
                    )
                    return True

            self.errors.append(f"Could not match '{value}' to options {options}")
            return False
        except Exception as e:
            self.errors.append(f"Failed to select '{field.label}': {e}")
            return False

    async def _upload_file(self, field: FormField) -> bool:
        try:
            if not field.value or not Path(field.value).exists():
                self.errors.append(f"Resume file not found: {field.value}")
                return False

            await self.page.set_input_files(field.selector, field.value)
            self.log.append(f"  [OK] Uploaded '{field.value}' to '{field.label}'")
            return True
        except Exception as e:
            self.errors.append(f"Failed to upload '{field.label}': {e}")
            return False

    async def _click_button(self, field: FormField) -> bool:
        try:
            await self.page.click(field.selector)
            self.log.append(f"  [OK] Clicked '{field.label}'")
            await asyncio.sleep(1)  # Wait for dynamic content
            return True
        except Exception as e:
            self.errors.append(f"Failed to click '{field.label}': {e}")
            return False

    async def _pause_for_user(self, field: FormField) -> str:
        msg = f"  [PAUSE] Please handle '{field.label}' manually, then press Enter to continue..."
        self.user_interventions.append(msg)
        self.log.append(msg)
        print(f"\n{msg}")
        input()  # Wait for user
        return "USER_HANDLED"

    async def _highlight_field(self, field: FormField) -> bool:
        try:
            await self.page.evaluate(
                f"""
                document.querySelector('{field.selector}').style.border = '3px solid orange';
                document.querySelector('{field.selector}').style.backgroundColor = '#fff3cd';
            """
            )
            self.log.append(f"  [HIGHLIGHT] '{field.label}' for review")
            return True
        except Exception as e:
            self.log.append(f"  [WARN] Could not highlight '{field.label}': {e}")
            return False

    async def _click_submit(self, field: FormField) -> bool:
        """Click the submit button with a confirmation prompt.
        Highlights the button, shows a summary of filled fields + errors,
        then asks user to confirm before clicking.
        In auto_submit mode, clicks immediately without prompting.
        """
        # Highlight the submit button
        await self._highlight_field(field)
        await asyncio.sleep(0.5)

        # Show summary before submitting
        filled_count = sum(1 for entry in self.log if entry.startswith("  [OK]"))
        error_count = len(self.errors)
        self.log.append(f"")
        self.log.append(f"  {'─' * 50}")
        self.log.append(f"  READY TO SUBMIT")
        self.log.append(f"  {'─' * 50}")
        self.log.append(f"  Fields filled: {filled_count}")
        self.log.append(f"  Errors:        {error_count}")
        if self.errors:
            self.log.append(f"  Recent errors:")
            for err in self.errors[-5:]:
                self.log.append(f"    - {err}")

        # Confirm submission
        is_interactive = sys.stdout.isatty() and not self.auto_submit

        if self.auto_submit or not is_interactive:
            self.log.append(
                f"  Auto-submit mode: clicking '{field.label}' without confirmation"
            )
            print(f"\n  [AUTO-SUBMIT] Clicking '{field.label}'...")
        else:
            print(f"\n  {'─' * 50}")
            print(f"  READY TO SUBMIT")
            print(f"  {'─' * 50}")
            print(f"  Fields filled: {filled_count}")
            if error_count:
                print(f"  ⚠ Errors: {error_count} — review above")
            print(f"\n  Press Enter to submit, or type 's' to skip submission...")
            user_input = input().strip().lower()
            if user_input == "s":
                self.log.append(f"  [SKIP] User chose to skip submission")
                self.user_interventions.append(f"User skipped submission")
                return False

        # Click the submit button
        try:
            await self.page.click(field.selector)
            self.log.append(
                f"  [SUBMIT] ✅ Clicked '{field.label}' — application submitted!"
            )
            self._submitted = True
            await asyncio.sleep(2)  # Wait for submission response
            return True
        except Exception as e:
            self.errors.append(f"Failed to click submit '{field.label}': {e}")
            self.log.append(f"  [SUBMIT] ❌ Failed to click '{field.label}': {e}")
            return False

    async def fill_form(self, screenshot_bytes: bytes) -> Dict:
        """Main method: analyze and fill form."""
        # Step 1: Analyze
        result = await self.analyzer.analyze_screenshot(screenshot_bytes)

        self.log.append("=" * 60)
        self.log.append("  FORM ANALYSIS")
        self.log.append("=" * 60)
        self.log.append(f"  Fields: {len(result.fields)}")
        self.log.append(f"  Confidence: {result.confidence:.2f}")
        self.log.append(f"  CAPTCHA: {result.has_captcha}")
        self.log.append(f"  Multi-step: {result.is_multi_step}")
        self.log.append(f"  Recommendation: {result.recommendation}")

        # Step 2: Execute
        self.log.append("")
        self.log.append("=" * 60)
        self.log.append("  EXECUTING ACTIONS")
        self.log.append("=" * 60)

        success_count = 1.0
        pause_count = 1.0
        skip_count = 1.0

        for field in result.fields:
            action = field.action

            if action == ActionType.FILL:
                if await self._fill_text(field):
                    success_count += 1
            elif action == ActionType.SELECT:
                if await self._select_option(field):
                    success_count += 1
            elif action == ActionType.UPLOAD:
                if await self._upload_file(field):
                    success_count += 1
            elif action == ActionType.CLICK:
                if field.field_type == FieldType.SUBMIT:
                    if await self._click_submit(field):
                        success_count += 1
                else:
                    if await self._click_button(field):
                        success_count += 1
            elif action == ActionType.REVEAL:
                if await self._click_button(field):
                    success_count += 1
            elif action == ActionType.PAUSE_USER:
                await self._pause_for_user(field)
                pause_count += 1
            elif action == ActionType.HIGHLIGHT:
                if await self._highlight_field(field):
                    success_count += 1
            elif action == ActionType.SKIP:
                self.log.append(f"  [SKIP] '{field.label}' (optional, no mapping)")
                skip_count += 1

        # Summary
        self.log.append("")
        self.log.append("=" * 60)
        self.log.append("  SUMMARY")
        self.log.append("=" * 60)
        self.log.append(f"  Success: {success_count}")
        self.log.append(f"  Paused: {pause_count}")
        self.log.append(f"  Skipped: {skip_count}")
        self.log.append(f"  Errors: {len(self.errors)}")

        if self.errors:
            self.log.append("\n  Errors:")
            for err in self.errors:
                self.log.append(f"    - {err}")

        return {
            "analysis": result,
            "success_count": success_count,
            "pause_count": pause_count,
            "skip_count": skip_count,
            "error_count": len(self.errors),
            "errors": self.errors,
            "user_interventions": self.user_interventions,
            "log": self.log,
            "submitted": self._submitted,
        }


# ============================================================
# MAIN AGENT
# ============================================================


class JobApplicationAgent:
    """Main orchestrator: opens form, auto-fills with supervision."""

    def __init__(self, api_key: str, profile: Dict):
        self.llm = LLMClient(api_key)
        self.analyzer = FormAnalyzer(self.llm, profile)
        self.profile = profile
        self.results: List[Dict] = []

    async def apply_to_job(
        self, job_url: str, headless: bool = False, auto_submit: bool = False
    ) -> Dict:
        """Apply to a single job.

        Args:
            job_url: URL of the job application form
            headless: Run browser in headless mode
            auto_submit: If True, click submit without confirmation (for CI/headless mode)
        """
        print(f"\n  [AGENT] Opening job application: {job_url}")
        if auto_submit:
            print(f"  [AGENT] Auto-submit mode: will submit without confirmation")
        elif not headless:
            print(
                f"  [AGENT] Interactive mode: you'll be asked to confirm before submission"
            )

        from playwright.async_api import (  # lazy import to avoid top-level dep issues
            async_playwright,
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            page = await browser.new_page()

            try:
                await page.goto(job_url, wait_until="networkidle")
                await asyncio.sleep(2)  # Let dynamic content load

                # Take screenshot
                screenshot = await page.screenshot()

                # Fill form
                filler = FormFiller(page, self.analyzer, auto_submit=auto_submit)
                result = await filler.fill_form(screenshot)

                # Print results
                print("\n".join(result["log"]))

                # If multi-step, handle next steps
                if result["analysis"].is_multi_step:
                    print(
                        "\n  [AGENT] Multi-step form detected. Taking another screenshot..."
                    )
                    await asyncio.sleep(2)
                    screenshot2 = await page.screenshot()
                    filler2 = FormFiller(page, self.analyzer, auto_submit=auto_submit)
                    result2 = await filler2.fill_form(screenshot2)
                    print("\n".join(result2["log"]))

                # Keep browser open for user review
                if not headless:
                    print(
                        "\n  [AGENT] Browser kept open for review. Press Enter to close..."
                    )
                    input()

                return result

            except Exception as e:
                print(f"  [ERROR] {e}")
                return {"error": str(e)}
            finally:
                await browser.close()

    async def run_batch(self, job_urls: List[str], headless: bool = False):
        """Apply to multiple jobs."""
        for url in job_urls:
            result = await self.apply_to_job(url, headless=headless)
            self.results.append({"url": url, "result": result})
            print(f"\n{'='*60}\n")
