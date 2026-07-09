"""
Browser automation scrapers + API scrapers for job platforms.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from .models import Job, Platform

logger = logging.getLogger(__name__)


# ─── Robust Selectors ──────────────────────────────────────────────────────────


class Selectors:
    """CSS selectors for each platform with fallbacks."""

    # LinkedIn
    LINKEDIN_CARDS = [
        ".job-search-card",
        ".occludable-job-posting",
        ".jobs-search-results__list-item",
        "[data-job-id]",
        ".reusable-search-result-container",
    ]
    LINKEDIN_TITLE = [".base-search-card__title", ".job-title", "h3"]
    LINKEDIN_COMPANY = [".base-search-card__subtitle", ".company"]
    LINKEDIN_LINK = [
        "a.base-card__full-link",
        "a[data-job-id]",
        "a[href*='/jobs/view']",
    ]

    # Indeed
    INDEED_CARDS = [
        "[data-jk]",
        ".card",
        "[class*='card']",
        ".job_seen_beacon",
        "li[class*='job']",
        "[data-testid*='job']",
    ]
    INDEED_TITLE = [
        "h2.jobTitle span",
        ".jobTitle",
        "h2",
        "[class*='title'] span",
        "span[class*='title']",
    ]
    INDEED_COMPANY = [
        "[data-testid='company-name']",
        "[data-testid*='company']",
        ".companyName",
        ".company",
        "[class*='company']",
    ]
    INDEED_LINK = [
        "a[id^='job_']",
        "a[href*='rc/clk']",
        "a[href*='/pagead/']",
        "a[data-jk]",
        "a[href*='/job/']",
    ]

    # Glassdoor
    GLASSDOOR_CARDS = [
        "[data-test*='job']",
        "[class*='JobCard']",
        "[data-test='cell-Jobs-url']",
        "[data-brandviews='JOB_CARD']",
        "[class*='jobListing']",
        "[class*='job-card']",
    ]
    GLASSDOOR_TITLE = [
        "[data-test='cell-Jobs-title']",
        "[class*='title'] a",
        "h2 a",
        "[class*='jobTitle']",
    ]
    GLASSDOOR_COMPANY = [
        "[data-test='employer-short-name']",
        "[data-test*='employer']",
        "[class*='employer']",
        "[class*='company']",
    ]
    GLASSDOOR_LINK = ["[data-test='cell-Jobs-url'] a", "a[href*='/job/']"]

    # Monster
    MONSTER_CARDS = [
        "[data-testid='job-card']",
        "[data-testid*='job']",
        ".job-card",
        "[class*='JobCard']",
        "section[data-testid='job-results'] > div",
        "article",
        "li[class]",
    ]
    MONSTER_TITLE = [
        "[data-testid='job-title']",
        "[data-testid*='title']",
        "h2 a",
        ".job-title",
        "[class*='title'] a",
        "h3",
    ]
    MONSTER_COMPANY = [
        "[data-testid='job-company']",
        "[data-testid*='company']",
        "[class*='company']",
        ".company-name",
        "[class*='org']",
    ]
    MONSTER_LINK = [
        "h2 a",
        "a[href*='/job/']",
        "a[href*='/jobs/']",
        "a.card-link",
        "a[data-testid*='link']",
    ]


# ─── Helper Functions ──────────────────────────────────────────────────────────


async def robust_query(page, selector: str) -> Optional[Any]:
    """Query a single element, returning None if not found."""
    try:
        return await page.query_selector(selector)
    except Exception:
        return None


async def robust_query_all(page, selector: str) -> List[Any]:
    """Query all elements matching selector."""
    try:
        return await page.query_selector_all(selector)
    except Exception:
        return []


async def get_text(el) -> str:
    """Get text content from element safely."""
    try:
        return await el.inner_text()
    except Exception:
        return ""


async def get_attr(el, attr: str) -> Optional[str]:
    """Get attribute from element safely."""
    try:
        return await el.get_attribute(attr)
    except Exception:
        return None


async def try_selectors(page, selectors: List[str], func) -> Optional[str]:
    """Try multiple selectors with a function."""
    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if el:
                result = await func(el)
                if result:
                    return result
        except Exception:
            continue
    return None


# ─── Overlay Dismissal ───────────────────────────────────────────────────────

DISMISS_SCRIPT = """
() => {
  // Dismiss common overlays, cookie banners, sign-up popups
  const selectors = [
    'button[aria-label*="Accept"]', 'button[aria-label*="accept"]',
    'button[aria-label*="Dismiss"]', 'button[aria-label*="dismiss"]',
    'button[aria-label*="Close"]', 'button[aria-label*="close"]',
    'button:has-text("Accept All")', 'button:has-text("Accept all")',
    'button:has-text("Got it")', 'button:has-text("Got It")',
    'button:has-text("OK")', 'button:has-text("Continue")',
    '#popup-close', '.modal-close', '.close-button',
    '[data-testid="modal-close"]', '[class*="close"]',
    'button:has-text("No thanks")', 'button:has-text("Not now")',
    'button:has-text("Skip")', 'button:has-text("Maybe later")',
    '[aria-label="Close"]', '[aria-label="Dismiss"]',
  ];
  for (const sel of selectors) {
    const btn = document.querySelector(sel);
    if (btn) { btn.click(); }
  }
  // Also remove common overlay divs
  const overlays = document.querySelectorAll('[class*="overlay"], [class*="modal"], [class*="popup"]');
  for (const el of overlays) {
    if (el.style) el.style.display = 'none';
  }
}
"""


async def dismiss_overlays(page):
    """Attempt to dismiss cookie banners and sign-up popups."""
    try:
        await page.evaluate(DISMISS_SCRIPT)
        await asyncio.sleep(0.5)
    except Exception:
        pass


async def safe_goto(page, url: str, timeout: int = 25000):
    """Navigate to URL with error handling and automatic overlay dismissal."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        await asyncio.sleep(2)
        await dismiss_overlays(page)
        await asyncio.sleep(1)
        return True
    except Exception as e:
        logger.warning(f"Navigation to {url[:60]}... failed: {e}")
        return False


