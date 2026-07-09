"""
Main CLI orchestrator for Job Agent.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .ai import AIClient
from .config import AppConfig, load_config, load_profile, validate_config_run
from .dashboard import run_dashboard
from .dashboard_fastapi import run_fastapi_dashboard
from .feedback_learning import get_feedback_insights_for_prompt
from .form_filler import JobApplicationAgent, map_profile_to_form_filler
from .models import AIResult, Job, Platform
from .notifier import send_job_alert
from .scrapers import (
    get_description,
    scrape_adzuna,
    scrape_glassdoor,
    scrape_indeed,
    scrape_linkedin,
    scrape_monster,
    scrape_reed,
)
from .tracker import ApplicationTracker
from .utils import RateLimiter, ResumeHandler, load_session, save_session, setup_logging
from .word_exporter import ScoredJob, export_jobs_to_word, export_scored_jobs_to_word

# ─── Progress helpers ──────────────────────────────────────────────────────────


def _progress_bar(current: int, total: int, width: int = 30, label: str = "") -> str:
    """Render a text progress bar like  [████████░░░░░░░░░░] 8/20 Scoring jobs"""
    if total <= 0:
        return ""
    filled = int(width * current / total)
    bar = "#" * filled + "-" * (width - filled)
    pct = int(100 * current / total)
    return f"\r  [{bar}] {current}/{total} ({pct}%) {label}"


def _print_scoring_header(total: int):
    """Print the scoring phase header."""
    print(f"\n{'=' * 60}")
    print(f"  PHASE 2: Scoring {total} jobs with AI")
    print(f"{'=' * 60}\n")


def _print_cv_header(ranges_with_jobs: dict):
    """Print the CV generation phase header."""
    total_ranges = len(ranges_with_jobs)
    total_jobs = sum(len(v) for v in ranges_with_jobs.values())
    print(f"\n{'=' * 60}")
    print(
        f"  PHASE 3: Generating CVs for {total_ranges} score ranges ({total_jobs} jobs total)"
    )
    print(f"{'=' * 60}\n")


def _print_export_header(results: list):
    """Print the export phase header."""
    total_jobs = sum(count for _, _, count, _ in results)
    total_files = len(results) * 2  # Word + PDF per range
    print(f"\n{'=' * 60}")
    print(f"  PHASE 4: Exporting {total_jobs} jobs to {total_files} files")
    print(f"{'=' * 60}\n")


# ─── Maximum jobs to score per run ────────────────────────────────────────────
# Keeps total runtime reasonable given the 8s rate limit on free tier
MAX_JOBS_TO_SCORE = 50


# ─── CV-Based Relevance Check ────────────────────────────────────────────────


def _job_title_matches_skills(title: str, skills: list, target_roles: list) -> bool:
    """Quickly check if a job title shares keywords with the candidate's skills or target roles.
    This is a lightweight pre-filter to skip obviously irrelevant jobs before AI scoring.
    """
    lower_title = title.lower()

    # Build keyword set from skills (extract meaningful words)
    # Include ALL words with length >= 2 to catch short keywords like "AI", "ML", "NLP", "CV", "DL"
    skill_keywords = set()
    for skill in skills:
        for word in skill.lower().split():
            word = word.strip(" ,.()-/")
            if len(word) >= 2:  # Keep short keywords like "ai", "ml", "nlp", "cv", "dl"
                skill_keywords.add(word)

    # Check if any skill keyword appears in the title
    for kw in skill_keywords:
        if kw in lower_title:
            return True

    # Check if any target ROLE (the full role phrase) appears in the title
    # E.g. "AI Engineer" should match a title containing "AI Engineer"
    for role in target_roles:
        role_lower = role.lower()
        if role_lower in lower_title:
            return True

    # Also check individual words from target roles (with len >= 2)
    # This catches "Engineer" in "Senior AI Engineer", "ML" in "ML Engineer", etc.
    for role in target_roles:
        role_words = role.lower().split()
        for w in role_words:
            if len(w) >= 2 and w in lower_title:
                return True

    return False


# ─── Search ────────────────────────────────────────────────────────────────────


async def run_search(profile: dict, context, limit: int = 0):
    """Execute job search across all platforms in parallel.
    Creates one browser page per platform and runs scrapers concurrently.
    Generates smart queries by combining target roles with top CV skills.
    """
    queries = profile.get("target_roles", ["software engineer"])
    skills = profile.get("skills", [])
    # Use AGENT_LOCATION env var if set (from dashboard region selector), otherwise profile location
    location = os.environ.get("AGENT_LOCATION", "") or profile.get(
        "preferred_location", "Remote"
    )

    # ── Enhance search queries with top CV skills ──
    enhanced_queries = []
    top_skills = [s for s in skills if s][:5]  # Use top 5 skills

    for role in queries:
        # Always include the base role query
        enhanced_queries.append(role)
        # Also generate role + skill combinations for more targeted searches
        for skill in top_skills:
            skill_short = skill.split(" ")[0] if len(skill) > 15 else skill
            combined = f"{role} {skill_short}"
            if combined not in enhanced_queries:
                enhanced_queries.append(combined)

    # If we have too many queries, prioritize the most diverse ones
    if len(enhanced_queries) > 12:
        # Keep base roles + unique skill combinations
        unique_skills_combined = []
        seen_skills = set()
        for role in queries:
            for skill in top_skills:
                skill_word = skill.split()[0].lower() if skill.split() else ""
                if skill_word not in seen_skills:
                    seen_skills.add(skill_word)
                    unique_skills_combined.append(
                        f"{role} {skill.split()[0] if skill.split() else skill}"
                    )
        enhanced_queries = queries + unique_skills_combined[:8]

    all_jobs = []

    # Create one page per platform for concurrent scraping
    page_linkedin = await context.new_page()
    page_indeed = await context.new_page()
    page_glassdoor = await context.new_page()
    page_monster = await context.new_page()

    try:
        for query in enhanced_queries:
            print(f"\n[SEARCH] Searching for: '{query}'")

            # Fire all platform scrapers concurrently (browser + API)
            tasks = [
                scrape_linkedin(page_linkedin, query, location, limit=limit),
                scrape_indeed(page_indeed, query, location, limit=limit),
                scrape_glassdoor(page_glassdoor, query, location, limit=limit),
                scrape_monster(page_monster, query, location, limit=limit),
                scrape_reed(query, location, limit=limit),
                scrape_adzuna(query, location, limit=limit),
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            platforms = ["LinkedIn", "Indeed", "Glassdoor", "Monster", "Reed", "Adzuna"]
            for platform_name, result in zip(platforms, results):
                if isinstance(result, Exception):
                    print(f"   {platform_name} search failed: {result}")
                elif isinstance(result, list):
                    print(f"   Found {len(result)} {platform_name} jobs")
                    all_jobs.extend(result)
    finally:
        # Clean up all pages
        for p in [page_linkedin, page_indeed, page_glassdoor, page_monster]:
            await p.close()

    # ── Smart deduplication: by URL first, then by (title + company) across platforms ──
    seen_urls = set()
    seen_title_company = set()  # Lowercase (title, company) pairs
    unique_jobs = []

    for job in all_jobs:
        # Dedup by URL
        if job.url and job.url in seen_urls:
            continue
        if job.url:
            seen_urls.add(job.url)

        # Dedup by title+company (catches same job posted on multiple platforms)
        title_company_key = (job.title.strip().lower(), job.company.strip().lower())
        if title_company_key in seen_title_company:
            continue
        seen_title_company.add(title_company_key)

        unique_jobs.append(job)

    # ── Pre-filter: remove jobs whose titles don't match CV skills at all ──
    if skills or queries:
        before = len(unique_jobs)
        unique_jobs = [
            j
            for j in unique_jobs
            if _job_title_matches_skills(j.title, skills, queries)
        ]
        filtered = before - len(unique_jobs)
        if filtered:
            print(
                f"\n[FILTER] Removed {filtered} irrelevant jobs (title doesn't match CV skills)"
            )

    return unique_jobs


# ─── Main agent (search → score → CV → export) ──────────────────────────────


async def run_agent(config: AppConfig):
    """Main job search, scoring, CV generation, and export orchestrator."""
    logger = setup_logging("job_agent", data_dir=config.data_dir)

    try:
        profile = load_profile(config.profile_path)
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"ERROR: {e}")
        return 1

    # Initialize components
    resume_handler = ResumeHandler(config.resume_path)
    resume_handler.load()
    resume_text = resume_handler.get_for_cover_letter() if resume_handler else ""

    ai_client = AIClient(config)

    # Load feedback learning insights for self-improvement
    try:
        feedback_insights = get_feedback_insights_for_prompt(days=30)
        if feedback_insights:
            print(f"  [LEARN] Loaded feedback insights for agent self-improvement")
            ai_client.feedback_insights = feedback_insights
        else:
            ai_client.feedback_insights = ""
    except Exception as e:
        logger.warning(f"Could not load feedback insights: {e}")
        ai_client.feedback_insights = ""

    tracker = ApplicationTracker(data_dir=config.data_dir)

    print(f"\n{'=' * 60}")
    print(f"  Job Agent - Auto-Profile Mode")
    print(
        f"  Resume: {resume_handler.file_name if resume_handler.resume_path else 'None'}"
    )
    print(
        f"  Min score: {config.min_score}% | Max jobs: {'Unlimited' if config.max_job_search <= 0 else config.max_job_search}"
    )
    print(f"{'=' * 60}")

    # ── Wipe old data from previous runs ──
    if resume_handler.resume_path and resume_handler.resume_path.exists():
        tracker.clear()
        for old_file in Path(".").glob("jobs_*.docx"):
            old_file.unlink(missing_ok=True)
        for old_file in Path(".").glob("cv_*.pdf"):
            old_file.unlink(missing_ok=True)
        print(f"  [CLEAN] Cleared old data and output files for fresh run")

    # Track when the last AI call happened (used by rate limiter during scoring)
    _last_ai_call_time_global = 0.0

    # ── Auto-extract full profile from resume ──
    if resume_text and resume_text != "Resume on file":
        print(f"\n  [AI] Analyzing resume to extract profile details...")
        # Rate-limit the profile extraction call too (it's an AI call on the free tier)
        await asyncio.sleep(2.0)  # Small initial delay before first AI call
        _last_ai_call_time_global = asyncio.get_event_loop().time()
        try:
            extracted = await asyncio.to_thread(
                ai_client.extract_full_profile, resume_text
            )
            if extracted and extracted.get("name"):
                for field in [
                    "name",
                    "email",
                    "phone",
                    "linkedin_url",
                    "github_url",
                    "address",
                    "current_title",
                    "current_company",
                    "experience_summary",
                    "skills",
                    "education",
                    "bachelor",
                    "target_roles",
                ]:
                    if extracted.get(field):
                        profile[field] = extracted[field]

                print(f"  [AI] Extracted profile: {extracted.get('name', 'Unknown')}")
                print(f"  [AI] Skills: {len(extracted.get('skills', []))} skills found")
                print(
                    f"  [AI] Target roles: {', '.join(extracted.get('target_roles', profile.get('target_roles', [])))}"
                )

                profile_path = Path(config.profile_path)
                if profile_path.exists():
                    with open(profile_path) as f:
                        full_profile = json.load(f)
                    for field in [
                        "name",
                        "email",
                        "phone",
                        "linkedin_url",
                        "github_url",
                        "address",
                        "current_title",
                        "current_company",
                        "experience_summary",
                        "skills",
                        "education",
                        "bachelor",
                        "target_roles",
                    ]:
                        if extracted.get(field):
                            full_profile[field] = extracted[field]
                    if config.resume_path:
                        full_profile["resume_path"] = config.resume_path
                    with open(profile_path, "w") as f:
                        json.dump(full_profile, f, indent=2)
                    print(f"  [AI] Profile saved to {config.profile_path}")
            else:
                suggested_roles = ai_client.analyze_resume_for_keywords(
                    resume_text, profile.get("target_roles", [])
                )
                if suggested_roles:
                    profile["target_roles"] = suggested_roles
                    print(
                        f"  [AI] Suggested roles (fallback): {', '.join(suggested_roles)}"
                    )
        except Exception as e:
            logger.error(f"Failed to auto-extract profile: {e}")
            print(
                f"  [AI] Could not extract profile from resume (using existing profile)"
            )

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "ERROR: Playwright not installed. Run: pip install playwright && playwright install chromium"
        )
        return 1

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=config.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )

        # Stealth: remove webdriver detection
        await context.add_init_script(
            """
            // Anti-detection: hide webdriver, fix navigator
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            delete navigator.__proto__.webdriver;
            window.chrome = { runtime: {} };
            // Fix plugins array
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            // Fix languages
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            // Override permissions query to avoid detection
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """
        )

        if config.save_session:
            await load_session(context, "linkedin")

        # ── Phase 1: Search ──
        print(f"\n{'=' * 60}")
        print(f"  PHASE 1: Searching job platforms")
        print(f"{'=' * 60}\n")

        all_jobs = await run_search(profile, context, limit=config.max_job_search)

        print(f"  Found {len(all_jobs)} unique jobs across all platforms")

        # ── Phase 2: Score (parallel) ──
        _print_scoring_header(len(all_jobs))

        scored_jobs = []
        alertable_jobs = []  # Jobs with 60%+ score for email alerts
        high_match_count = 0
        completed_count = 0
        lock = asyncio.Lock()

        # Create a pool of pages for concurrent description fetching
        pool_size = min(5, max(1, len(all_jobs)))
        page_pool = asyncio.Queue()
        pool_pages = []
        for _ in range(pool_size):
            p = await context.new_page()
            pool_pages.append(p)
            await page_pool.put(p)

        # ── Rate limiter for OpenRouter free tier (~8 req/min for Llama 3.3 70B) ──
        # We enforce a strict minimum 12.0s gap between AI API calls to never exceed the limit.
        # _last_ai_call_time is initialized from the profile extraction call timestamp (if any)
        # so the first scoring call respects the rate limit from the extraction call.
        _ai_rate_lock = asyncio.Lock()
        _last_ai_call_time = _last_ai_call_time_global
        _min_ai_interval = (
            12.0  # seconds between AI calls (5 RPM max, well under 8 RPM free tier)
        )

        async def _rate_limited_ai_call(profile, job, resume_text) -> AIResult:
            """Make a rate-limited AI call. Guarantees at least `_min_ai_interval` seconds between calls."""
            nonlocal _last_ai_call_time

            async with _ai_rate_lock:
                # Wait if we've called too recently
                now = asyncio.get_event_loop().time()
                elapsed = now - _last_ai_call_time
                if elapsed < _min_ai_interval:
                    wait = _min_ai_interval - elapsed
                    print(f"\r  ⏳ Rate-limit wait: {wait:.1f}s ...")
                    sys.stdout.flush()
                    await asyncio.sleep(wait)

                # Make the actual AI call
                ai_result = await asyncio.to_thread(
                    ai_client.tailor_application, profile, job, resume_text
                )
                _last_ai_call_time = asyncio.get_event_loop().time()
                return ai_result

        async def _rate_limited_title_call(profile, job, resume_text) -> AIResult:
            """Make a rate-limited title-only AI call."""
            nonlocal _last_ai_call_time

            async with _ai_rate_lock:
                now = asyncio.get_event_loop().time()
                elapsed = now - _last_ai_call_time
                if elapsed < _min_ai_interval:
                    wait = _min_ai_interval - elapsed
                    await asyncio.sleep(wait)

                ai_result = await asyncio.to_thread(
                    ai_client.score_by_title_only, profile, job, resume_text
                )
                _last_ai_call_time = asyncio.get_event_loop().time()
                return ai_result

        async def score_one_job(job: Job):
            nonlocal high_match_count, completed_count

            # Step 1: Fetch description (if not already provided by API scrapers like Reed/Adzuna)
            if not job.description:
                page = await page_pool.get()
                try:
                    job.description = await get_description(page, job, context)
                except Exception:
                    job.description = ""
                finally:
                    await page_pool.put(page)

            if not job.description:
                # Use title-only AI scoring for ALL jobs, not just AI-related ones.
                # This ensures every job gets scored even if description fetching fails.
                try:
                    ai_result = await _rate_limited_title_call(
                        profile, job, resume_text
                    )
                    score = ai_result.match_score
                    async with lock:
                        completed_count += 1
                        tracker.save(job, ai_result)
                        tag = "*" if score >= 40 else ""
                        sys.stdout.write(
                            f"\r  {completed_count}/{len(all_jobs)} [T] {job.title[:35]:35s} -> {score}/100 (title only) {tag}\n"
                        )
                        # Also collect title-only alertable jobs (60%+)
                        if score >= 60:
                            alertable_jobs.append(
                                {
                                    "title": job.title,
                                    "company": job.company,
                                    "score": score,
                                    "url": job.url,
                                    "skills": ai_result.matching_skills,
                                    "is_title_only": True,
                                }
                            )
                        sys.stdout.flush()
                    return
                except Exception as e:
                    logger.error(f"Title-only AI error for {job.title}: {e}")
                    async with lock:
                        completed_count += 1
                        sys.stdout.write(
                            f"\r  {completed_count}/{len(all_jobs)} SKIP: {job.title[:40]} - title scoring failed      \n"
                        )
                        sys.stdout.flush()
                    tracker.save(job, AIResult(match_score=0))
                    return

            # Step 2: AI scoring (rate-limited to 1 call per 8 seconds)
            try:
                ai_result = await _rate_limited_ai_call(profile, job, resume_text)
                score = ai_result.match_score
            except Exception as e:
                logger.error(f"AI error for {job.title}: {e}")
                async with lock:
                    completed_count += 1
                    sys.stdout.write(
                        f"\r  {completed_count}/{len(all_jobs)} [X] {job.title[:35]:35s} -> ERROR\n"
                    )
                    sys.stdout.flush()
                tracker.save(job, AIResult(match_score=0))
                return

            # Step 3: Record result (under lock to protect shared state + file writes)
            async with lock:
                completed_count += 1
                tracker.save(job, ai_result)
                if score >= 80:
                    scored_jobs.append(ScoredJob(job, score, ai_result.cover_letter))
                    high_match_count += 1
                    sys.stdout.write(
                        f"\r  {completed_count}/{len(all_jobs)} [OK] {job.title[:35]:35s} -> {score}/100 *\n"
                    )
                else:
                    sys.stdout.write(
                        f"\r  {completed_count}/{len(all_jobs)} [  ] {job.title[:35]:35s} -> {score}/100\n"
                    )
                # Collect alertable jobs (60%+) for email notification
                if score >= 60:
                    alertable_jobs.append(
                        {
                            "title": job.title,
                            "company": job.company,
                            "score": score,
                            "url": job.url,
                            "skills": ai_result.matching_skills,
                            "is_title_only": False,
                        }
                    )
                sys.stdout.flush()

        # Process all jobs (description fetching is concurrent, AI scoring is serial)
        # Cap at MAX_JOBS_TO_SCORE to keep runtime reasonable
        jobs_to_score = all_jobs[:MAX_JOBS_TO_SCORE]
        if len(all_jobs) > MAX_JOBS_TO_SCORE:
            print(
                f"\n  ⚠ Scoring {MAX_JOBS_TO_SCORE} of {len(all_jobs)} jobs ({len(all_jobs) - MAX_JOBS_TO_SCORE} skipped — too many for free tier rate limits)"
            )
        tasks = [score_one_job(job) for job in jobs_to_score]
        await asyncio.gather(*tasks)

        # Cleanup page pool
        for p in pool_pages:
            await p.close()

        # Final scoring summary (use actual count scored, not total found)
        jobs_actual = len(jobs_to_score)
        sys.stdout.write(
            f"\r  [{('#' * 30)}] {jobs_actual}/{jobs_actual} (100%) Scoring complete\n"
        )
        sys.stdout.flush()

        print(
            f"\n  Results: {high_match_count} jobs with 80%+ match out of {jobs_actual} scored"
        )

        if config.save_session:
            await save_session(context, "linkedin")

        await browser.close()

    # ── Email Alert: Send top matches to user's email (auto-extracted from CV) ──
    user_email = profile.get("email", "")
    user_name = profile.get("name", "User")
    if alertable_jobs and user_email:
        print(
            f"\n  [EMAIL] Sending alert with {len(alertable_jobs)} top matches to {user_email}..."
        )
        try:
            sent = send_job_alert(user_email, user_name, alertable_jobs)
            if sent:
                print(f"  [EMAIL] ✅ Alert sent to {user_email}")
            else:
                print(
                    f"  [EMAIL] ⚠ Gmail SMTP not configured. Set GMAIL_USER + GMAIL_APP_PASSWORD env vars or configure in Admin panel."
                )
        except Exception as e:
            logger.error(f"Failed to send job alert email: {e}")
            print(f"  [EMAIL] ❌ Failed to send alert: {e}")
    elif not user_email:
        print(
            f"\n  [EMAIL] ⚠ No email found in profile - could not send job alert. Upload a resume with your email address."
        )
    else:
        print(f"\n  [EMAIL] No jobs scored 60%+ - no email sent.")

    # ── Phase 3: Generate CVs ──
    cv_texts = {}
    ranges_with_jobs = {}
    for sj in scored_jobs:
        if sj.score_range:
            ranges_with_jobs.setdefault(sj.score_range, []).append(sj)

    if ranges_with_jobs:
        _print_cv_header(ranges_with_jobs)

        cv_ranges = ["96-100", "91-95", "86-90", "80-85"]
        cv_to_generate = [r for r in cv_ranges if r in ranges_with_jobs]

        for idx, range_label in enumerate(cv_to_generate):
            jobs_in_range = ranges_with_jobs[range_label]
            sys.stdout.write(
                _progress_bar(idx, len(cv_to_generate), label="Generating CVs")
            )
            sys.stdout.write(
                f"\r  Generating CV for {range_label}% ({len(jobs_in_range)} jobs)..."
            )
            sys.stdout.flush()

            try:
                job_dicts = [
                    {
                        "title": sj.job.title,
                        "company": sj.job.company,
                        "description": sj.job.description or "",
                    }
                    for sj in jobs_in_range
                ]
                cv_text = ai_client.generate_cv(
                    profile, job_dicts, range_label, resume_text
                )
                cv_texts[range_label] = cv_text
                print(
                    f"\r  CV for {range_label}% ({len(jobs_in_range)} jobs) - done              "
                )
            except Exception as e:
                print(
                    f"\r  [X] CV for {range_label}% - failed: {e}                    "
                )

        sys.stdout.write(
            _progress_bar(
                len(cv_to_generate), len(cv_to_generate), label="CVs complete"
            )
        )
        sys.stdout.write("\n")
        sys.stdout.flush()
    else:
        print(f"\n  No jobs with 80%+ match - skipping CV generation.")

    # ── Phase 4: Export ──
    created_files = []
    if scored_jobs:
        results = export_scored_jobs_to_word(
            scored_jobs, profile.get("name", ""), ".", cv_texts
        )

        _print_export_header(results)
        for range_label, word_path, count, pdf_path in results:
            print(f"  {range_label}%: {count} jobs")
            print(f"    [Word] {word_path}")
            print(f"    [PDF]  {pdf_path}")
            if word_path and os.path.isfile(word_path):
                created_files.append(word_path)

        if created_files:
            print(f"\n  Opening {len(created_files)} Word file(s)...")
            for f in created_files:
                try:
                    os.startfile(f)
                    print(f"    Opened: {f}")
                except Exception as e:
                    print(f"    Could not open {f}: {e}")
    else:
        print(f"\n  No jobs to export (none scored 80%+).")

    # ── Summary ──
    stats = tracker.get_stats()
    print(f"\n{'=' * 60}")
    print(f"  COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Jobs searched:    {stats['total_jobs_reviewed']}")
    print(f"  Jobs 80%+ match:  {len(scored_jobs)}")
    print(f"  CVs generated:    {len(cv_texts)}")
    print(f"  Avg match score:  {stats['average_match_score']}")
    print(f"{'=' * 60}\n")

    return 0


# ─── Export (no scoring) ─────────────────────────────────────────────────────


async def export_jobs_only(config: AppConfig):
    """Export job listings to Word without opening job pages or scoring."""
    logger = setup_logging("job_agent")

    try:
        profile = load_profile(config.profile_path)
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"ERROR: {e}")
        return 1

    print(f"\n  Starting Job Export for: {profile['name']}")
    print(f"  Targets: {', '.join(profile.get('target_roles', []))}")
    print(f"  Mode: EXPORT ONLY - no scoring\n")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "ERROR: Playwright not installed. Run: pip install playwright && playwright install chromium"
        )
        return 1

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=config.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )

        await context.add_init_script(
            """
            // Anti-detection: hide webdriver, fix navigator
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            delete navigator.__proto__.webdriver;
            window.chrome = { runtime: {} };
            // Fix plugins array
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            // Fix languages
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            // Override permissions query to avoid detection
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """
        )

        if config.save_session:
            await load_session(context, "linkedin")

        all_jobs = await run_search(profile, context, limit=config.max_job_search)

        if config.save_session:
            await save_session(context, "linkedin")

        await browser.close()

    output_path = (
        config.word_export_path
        if hasattr(config, "word_export_path")
        else "job_listings.docx"
    )
    filepath = export_jobs_to_word(all_jobs, profile.get("name", ""), output_path)

    print(f"\n  [OK] Exported {len(all_jobs)} jobs to: {filepath}\n")
    return 0


# ─── Form auto-fill ──────────────────────────────────────────────────────────


async def run_apply(config: AppConfig, job_url: str, auto_submit: bool = False):
    """Auto-fill a job application form using AI + Playwright."""
    if (
        not config.openrouter_api_key
        and not config.ollama_base_url
        and not config.groq_api_key
    ):
        print(
            "[ERROR] No AI provider configured. Set OLLAMA_BASE_URL, OPENROUTER_API_KEY, or GROQ_API_KEY:"
        )
        print('   OLLAMA_BASE_URL="http://localhost:11434"   (local LLM — $0 cost)')
        print("   — or —")
        print('   export OPENROUTER_API_KEY="sk-or-..."')
        print("Get a free key at https://openrouter.ai")
        return 1

    try:
        profile = load_profile(config.profile_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}")
        return 1

    form_profile = map_profile_to_form_filler(profile)
    # Pass the OpenRouter key (or empty for Ollama which doesn't need one)
    api_key = config.openrouter_api_key or "ollama"
    agent = JobApplicationAgent(api_key, form_profile)
    result = await agent.apply_to_job(
        job_url, headless=config.headless, auto_submit=auto_submit
    )

    if "error" in result:
        print(f"\n  [ERROR] {result['error']}")
        return 1

    print(
        f"\n  Auto-fill complete. Success: {result.get('success_count', 0)}, Paused: {result.get('pause_count', 1)}"
    )
    return 0


# ─── Dashboard & stats ─────────────────────────────────────────────────────────


def run_dashboard_cmd(config: AppConfig):
    """Run the web dashboard (FastAPI by default)."""
    run_fastapi_dashboard(config)


def show_stats(config: AppConfig):
    """Show job scoring statistics."""
    tracker = ApplicationTracker()
    stats = tracker.get_stats()

    print("\n  Job Agent Statistics")
    print("  " + "=" * 38)
    print(f"  Jobs Reviewed:     {stats['total_jobs_reviewed']}")
    print(f"  Avg Match Score:   {stats['average_match_score']}")
    print("\n  By Platform:")
    for platform, count in stats.get("by_platform", {}).items():
        print(f"    {platform}: {count}")
    print()


def clear_history(config: AppConfig):
    """Clear scoring history."""
    tracker = ApplicationTracker()
    tracker.clear()
    print("  Scoring history cleared.")


# ─── CLI ───────────────────────────────────────────────────────────────────────


def main():
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(
        description="Job Agent - AI-powered job search, scoring, and CV generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Run command
    run_parser = subparsers.add_parser(
        "run", help="Search, score, generate CVs, export to Word + PDF"
    )
    run_parser.add_argument(
        "--profile", default="profiles/profile.json", help="Path to profile JSON"
    )
    run_parser.add_argument(
        "--headless", action="store_true", help="Run browser in headless mode"
    )
    run_parser.add_argument(
        "--min-score", type=int, default=70, help="Minimum match score (0-100)"
    )
    run_parser.add_argument(
        "--max-jobs",
        type=int,
        default=0,
        help="Max jobs to search per platform (0 = unlimited)",
    )
    run_parser.add_argument("--resume", help="Path to resume file (PDF or TXT)")
    run_parser.add_argument(
        "--output", default=".", help="Output directory for Word and PDF files"
    )

    # Export command
    export_parser = subparsers.add_parser(
        "export", help="Export job listings to Word (no scoring)"
    )
    export_parser.add_argument(
        "--profile", default="profiles/profile.json", help="Path to profile JSON"
    )
    export_parser.add_argument(
        "--headless", action="store_true", help="Run browser in headless mode"
    )
    export_parser.add_argument(
        "--output", default="job_listings.docx", help="Output Word file path"
    )
    export_parser.add_argument(
        "--max-jobs",
        type=int,
        default=0,
        help="Max jobs to search per platform (0 = unlimited)",
    )

    # Apply command (auto-fill job application form)
    apply_parser = subparsers.add_parser(
        "apply", help="Auto-fill a job application form using AI + Playwright"
    )
    apply_parser.add_argument("url", help="Job application URL to auto-fill")
    apply_parser.add_argument(
        "--profile", default="profiles/profile.json", help="Path to profile JSON"
    )
    apply_parser.add_argument(
        "--headless", action="store_true", help="Run browser in headless mode"
    )
    apply_parser.add_argument(
        "--auto-submit",
        action="store_true",
        help="Click submit without confirmation (use in headless/CI mode)",
    )

    # Dashboard
    dash_parser = subparsers.add_parser("dashboard", help="Start the web dashboard")
    dash_parser.add_argument("--port", type=int, default=8080, help="Dashboard port")
    dash_parser.add_argument("--host", default="127.0.0.1", help="Dashboard host")

    # Stats / clear
    subparsers.add_parser("stats", help="Show scoring statistics")
    subparsers.add_parser("clear", help="Clear scoring history")

    args = parser.parse_args()
    config = load_config()

    if args.command == "run":
        config.profile_path = args.profile
        config.headless = args.headless
        config.min_score = args.min_score
        config.max_job_search = args.max_jobs
        config.word_export_path = args.output
        if args.resume:
            config.resume_path = args.resume
    elif args.command == "apply":
        config.profile_path = args.profile
        config.headless = args.headless
    elif args.command == "dashboard":
        # On HF Spaces, host/port are auto-detected (0.0.0.0:7860)
        if not config.is_hf_space:
            config.dashboard_port = args.port
            config.dashboard_host = args.host

    if not args.command:
        parser.print_help()
        print("\n  Quick start:")
        print(
            "    python -m agent run              # Search, score, generate CVs, export"
        )
        print(
            "    python -m agent export            # Export job list to Word (no scoring)"
        )
        print(
            "    python -m agent apply <URL>       # Auto-fill a job application form"
        )
        print("    python -m agent dashboard         # Start dashboard")
        print("    python -m agent stats             # Show statistics\n")
        return 0

    if args.command == "run":
        if not validate_config_run(config):
            return 1
        return asyncio.run(run_agent(config))
    elif args.command == "export":
        config.profile_path = args.profile
        config.headless = args.headless
        config.word_export_path = args.output
        config.max_job_search = args.max_jobs
        return asyncio.run(export_jobs_only(config))
    elif args.command == "apply":
        auto_submit = getattr(args, "auto_submit", False)
        return asyncio.run(run_apply(config, args.url, auto_submit=auto_submit))
    elif args.command == "dashboard":
        run_dashboard_cmd(config)
        return 0
    elif args.command == "stats":
        show_stats(config)
        return 0
    elif args.command == "clear":
        clear_history(config)
        return 0


if __name__ == "__main__":
    sys.exit(main())
