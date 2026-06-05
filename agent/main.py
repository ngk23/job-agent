"""
Main CLI orchestrator for Job Agent.
"""

import asyncio
import json
import os
import sys
import argparse
from pathlib import Path

from .config import AppConfig, load_profile, load_config, validate_config_run
from .utils import setup_logging, RateLimiter, ResumeHandler, save_session, load_session
from .scrapers import scrape_linkedin, scrape_indeed, scrape_glassdoor, scrape_monster, get_description
from .ai import AIClient
from .tracker import ApplicationTracker
from .dashboard import run_dashboard
from .models import Job, Platform, AIResult
from .word_exporter import export_jobs_to_word, export_scored_jobs_to_word, ScoredJob


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
    print(f"\n{'='*60}")
    print(f"  PHASE 2: Scoring {total} jobs with AI")
    print(f"{'='*60}\n")


def _print_cv_header(ranges_with_jobs: dict):
    """Print the CV generation phase header."""
    total_ranges = len(ranges_with_jobs)
    total_jobs = sum(len(v) for v in ranges_with_jobs.values())
    print(f"\n{'='*60}")
    print(f"  PHASE 3: Generating CVs for {total_ranges} score ranges ({total_jobs} jobs total)")
    print(f"{'='*60}\n")


def _print_export_header(results: list):
    """Print the export phase header."""
    total_jobs = sum(count for _, _, count, _ in results)
    total_files = len(results) * 2  # Word + PDF per range
    print(f"\n{'='*60}")
    print(f"  PHASE 4: Exporting {total_jobs} jobs to {total_files} files")
    print(f"{'='*60}\n")


# ─── AI Title Keywords ─────────────────────────────────────────────────────────

AI_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "ml", "deep learning", "dl",
    "computer vision", "cv", "nlp", "natural language", "neural network", "neural",
    "data science", "data scientist", "llm", "large language model", "rag", "generative",
    "gen ai", "genai", "automation", "robotics", "robot",
    "tensorflow", "pytorch", "keras", "mlops", "prompt engineer", "prompting",
    "transformer", "classification", "regression", "object detection",
    "chatbot", "conversational", "speech", "vision", "image recognition",
    "recommendation", "reinforcement learning", "time series", "forecasting",
    "ai engineer", "ml engineer", "deep learning engineer", "ai/ml",
    "ai developer", "machine learning engineer", "data engineer",
    "cognitive", "intelligent", "predictive", "analytics",
]


def _is_ai_related(title: str, extra_keywords: list = None) -> bool:
    """Check if a job title contains AI/ML/DL related keywords (case-insensitive).
    Uses the default AI_KEYWORDS list merged with any extra keywords from profile.
    """
    keywords = AI_KEYWORDS.copy()
    if extra_keywords:
        for kw in extra_keywords:
            kw_lower = kw.strip().lower()
            if kw_lower and kw_lower not in keywords:
                keywords.append(kw_lower)
    lower_title = title.lower()
    return any(kw in lower_title for kw in keywords)


# ─── Search ────────────────────────────────────────────────────────────────────

