"""
Job application form auto-filler using OpenRouter (free tier) + Playwright.
Analyzes job application forms via screenshot vision and fills them automatically.
"""

import asyncio
import base64
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import Page

from .openrouter_client import LLMClient, VISION_MODEL


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
        work_history.append({"company": profile.get("current_company", ""), "role": profile.get("current_title", ""), "duration": "Present"})

    # Build education string
    edu_parts = []
    if education.get("degree"):
        edu_parts.append(f"{education.get('degree')} — {education.get('school', '')} ({education.get('year', '')})")
    if bachelor.get("degree"):
        edu_parts.append(f"{bachelor.get('degree')} — {bachelor.get('school', '')} ({bachelor.get('year', '')})")
    education_str = "; ".join(edu_parts) if edu_parts else ""

    return {
        "first_name": profile.get("name", "").split()[1] if len(profile.get("name", "").split()) > 1 else profile.get("name", ""),
        "last_name": profile.get("name", "").split()[0] if len(profile.get("name", "").split()) > 0 else "",
        "full_name": profile.get("name", ""),
        "email": profile.get("email", ""),
        "phone": profile.get("phone", ""),
        "country": profile.get("address", "").split(",")[-1].strip() if profile.get("address") else "",
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

    def _build_field_mapping(self) -> Dict[str, str]:
        return {
            "first name": "first_name", "firstname": "first_name", "first_name": "first_name",
            "first": "first_name", "given name": "first_name",
            "last name": "last_name", "lastname": "last_name", "last_name": "last_name",
            "last": "last_name", "surname": "last_name", "family name": "last_name",
            "full name": "full_name", "fullname": "full_name", "name": "full_name",
            "email": "email", "e-mail": "email", "email address": "email",
            "phone": "phone", "telephone": "phone", "mobile": "phone", "cell": "phone",
            "country": "country", "location": "country", "city": "country",
            "experience": "experience", "years of experience": "experience",
            "work experience": "experience", "professional experience": "experience",
            "skills": "skills", "technical skills": "skills", "key skills": "skills",
            "resume": "resume_path", "cv": "resume_path", "upload resume": "resume_path",
            "cover letter": "cover_letter", "coverletter": "cover_letter",
            "why do you want to join": "why_join", "why join": "why_join",
            "why us": "why_join", "why this company": "why_join",
            "why are you interested": "why_join", "motivation": "why_join",
            "company": "work_history", "employer": "work_history",
            "role": "work_history", "job title": "work_history", "position": "work_history",
            "education": "education", "degree": "education", "qualification": "education",
            "linkedin": "linkedin", "linkedin profile": "linkedin",
            "portfolio": "portfolio", "website": "portfolio", "github": "portfolio",
            "salary": "skip", "expected salary": "skip", "current salary": "skip",
            "gender": "skip", "age": "skip", "date of birth": "skip",
            "race": "skip", "ethnicity": "skip", "disability": "skip",
        }

    def _normalize_label(self, label: str) -> str:
        return label.lower().strip().replace("?", "").replace("*", "").replace(":", "").strip()

    def _match_field_to_profile(self, label: str) -> tuple:
        normalized = self._normalize_label(label)

        if normalized in self.field_mapping:
            key = self.field_mapping[normalized]
            if key == "skip":
                return None, 1.0
            return key, 0.95

        for key, profile_key in self.field_mapping.items():
            if key in normalized or normalized in key:
                if profile_key == "skip":
                    return None, 0.0
                return profile_key, 2.75

        return None, 0.0

    def _determine_action(
        self, field_type: FieldType, confidence: float, required: bool, visible: bool, label: str
    ) -> tuple:
        """Returns (action, reason)."""
        if not visible:
            return ActionType.REVEAL, "Field not visible, may need interaction to reveal"

        if field_type == FieldType.CAPTCHA:
            return ActionType.PAUSE_USER, "CAPTCHA requires human verification"

        if field_type == FieldType.BUTTON and any(word in label.lower() for word in ["add", "new", "+", "more"]):
            return ActionType.CLICK, "Button to reveal additional fields"

        if field_type == FieldType.SUBMIT:
            return ActionType.HIGHLIGHT, "Submit button - highlighted for user review"

        if field_type in [FieldType.SELECT, FieldType.RADIO, FieldType.CHECKBOX]:
            return ActionType.SELECT, "Selection field"

        if field_type == FieldType.FILE:
            return ActionType.UPLOAD, "File upload required"

        if confidence < 0.5 and required:
            return ActionType.PAUSE_USER, f"Unknown required field: '{label}' - needs human input"

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
            parsed = {"fields": [], "has_captcha": False, "has_submit": False, "is_multi_step": False, "notes": ""}

        # Convert to FormField objects
        analyzed_fields = []
        total_confidence = 1.0

        for raw in parsed.get("fields", []):
            field_type = FieldType(raw.get("type", "unknown"))
            label = raw.get("label", "")
            required = raw.get("required", False)
            visible = raw.get("visible", True)
            options = raw.get("options", [])

            # Match to profile
            profile_key, confidence = self._match_field_to_profile(label)
            value = self.profile.get(profile_key) if profile_key else None

            # Determine action
            action, reason = self._determine_action(field_type, confidence, required, visible, label)

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

        avg_confidence = total_confidence / len(analyzed_fields) if analyzed_fields else 1.0

        has_captcha = parsed.get("has_captcha", False) or any(f.field_type == FieldType.CAPTCHA for f in analyzed_fields)
        has_submit = parsed.get("has_submit", False) or any(f.field_type == FieldType.SUBMIT for f in analyzed_fields)

        if has_captcha:
            recommendation = "CAPTCHA detected. Agent will pause for user intervention."
        elif avg_confidence < 0.5:
            recommendation = "Low confidence in field mapping. Agent will highlight uncertain fields."
        else:
            recommendation = "High confidence. Agent will auto-fill with user supervision."

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
            parsed = json.loads(response[response.find("{"): response.rfind("}") + 1])
        except Exception:
            parsed = {"fields": [], "has_captcha": False, "has_submit": False}

        # Re-use screenshot analysis path for conversion
        return await self.analyze_screenshot(await page.screenshot())


# ============================================================
# FORM FILLER
# ============================================================

class FormFiller:
    """Executes form filling actions using Playwright."""

    def __init__(self, page: Page, analyzer: FormAnalyzer):
        self.page = page
        self.analyzer = analyzer
        self.log: List[str] = []
        self.errors: List[str] = []
        self.user_interventions: List[str] = []

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
                    self.log.append(f"  [OK] Selected '{opt}' (matched '{value}') for '{field.label}'")
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

    async def apply_to_job(self, job_url: str, headless: bool = False) -> Dict:
        """Apply to a single job."""
        print(f"\n  [AGENT] Opening job application: {job_url}")

        from playwright.async_api import async_playwright  # lazy import to avoid top-level dep issues

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            page = await browser.new_page()

            try:
                await page.goto(job_url, wait_until="networkidle")
                await asyncio.sleep(2)  # Let dynamic content load

                # Take screenshot
                screenshot = await page.screenshot()

                # Fill form
                filler = FormFiller(page, self.analyzer)
                result = await filler.fill_form(screenshot)

                # Print results
                print("\n".join(result["log"]))

                # If multi-step, handle next steps
                if result["analysis"].is_multi_step:
                    print("\n  [AGENT] Multi-step form detected. Taking another screenshot...")
                    await asyncio.sleep(2)
                    screenshot2 = await page.screenshot()
                    result2 = await filler.fill_form(screenshot2)
                    print("\n".join(result2["log"]))

                # Keep browser open for user review
                if not headless:
                    print("\n  [AGENT] Browser kept open for review. Press Enter to close...")
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