# ─── Scraper Functions ─────────────────────────────────────────────────────────


async def scrape_linkedin(page, query: str, location: str, limit: int = 0) -> List[Job]:
    """Scrape LinkedIn job listings."""
    jobs = []
    url = f"https://www.linkedin.com/jobs/search/?keywords={quote(query)}&location={quote(location)}"
    logger.info(f"Searching LinkedIn: {url}")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Find job cards with fallback selectors
        cards = []
        for selector in Selectors.LINKEDIN_CARDS:
            cards = await robust_query_all(page, selector)
            if cards:
                logger.info(
                    f"Found {len(cards)} LinkedIn cards with selector: {selector}"
                )
                break

        cards_to_process = cards if limit <= 0 else cards[:limit]
        for card in cards_to_process:
            try:
                title_el = await robust_query(card, Selectors.LINKEDIN_TITLE[0])
                company_el = await robust_query(card, Selectors.LINKEDIN_COMPANY[0])
                link_el = await robust_query(card, "a")

                title = await get_text(title_el) if title_el else "Unknown"
                company = await get_text(company_el) if company_el else "Unknown"
                href = await get_attr(link_el, "href") if link_el else ""

                if href and href.startswith("/"):
                    href = "https://www.linkedin.com" + href

                jobs.append(
                    Job(
                        title=title.strip() or "Unknown",
                        company=company.strip() or "Unknown",
                        url=href or "",
                        platform=Platform.LINKEDIN,
                        description="",
                    )
                )
            except Exception as e:
                logger.warning(f"Error parsing LinkedIn card: {e}")

    except Exception as e:
        logger.error(f"Failed to scrape LinkedIn: {e}")

    return jobs