async def run_search(profile: dict, context, limit: int = 0):
    """Execute job search across all platforms in parallel.
    Creates one browser page per platform and runs scrapers concurrently.
    """
    queries = profile.get("target_roles", ["software engineer"])
    # Use AGENT_LOCATION env var if set (from dashboard region selector), otherwise profile location
    location = os.environ.get("AGENT_LOCATION", "") or profile.get("preferred_location", "Remote")

    all_jobs = []

    # Create one page per platform for concurrent scraping
    page_linkedin = await context.new_page()
    page_indeed = await context.new_page()
    page_glassdoor = await context.new_page()
    page_monster = await context.new_page()

    try:
        for query in queries:
            print(f"\n[SEARCH] Searching for: '{query}'")

            # Fire all 4 platform scrapers concurrently
            tasks = [
                scrape_linkedin(page_linkedin, query, location, limit=limit),
                scrape_indeed(page_indeed, query, location, limit=limit),
                scrape_glassdoor(page_glassdoor, query, location, limit=limit),
                scrape_monster(page_monster, query, location, limit=limit),
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            platforms = ["LinkedIn", "Indeed", "Glassdoor", "Monster"]
            for platform_name, result in zip(platforms, results):
                if isinstance(result, Exception):
                    print(f"   {platform_name} search failed: {result}")
                else:
                    print(f"   Found {len(result)} {platform_name} jobs")
                    all_jobs.extend(result)
    finally:
        # Clean up all pages
        for p in [page_linkedin, page_indeed, page_glassdoor, page_monster]:
            await p.close()

    seen_urls = set()
    unique_jobs = []
    for job in all_jobs:
        if job.url and job.url not in seen_urls:
            seen_urls.add(job.url)
            unique_jobs.append(job)

    return unique_jobs


# ─── Main agent (search → score → CV → export) ────────────────────────────────

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
    tracker = ApplicationTracker(data_dir=config.data_dir)

    print(f"\n{'='*60}")
    print(f"  Job Agent - Auto-Profile Mode")
    print(f"  Resume: {resume_handler.file_name if resume_handler.resume_path else 'None'}")
    print(f"  Min score: {config.min_score}% | Max jobs: {'Unlimited' if config.max_job_search <= 0 else config.max_job_search}")
    print(f"{'='*60}")

    # ── Wipe old data from previous runs ──
    if resume_handler.resume_path and resume_handler.resume_path.exists():
        # Clear old tracker history so results are fresh for this CV
        tracker.clear()
        # Clean up old output files from previous runs
        for old_file in Path(".").glob("jobs_*.docx"):
            old_file.unlink(missing_ok=True)
        for old_file in Path(".").glob("cv_*.pdf"):
            old_file.unlink(missing_ok=True)
        print(f"  [CLEAN] Cleared old data and output files for fresh run")

    # ── Auto-extract full profile from resume ──
    if resume_text and resume_text != "Resume on file":
        print(f"\n  [AI] Analyzing resume to extract profile details...")
        try:
            extracted = ai_client.extract_full_profile(resume_text)
            if extracted and extracted.get('name'):
                # Merge extracted fields into the working profile
                for field in ['name', 'email', 'phone', 'linkedin_url', 'github_url',
                             'address', 'current_title', 'current_company',
                             'experience_summary', 'skills', 'education', 'bachelor',
                             'target_roles']:
                    if extracted.get(field):
                        profile[field] = extracted[field]

                print(f"  [AI] Extracted profile: {extracted.get('name', 'Unknown')}")
                print(f"  [AI] Skills: {len(extracted.get('skills', []))} skills found")
                print(f"  [AI] Target roles: {', '.join(extracted.get('target_roles', profile.get('target_roles', [])))}")

                # Save the full extracted profile to profile.json
                profile_path = Path(config.profile_path)
                if profile_path.exists():
                    # Load existing profile, update with extracted fields
                    with open(profile_path) as f:
                        full_profile = json.load(f)
                    for field in ['name', 'email', 'phone', 'linkedin_url', 'github_url',
                                 'address', 'current_title', 'current_company',
                                 'experience_summary', 'skills', 'education', 'bachelor',
                                 'target_roles']:
                        if extracted.get(field):
                            full_profile[field] = extracted[field]
                    # Also set resume_path for future runs
                    if config.resume_path:
                        full_profile['resume_path'] = config.resume_path
                    with open(profile_path, 'w') as f:
                        json.dump(full_profile, f, indent=2)
                    print(f"  [AI] Profile saved to {config.profile_path}")
            else:
                # Fallback: just try to get keywords
                suggested_roles = ai_client.analyze_resume_for_keywords(
                    resume_text, profile.get('target_roles', [])
                )
                if suggested_roles:
                    profile['target_roles'] = suggested_roles
                    print(f"  [AI] Suggested roles (fallback): {', '.join(suggested_roles)}")
        except Exception as e:
            logger.error(f"Failed to auto-extract profile: {e}")
            print(f"  [AI] Could not extract profile from resume (using existing profile)")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: Playwright not installed. Run: pip install playwright && playwright install chromium")
        return 1

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=config.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )

        # Stealth: remove webdriver detection
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            delete navigator.__proto__.webdriver;
            window.chrome = { runtime: {} };
        """)

        if config.save_session:
            await load_session(context, "linkedin")

        # ── Phase 1: Search ──
        print(f"\n{'='*60}")
        print(f"  PHASE 1: Searching job platforms")
        print(f"{'='*60}\n")

        all_jobs = await run_search(profile, context, limit=config.max_job_search)

        print(f"  Found {len(all_jobs)} unique jobs across all platforms")

        # ── Phase 2: Score (parallel) ──
        _print_scoring_header(len(all_jobs))

        scored_jobs = []
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

        # Semaphore to limit concurrent AI API calls
        ai_semaphore = asyncio.Semaphore(5)

        async def score_one_job(job: Job):
            nonlocal high_match_count, completed_count

            # Step 1: Fetch description (uses a page from the pool)
            page = await page_pool.get()
            try:
                job.description = await get_description(page, job, context)
            except Exception:
                job.description = ""
            finally:
                await page_pool.put(page)

            if not job.description:
                # Try title-only scoring if the job is AI/ML related
                profile_keywords = profile.get('ai_keywords', [])
                if _is_ai_related(job.title, profile_keywords):
                    async with ai_semaphore:
                        try:
                            ai_result = await asyncio.to_thread(
                                ai_client.score_by_title_only, profile, job, resume_text
                            )
                            score = ai_result.match_score
                            async with lock:
                                completed_count += 1
                                tracker.save(job, ai_result)
                                tag = "*" if score >= 40 else ""
                                sys.stdout.write(f"\r  {completed_count}/{len(all_jobs)} [T] {job.title[:35]:35s} -> {score}/100 (title only) {tag}\n")
                                sys.stdout.flush()
                            return
                        except Exception as e:
                            logger.error(f"Title-only AI error for {job.title}: {e}")
                            # Fall through to SKIP below
                
                async with lock:
                    completed_count += 1
                    sys.stdout.write(f"\r  {completed_count}/{len(all_jobs)} SKIP: {job.title[:40]} - no description      \n")
                    sys.stdout.flush()
                tracker.save(job, AIResult(match_score=0))
                return

            # Step 2: AI scoring (rate-limited by semaphore, run in thread to not block event loop)
            async with ai_semaphore:
                try:
                    ai_result = await asyncio.to_thread(
                        ai_client.tailor_application, profile, job, resume_text
                    )
                    score = ai_result.match_score
                except Exception as e:
                    logger.error(f"AI error for {job.title}: {e}")
                    async with lock:
                        completed_count += 1
                        sys.stdout.write(f"\r  {completed_count}/{len(all_jobs)} [X] {job.title[:35]:35s} -> ERROR\n")
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
                    sys.stdout.write(f"\r  {completed_count}/{len(all_jobs)} [OK] {job.title[:35]:35s} -> {score}/100 *\n")
                else:
                    sys.stdout.write(f"\r  {completed_count}/{len(all_jobs)} [  ] {job.title[:35]:35s} -> {score}/100\n")
                sys.stdout.flush()

        # Process all jobs concurrently
        tasks = [score_one_job(job) for job in all_jobs]
        await asyncio.gather(*tasks)

        # Cleanup page pool
        for p in pool_pages:
            await p.close()

        # Final scoring summary
        sys.stdout.write(f"\r  [{('#' * 30)}] {len(all_jobs)}/{len(all_jobs)} (100%) Scoring complete\n")
        sys.stdout.flush()

        print(f"\n  Results: {high_match_count} jobs with 80%+ match out of {len(all_jobs)} scored")

        if config.save_session:
            await save_session(context, "linkedin")

        await browser.close()

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
            # Progress bar for CV generation
            sys.stdout.write(_progress_bar(idx, len(cv_to_generate), label="Generating CVs"))
            sys.stdout.write(f"\r  Generating CV for {range_label}% ({len(jobs_in_range)} jobs)...")
            sys.stdout.flush()

            try:
                job_dicts = [
                    {"title": sj.job.title, "company": sj.job.company, "description": sj.job.description or ""}
                    for sj in jobs_in_range
                ]
                cv_text = ai_client.generate_cv(profile, job_dicts, range_label, resume_text)
                cv_texts[range_label] = cv_text
                print(f"\r  CV for {range_label}% ({len(jobs_in_range)} jobs) - done              ")
            except Exception as e:
                print(f"\r  [X] CV for {range_label}% - failed: {e}                    ")

        # Final CV progress bar
        sys.stdout.write(_progress_bar(len(cv_to_generate), len(cv_to_generate), label="CVs complete"))
        sys.stdout.write("\n")
        sys.stdout.flush()
    else:
        print(f"\n  No jobs with 80%+ match - skipping CV generation.")

    # ── Phase 4: Export ──
    created_files = []
    if scored_jobs:
        results = export_scored_jobs_to_word(scored_jobs, profile.get('name', ''), ".", cv_texts)

        _print_export_header(results)
        for range_label, word_path, count, pdf_path in results:
            print(f"  {range_label}%: {count} jobs")
            print(f"    [Word] {word_path}")
            print(f"    [PDF]  {pdf_path}")
            if word_path and os.path.isfile(word_path):
                created_files.append(word_path)

        # Open all created Word files
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
    print(f"\n{'='*60}")
    print(f"  COMPLETE")
    print(f"{'='*60}")
    print(f"  Jobs searched:    {stats['total_jobs_reviewed']}")
    print(f"  Jobs 80%+ match:  {len(scored_jobs)}")
    print(f"  CVs generated:    {len(cv_texts)}")
    print(f"  Avg match score:  {stats['average_match_score']}")
    print(f"{'='*60}\n")

    return 0


# ─── Export (no scoring) ───────────────────────────────────────────────────────

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
        print("ERROR: Playwright not installed. Run: pip install playwright && playwright install chromium")
        return 1

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=config.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            delete navigator.__proto__.webdriver;
            window.chrome = { runtime: {} };
        """)

        if config.save_session:
            await load_session(context, "linkedin")

        all_jobs = await run_search(profile, context, limit=config.max_job_search)

        if config.save_session:
            await save_session(context, "linkedin")

        await browser.close()

    output_path = config.word_export_path if hasattr(config, 'word_export_path') else "job_listings.docx"
    filepath = export_jobs_to_word(all_jobs, profile.get('name', ''), output_path)

    print(f"\n  [OK] Exported {len(all_jobs)} jobs to: {filepath}\n")
    return 0