async def scrape_indeed(page, query: str, location: str, limit: int = 0) -> List[Job]:
    """Scrape Indeed job listings via embedded JSON data + DOM fallback."""
    jobs = []
    url = f"https://www.indeed.com/jobs?q={quote(query.replace(' ', '+'))}&l={quote(location.replace(' ', '+'))}&from=searchOnHP"
    logger.info(f"Searching Indeed: {url}")

    ok = await safe_goto(page, url)
    if not ok:
        # Try alternative Indeed URL format
        alt_url = f"https://www.indeed.com/jobs?q={quote(query.replace(' ', '+'))}&l={quote(location.replace(' ', '+'))}"
        logger.info("Indeed primary URL failed, trying fallback...")
        ok = await safe_goto(page, alt_url)
        if not ok:
            return jobs

    # Strategy 1: Extract from window.mosaic.providerData JSON
    try:
        extracted = await page.evaluate(
            """() => {
          try {
            const data = window.mosaic && window.mosaic.providerData &&
              window.mosaic.providerData['mosaic-provider-jobcards'];
            if (!data) return null;
            // metaData.mosaicProviderJobCardsModel.results contains jobs
            if (data.metaData && data.metaData.mosaicProviderJobCardsModel &&
                data.metaData.mosaicProviderJobCardsModel.results) {
              return data.metaData.mosaicProviderJobCardsModel.results;
            }
            // Sometimes results is directly on the data
            if (data.results) return data.results;
            return data;
          } catch(e) { return null; }
        }"""
        )

        if extracted and isinstance(extracted, list) and len(extracted) > 0:
            logger.info(f"Extracted {len(extracted)} Indeed jobs from mosaic JSON")
            cards_to_process = extracted if limit <= 0 else extracted[:limit]
            for item in cards_to_process:
                try:
                    title = (
                        item.get("title") or item.get("displayTitle") or ""
                    ).strip()
                    company = (
                        item.get("company")
                        or item.get("companyName")
                        or item.get("cmpH1")
                        or ""
                    ).strip()
                    jobkey = item.get("jobkey") or item.get("jk") or ""
                    href = (
                        f"https://www.indeed.com/viewjob?jk={jobkey}" if jobkey else ""
                    )
                    if title:
                        jobs.append(
                            Job(
                                title=title or "Unknown",
                                company=company or "Unknown",
                                url=href,
                                platform=Platform.INDEED,
                                description="",
                            )
                        )
                except Exception as e:
                    logger.warning(f"Error parsing Indeed JSON item: {e}")
            if jobs:
                return jobs
    except Exception as e:
        logger.warning(f"Indeed JSON extraction failed: {e}")

    # Strategy 2: DOM-based extraction with fallback selectors
    logger.info("Indeed JSON extraction returned no results, trying DOM selectors...")
    try:
        await page.wait_for_selector(
            '[class*="card"], [data-jk], .job_seen_beacon', timeout=8000
        )
        await asyncio.sleep(1)
    except:
        pass

    for selector in Selectors.INDEED_CARDS:
        cards = await robust_query_all(page, selector)
        if cards:
            logger.info(
                f"Found {len(cards)} Indeed cards with DOM selector: {selector}"
            )
            cards_to_process = cards if limit <= 0 else cards[:limit]
            for card in cards_to_process:
                try:
                    # Get href from card's anchor
                    link_el = await card.query_selector("a[href]")
                    href = await get_attr(link_el, "href") if link_el else ""

                    title = (
                        await get_text(
                            await robust_query(card, "h2, .jobTitle, [class*='title']")
                        )
                        or ""
                    )
                    company = (
                        await get_text(
                            await robust_query(
                                card, "[class*='company'], span[data-testid*='company']"
                            )
                        )
                        or ""
                    )
                    if not href:
                        jk_el = await card.query_selector("[data-jk]")
                        jk = await get_attr(jk_el, "data-jk") if jk_el else ""
                        if jk:
                            href = f"https://www.indeed.com/viewjob?jk={jk}"
                    if title:
                        jobs.append(
                            Job(
                                title=title.strip() or "Unknown",
                                company=company.strip() or "Unknown",
                                url=href or "",
                                platform=Platform.INDEED,
                                description="",
                            )
                        )
                except Exception as e:
                    logger.warning(f"Error parsing Indeed DOM card: {e}")
            break

    logger.info(f"Indeed total: {len(jobs)} jobs")
    return jobs


async def scrape_glassdoor(
    page, query: str, location: str, limit: int = 0
) -> List[Job]:
    """Scrape Glassdoor job listings with overlay dismissal + DOM + JSON fallbacks."""
    jobs = []
    url = f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={quote(query)}&loc={quote(location)}&srs=RECENT_SEARCHES"
    logger.info(f"Searching Glassdoor: {url}")

    ok = await safe_goto(page, url)
    if not ok:
        return jobs

    # Extra dismissal rounds for Glassdoor's aggressive overlays
    await dismiss_overlays(page)
    await asyncio.sleep(1)

    # Try to dismiss the Glassdoor sign-up wall specifically
    try:
        await page.evaluate(
            """() => {
          const btns = document.querySelectorAll('button, a, [role="button"]');
          for (const btn of btns) {
            const txt = (btn.textContent || '').toLowerCase();
            if (txt.includes('dismiss') || txt.includes('skip') || txt.includes('close') ||
                txt.includes('no thanks') || txt.includes('not now') || txt.includes('maybe later') ||
                txt.includes('accept')) {
              btn.click();
            }
          }
          // Remove modal/overlay divs
          document.querySelectorAll('[class*="modal"], [class*="overlay"], [role="dialog"]')
            .forEach(el => el.remove());
          // Un-hide body scroll
          document.body.style.overflow = 'auto';
        }"""
        )
        await asyncio.sleep(1)
    except Exception:
        pass

    # Strategy 1: Try to extract from embedded JSON (Apollo state or __NEXT_DATA__)
    try:
        extracted = await page.evaluate(
            """() => {
          try {
            // Next.js data
            const el = document.getElementById('__NEXT_DATA__');
            if (el) {
              const data = JSON.parse(el.textContent);
              return data;
            }
            // Apollo cache
            if (window.__APOLLO_STATE__) return window.__APOLLO_STATE__;
            return null;
          } catch(e) { return null; }
        }"""
        )
        if extracted:
            logger.info("Found embedded Glassdoor data, searching for jobs...")
            # Try to extract job listings from the data
            try:
                if isinstance(extracted, dict):
                    # Walk the dict looking for job arrays
                    def _find_job_arrays(obj, depth=0):
                        if depth > 5:
                            return None
                        if isinstance(obj, list) and len(obj) > 0:
                            # Check if this looks like a job list
                            if all(
                                isinstance(x, dict)
                                and (
                                    x.get("jobTitle")
                                    or x.get("title")
                                    or x.get("jobview")
                                )
                                for x in obj[:3]
                            ):
                                return obj
                        if isinstance(obj, dict):
                            for v in obj.values():
                                result = _find_job_arrays(v, depth + 1)
                                if result:
                                    return result
                        return None

                    job_array = _find_job_arrays(extracted)
                    if job_array:
                        logger.info(
                            f"Found {len(job_array)} jobs in embedded Glassdoor data"
                        )
                        for item in job_array:
                            title = item.get("jobTitle") or item.get("title") or ""
                            company = (
                                item.get("employer")
                                or item.get("company")
                                or item.get("employerName")
                                or ""
                            )
                            url = (
                                item.get("url")
                                or item.get("jobview")
                                or item.get("jobListingUrl")
                                or ""
                            )
                            if title:
                                if url and not url.startswith("http"):
                                    url = "https://www.glassdoor.com" + url
                                jobs.append(
                                    Job(
                                        title=title.strip() or "Unknown",
                                        company=company.strip() or "Unknown",
                                        url=url.strip() or "",
                                        platform=Platform.GLASSDOOR,
                                        description="",
                                    )
                                )
                            if len(jobs) >= (limit if limit > 0 else 100):
                                break
            except Exception as je:
                logger.warning(f"Glassdoor embedded data walk failed: {je}")
    except Exception as e:
        logger.warning(f"Glassdoor JSON extraction failed: {e}")

    # Strategy 2: DOM-based extraction
    for selector in Selectors.GLASSDOOR_CARDS:
        cards = await robust_query_all(page, selector)
        if cards:
            logger.info(f"Found {len(cards)} Glassdoor cards with selector: {selector}")
            cards_to_process = cards if limit <= 0 else cards[:limit]
            for card in cards_to_process:
                try:
                    title_el = await robust_query(card, "h2 a, [class*='title'], h2")
                    company_el = await robust_query(
                        card,
                        "[class*='employer'], [class*='company'], span[class*='Emp']",
                    )
                    link_el = await robust_query(
                        card, "a[href*='/job/'], a[href*='job' i]"
                    )

                    title = await get_text(title_el) if title_el else ""
                    company = await get_text(company_el) if company_el else ""
                    href = await get_attr(link_el, "href") if link_el else ""

                    if href and href.startswith("/"):
                        href = "https://www.glassdoor.com" + href

                    if title:
                        jobs.append(
                            Job(
                                title=title.strip() or "Unknown",
                                company=company.strip() or "Unknown",
                                url=href or "",
                                platform=Platform.GLASSDOOR,
                                description="",
                            )
                        )
                except Exception as e:
                    logger.warning(f"Error parsing Glassdoor card: {e}")
            if jobs:
                break

    # Strategy 3: Try broader selectors if nothing found
    if not jobs:
        try:
            all_links = await page.query_selector_all("a[href*='/job/']")
            for link in all_links:
                href = await get_attr(link, "href") or ""
                text = await get_text(link) or ""
                if text and href:
                    if href.startswith("/"):
                        href = "https://www.glassdoor.com" + href
                    jobs.append(
                        Job(
                            title=text.strip()[:80],
                            company="Unknown",
                            url=href,
                            platform=Platform.GLASSDOOR,
                            description="",
                        )
                    )
            if jobs:
                logger.info(f"Found {len(jobs)} Glassdoor jobs via broad link search")
        except Exception as e:
            logger.warning(f"Glassdoor broad search failed: {e}")

    # Try one more click on the job search results container
    if not jobs:
        try:
            await page.wait_for_timeout(2000)
            # Sometimes Glassdoor shows results in a ul or div with specific roles
            items = await page.query_selector_all(
                '[role="listitem"], [data-test*="job"], li[class*="job"]'
            )
            for item in items:
                text = await get_text(item)
                if text and len(text) > 10:
                    link_el = await item.query_selector("a")
                    href = await get_attr(link_el, "href") if link_el else ""
                    if href and href.startswith("/"):
                        href = "https://www.glassdoor.com" + href
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    title = lines[0] if lines else "Unknown"
                    company = lines[1] if len(lines) > 1 else "Unknown"
                    jobs.append(
                        Job(
                            title=title[:80],
                            company=company[:80],
                            url=href or "",
                            platform=Platform.GLASSDOOR,
                            description="",
                        )
                    )
        except Exception as e:
            logger.warning(f"Glassdoor listitem search failed: {e}")

    logger.info(f"Glassdoor total: {len(jobs)} jobs")
    return jobs