# ─── Dashboard & stats ─────────────────────────────────────────────────────────

def run_dashboard_cmd(config: AppConfig):
    """Run the web dashboard."""
    run_dashboard(config)


def show_stats(config: AppConfig):
    """Show job scoring statistics."""
    tracker = ApplicationTracker()
    stats = tracker.get_stats()

    print("\n  Job Agent Statistics")
    print("  " + "=" * 38)
    print(f"  Jobs Reviewed:     {stats['total_jobs_reviewed']}")
    print(f"  Avg Match Score:   {stats['average_match_score']}")
    print("\n  By Platform:")
    for platform, count in stats.get('by_platform', {}).items():
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
    run_parser = subparsers.add_parser("run", help="Search, score, generate CVs, export to Word + PDF")
    run_parser.add_argument("--profile", default="profiles/profile.json", help="Path to profile JSON")
    run_parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    run_parser.add_argument("--min-score", type=int, default=70, help="Minimum match score (0-100)")
    run_parser.add_argument("--max-jobs", type=int, default=0, help="Max jobs to search per platform (0 = unlimited)")
    run_parser.add_argument("--resume", help="Path to resume file (PDF or TXT)")
    run_parser.add_argument("--output", default=".", help="Output directory for Word and PDF files")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export job listings to Word (no scoring)")
    export_parser.add_argument("--profile", default="profiles/profile.json", help="Path to profile JSON")
    export_parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    export_parser.add_argument("--output", default="job_listings.docx", help="Output Word file path")
    export_parser.add_argument("--max-jobs", type=int, default=0, help="Max jobs to search per platform (0 = unlimited)")

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
    elif args.command == "dashboard":
        # On HF Spaces, host/port are auto-detected (0.0.0.0:7860)
        # Only apply argparse overrides when running locally
        if not config.is_hf_space:
            config.dashboard_port = args.port
            config.dashboard_host = args.host

    if not args.command:
        parser.print_help()
        print("\n  Quick start:")
        print("    python -m agent run              # Search, score, generate CVs, export")
        print("    python -m agent export            # Export job list to Word (no scoring)")
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