async def scrape_monster(page, query: str, location: str, limit: int = 0) -> List[Job]:
    """Scrape Monster.com job listings with JSON-LD + DOM selectors."""
    jobs = []
    url = f"https://www.monster.com/jobs/search/?q={quote(query)}&l={quote(location)}"
    logger.info(f"Searching Monster: {url}")

    ok = await safe_goto(page, url)
    if not ok:
        return jobs

    # Strategy 1: Extract from JSON-LD structured data (most stable)
    try:
        jsonld_data = await page.evaluate(
            """() => {
          const scripts = document.querySelectorAll('script[type="application/ld+json"]');
          const results = [];
          for (const script of scripts) {
            try {
              const data = JSON.parse(script.textContent);
              if (data['@type'] === 'ItemList' && data.itemListElement) {
                for (const item of data.itemListElement) {
                  if (item.item) results.push(item.item);
                }
              }
              // Single job posting
              if (data['@type'] === 'JobPosting' || data['@type'] === 'JobPostingList') {
                if (Array.isArray(data)) results.push(...data);
                else results.push(data);
              }
            } catch(e) {}
          }
          return results.length > 0 ? results : null;
        }"""
        )

        if jsonld_data and isinstance(jsonld_data, list) and len(jsonld_data) > 0:
            logger.info(f"Extracted {len(jsonld_data)} Monster jobs from JSON-LD")
            items_to_process = jsonld_data if limit <= 0 else jsonld_data[:limit]
            for item in items_to_process:
                try:
                    title = (item.get("title") or item.get("name") or "").strip()
                    company = ""
                    if item.get("hiringOrganization"):
                        company = item["hiringOrganization"].get("name", "") or ""
                    company = company or item.get("company", "") or ""
                    href = item.get("url") or item.get("@id") or ""
                    if title:
                        jobs.append(
                            Job(
                                title=title or "Unknown",
                                company=company.strip() or "Unknown",
                                url=href.strip() or "",
                                platform=Platform.MONSTER,
                                description="",
                            )
                        )
                except Exception as e:
                    logger.warning(f"Error parsing Monster JSON-LD item: {e}")
            if jobs:
                return jobs
    except Exception as e:
        logger.warning(f"Monster JSON-LD extraction failed: {e}")

    # Strategy 2: Try to extract from window.__INITIAL_STATE__ or similar
    try:
        state_data = await page.evaluate(
            """() => {
          try {
            if (window.__INITIAL_STATE__) return window.__INITIAL_STATE__;
            if (window.__NEXT_DATA__) return JSON.parse(document.getElementById('__NEXT_DATA__').textContent);
            return null;
          } catch(e) { return null; }
        }"""
        )
        if state_data:
            logger.info("Found Monster initial state data")
    except Exception:
        pass

    # Strategy 3: Wait for dynamic content and use DOM selectors
    try:
        await page.wait_for_selector(
            '[data-testid="job-card"], article, [class*="card"], li[class]',
            timeout=8000,
        )
        await asyncio.sleep(1)
    except:
        pass

    for selector in Selectors.MONSTER_CARDS:
        cards = await robust_query_all(page, selector)
        if cards:
            logger.info(
                f"Found {len(cards)} Monster cards with DOM selector: {selector}"
            )
            cards_to_process = cards if limit <= 0 else cards[:limit]
            for card in cards_to_process:
                try:
                    href = ""
                    # Try multiple link selectors
                    for link_sel in Selectors.MONSTER_LINK:
                        link_el = await robust_query(card, link_sel)
                        if link_el:
                            href = await get_attr(link_el, "href") or ""
                            if href:
                                break

                    title = ""
                    for title_sel in Selectors.MONSTER_TITLE:
                        title_el = await robust_query(card, title_sel)
                        if title_el:
                            title = await get_text(title_el) or ""
                            if title:
                                break

                    company = ""
                    for comp_sel in Selectors.MONSTER_COMPANY:
                        comp_el = await robust_query(card, comp_sel)
                        if comp_el:
                            company = await get_text(comp_el) or ""
                            if company:
                                break

                    if href and not href.startswith("http"):
                        href = "https://www.monster.com" + href

                    if title:
                        jobs.append(
                            Job(
                                title=title.strip() or "Unknown",
                                company=company.strip() or "Unknown",
                                url=href or "",
                                platform=Platform.MONSTER,
                                description="",
                            )
                        )
                except Exception as e:
                    logger.warning(f"Error parsing Monster DOM card: {e}")
            if jobs:
                break

    # Strategy 4: Broad link search as last resort
    if not jobs:
        try:
            links = await page.query_selector_all("a[href*='/job/'], a[href*='/jobs/']")
            seen = set()
            for link in links:
                href = await get_attr(link, "href") or ""
                text = await get_text(link) or ""
                if text and href and href not in seen:
                    seen.add(href)
                    if not href.startswith("http"):
                        href = "https://www.monster.com" + href
                    jobs.append(
                        Job(
                            title=text.strip()[:80],
                            company="Unknown",
                            url=href,
                            platform=Platform.MONSTER,
                            description="",
                        )
                    )
            if jobs:
                logger.info(f"Found {len(jobs)} Monster jobs via broad link search")
        except Exception as e:
            logger.warning(f"Monster broad search failed: {e}")

    logger.info(f"Monster total: {len(jobs)} jobs")
    return jobs


async def get_description(page, job: Job, context=None) -> str:
    """Get full job description from listing page with multiple extraction strategies.
    Tries to extract from the listing page first (using inline JSON-LD / meta tags),
    then falls back to navigating to the full job page.
    """
    if not job.url:
        return ""

    # Strategy 1: Navigate to the job page first (always navigate to the correct URL)
    # This avoids extracting description from a previous job's page via the page pool
    try:
        await page.goto(job.url, wait_until="domcontentloaded", timeout=35000)
        await asyncio.sleep(3)
        await dismiss_overlays(page)
    except Exception as e:
        logger.warning(f"Navigation to {job.url[:60]}... failed: {e}")
        # Try once more with a fresh page
        if context:
            try:
                old_page = page
                page = await context.new_page()
                await page.goto(job.url, wait_until="domcontentloaded", timeout=35000)
                await asyncio.sleep(3)
                await dismiss_overlays(page)
            except Exception as e2:
                logger.warning(f"Description recovery also failed: {e2}")
                return ""
        else:
            return ""

    # Strategy 2: Try to extract from embedded JSON-LD on the job page
    try:
        desc = await page.evaluate(
            """() => {
          const scripts = document.querySelectorAll('script[type="application/ld+json"]');
          for (const s of scripts) {
            try {
              const data = JSON.parse(s.textContent);
              if (data.description && data.description.length > 50) return data.description;
              // Some job boards nest description under itemListElement
              if (data.itemListElement && Array.isArray(data.itemListElement)) {
                for (const item of data.itemListElement) {
                  if (item.item && item.item.description && item.item.description.length > 50) 
                    return item.item.description;
                }
              }
            } catch(e) {}
          }
          // Try meta description
          const meta = document.querySelector('meta[name="description"]');
          if (meta && meta.getAttribute('content') && meta.getAttribute('content').length > 50)
            return meta.getAttribute('content');
          return null;
        }"""
        )
        if desc and len(desc) > 50:
            return desc[:3000]
    except Exception:
        pass

    # Strategy 3: Use broad selectors for each platform
    # These are updated selectors that match current DOM structures
    try:
        selectors_map = {
            Platform.LINKEDIN: [
                ".description__text",
                ".job-details-summarize__content",
                ".job-description",
                "div[id='job-description']",
                "[class*='description']",
                "article",
                "main",
            ],
            Platform.INDEED: [
                "#jobDescriptionText",
                ".job-snippet",
                "[class*='jobsearch-JobComponent']",
                "[class*='description']",
                "main",
            ],
            Platform.GLASSDOOR: [
                "[class*='description']",
                ".jobDescriptionContent",
                "[data-testid='job-description']",
                "article",
                "main",
            ],
            Platform.MONSTER: [
                "[data-testid='job-description']",
                ".job-description",
                "#jobDescriptionContent",
                "[class*='description']",
                "article",
                "main",
            ],
        }

        selectors = selectors_map.get(
            job.platform, ["body", "main", "article", "[class*='content']"]
        )

        for selector in selectors:
            el = await robust_query(page, selector)
            if el:
                text = await get_text(el)
                if text and len(text) > 50:
                    return text[:3000]

        # Fallback: get all visible text from body
        body = await robust_query(page, "body")
        if body:
            text = await get_text(body)
            # Filter out common non-content text
            lines = [
                l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 20
            ]
            if lines:
                combined = "\n".join(lines[:50])  # First 50 substantial lines
                if len(combined) > 50:
                    return combined[:3000]
            return text[:3000]

    except Exception as e:
        logger.warning(f"Failed to get description for {job.url}: {e}")

    return ""


# ─── API-Based Scrapers (no browser needed!) ──────────────────────────────────
# Reed and Adzuna provide official REST APIs that return structured JSON.
# These are much faster and more reliable than browser scraping.


def _get_api_keys() -> dict:
    """Get API keys for Reed and Adzuna from environment variables."""
    return {
        "reed_api_key": os.environ.get("REED_API_KEY", ""),
        "adzuna_app_id": os.environ.get("ADZUNA_APP_ID", ""),
        "adzuna_app_key": os.environ.get("ADZUNA_APP_KEY", ""),
        "adzuna_country": os.environ.get("ADZUNA_COUNTRY", "gb"),
    }


async def scrape_reed(query: str, location: str, limit: int = 0) -> List[Job]:
    """Search Reed.co.uk via their official Jobseeker API.
    Uses Basic Auth with the API key as username and blank password.
    Returns jobs with descriptions already included (no browser needed!).
    """
    keys = _get_api_keys()
    api_key = keys["reed_api_key"]
    if not api_key:
        logger.info("Reed API key not configured (set REED_API_KEY env var)")
        return []

    jobs = []
    max_results = min(limit, 100) if limit > 0 else 100  # API max is 100

    url = "https://www.reed.co.uk/api/1.0/search"
    params = {
        "keywords": query,
        "locationName": location,
        "resultsToTake": max_results,
    }

    auth = httpx.BasicAuth(username=api_key, password="")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params, auth=auth)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            logger.info(f"Reed: no results for '{query}' in {location}")
            return []

        logger.info(f"Reed API returned {len(results)} jobs for '{query}'")

        for item in results:
            try:
                title = (item.get("jobTitle") or "").strip()
                company = (item.get("employerName") or "").strip()
                description = (item.get("jobDescription") or "").strip()
                url = (item.get("jobUrl") or "").strip()
                location_name = (item.get("locationName") or "").strip()

                if title:
                    jobs.append(
                        Job(
                            title=title,
                            company=company or "Unknown",
                            url=url,
                            platform=Platform.REED,
                            location=location_name,
                            description=description[
                                :3000
                            ],  # Description comes free with API!
                        )
                    )
            except Exception as e:
                logger.warning(f"Error parsing Reed item: {e}")

    except httpx.HTTPStatusError as e:
        logger.error(f"Reed API HTTP error: {e}")
    except Exception as e:
        logger.error(f"Reed API request failed: {e}")

    return jobs


async def scrape_adzuna(query: str, location: str, limit: int = 0) -> List[Job]:
    """Search Adzuna via their official Jobs API.
    Uses app_id + app_key as query parameters.
    Returns jobs with descriptions already included (no browser needed!).
    """
    keys = _get_api_keys()
    app_id = keys["adzuna_app_id"]
    app_key = keys["adzuna_app_key"]
    country = keys.get("adzuna_country", "gb")

    if not app_id or not app_key:
        logger.info(
            "Adzuna API keys not configured (set ADZUNA_APP_ID + ADZUNA_APP_KEY env vars)"
        )
        return []

    jobs = []
    results_per_page = min(limit, 50) if limit > 0 else 50  # Keep reasonable

    # Adzuna supports multiple countries: gb, us, ca, au, de, fr, nl, za, in, br, pl, se, at
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": query,
        "where": location,
        "results_per_page": results_per_page,
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            logger.info(f"Adzuna: no results for '{query}' in {location} ({country})")
            return []

        logger.info(f"Adzuna API returned {len(results)} jobs for '{query}'")

        for item in results:
            try:
                title = (item.get("title") or "").strip()
                company = ""
                company_data = item.get("company", {})
                if isinstance(company_data, dict):
                    company = (company_data.get("display_name") or "").strip()
                elif isinstance(company_data, str):
                    company = company_data

                description = (item.get("description") or "").strip()
                url = (item.get("redirect_url") or "").strip()

                location_name = ""
                location_data = item.get("location", {})
                if isinstance(location_data, dict):
                    location_name = (location_data.get("display_name") or "").strip()

                if title:
                    jobs.append(
                        Job(
                            title=title,
                            company=company or "Unknown",
                            url=url,
                            platform=Platform.ADZUNA,
                            location=location_name,
                            description=description[:3000],  # Description included!
                        )
                    )
            except Exception as e:
                logger.warning(f"Error parsing Adzuna item: {e}")

    except httpx.HTTPStatusError as e:
        logger.error(f"Adzuna API HTTP error: {e}")
    except Exception as e:
        logger.error(f"Adzuna API request failed: {e}")

    return jobs
