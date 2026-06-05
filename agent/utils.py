"""
Utility functions for Job Agent.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional, Callable, Any

from .config import get_env, AppConfig

logger = logging.getLogger(__name__)

# ─── Logging Setup ─────────────────────────────────────────────────────────────

_LOG_DIR: Optional[Path] = None
_SESSION_DIR: Optional[Path] = None

def _ensure_dirs(data_dir: Optional[str] = None):
    """Initialize log and session directories based on data directory.
    If data_dir is None, checks DATA_DIR env var, then defaults to ".".
    """
    global _LOG_DIR, _SESSION_DIR
    if data_dir is None:
        data_dir = get_env("DATA_DIR", ".")
    logs_path = Path(data_dir) / "logs"
    logs_path.mkdir(parents=True, exist_ok=True)
    sessions_path = logs_path / "sessions"
    sessions_path.mkdir(parents=True, exist_ok=True)
    _LOG_DIR = logs_path
    _SESSION_DIR = sessions_path

# Initialize with default paths (will be re-initialized if DATA_DIR env var is set later)
_ensure_dirs()

def setup_logging(name: str = __name__, data_dir: Optional[str] = None) -> logging.Logger:
    """Configure logging for the application.
    Accepts optional data_dir to place log files in the correct persistent directory.
    """
    if data_dir:
        _ensure_dirs(data_dir)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(_LOG_DIR / "agent.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(name)


# ─── Rate Limiter ──────────────────────────────────────────────────────────────

class RateLimiter:
    """Adaptive rate limiter with exponential backoff."""
    
    def __init__(self, base_delay: float = 3.0, max_delay: float = 60.0):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.current_delay = base_delay
        self.failures = 0
    
    async def wait(self, context: str = ""):
        """Wait with adaptive delay."""
        if self.current_delay > self.base_delay:
            logger.info(f"Rate limit backoff: waiting {self.current_delay:.1f}s ({context})")
        await asyncio.sleep(self.current_delay)
    
    def success(self):
        """Record successful operation."""
        if self.failures > 0:
            self.failures -= 1
        self.current_delay = max(self.base_delay, self.current_delay * 0.8)
    
    def failure(self):
        """Record failed operation."""
        self.failures += 1
        self.current_delay = min(self.max_delay, self.current_delay * 1.5)
        logger.warning(f"Failure #{self.failures}, delay increased to {self.current_delay:.1f}s")


# ─── Session Persistence ───────────────────────────────────────────────────────

def get_session_path(platform: str) -> Path:
    """Get path for persisting platform session cookies."""
    return _SESSION_DIR / f"{platform}_session.json"


async def save_session(context, platform: str):
    """Persist browser context cookies to disk."""
    try:
        cookies = await context.cookies()
        path = get_session_path(platform)
        path.write_text(json.dumps(cookies, indent=2))
        logger.info(f"Saved {platform} session ({len(cookies)} cookies)")
    except Exception as e:
        logger.warning(f"Failed to save {platform} session: {e}")


async def load_session(context, platform: str) -> bool:
    """Restore browser context cookies from disk."""
    path = get_session_path(platform)
    if not path.exists():
        return False
    try:
        cookies = json.loads(path.read_text())
        if cookies:
            await context.add_cookies(cookies)
            logger.info(f"Restored {platform} session ({len(cookies)} cookies)")
            return True
    except Exception as e:
        logger.warning(f"Failed to load {platform} session: {e}")
    return False


# ─── Resume Handler ────────────────────────────────────────────────────────────

class ResumeHandler:
    """Handles resume parsing, validation, and application attachment."""
    
    def __init__(self, resume_path: Optional[str] = None):
        self.resume_path: Optional[Path] = Path(resume_path) if resume_path else None
        self.parsed_text: str = ""
        self.file_name: str = Path(resume_path).name if resume_path else ""
    
    def load(self, resume_path: Optional[str] = None) -> bool:
        """Load and parse resume file."""
        path = Path(resume_path) if resume_path else self.resume_path
        if not path:
            # Try default locations
            for candidate in ["resume.pdf", "resume.txt", "resume.docx", "logs/resume.pdf"]:
                if Path(candidate).exists():
                    path = Path(candidate)
                    break
        
        if not path or not path.exists():
            logger.warning("No resume file found, continuing without resume")
            return False
        
        self.resume_path = path
        self.file_name = path.name
        
        try:
            if path.suffix == ".txt":
                self.parsed_text = path.read_text(encoding="utf-8")
            elif path.suffix == ".pdf":
                try:
                    import PyPDF2
                    with open(path, "rb") as f:
                        reader = PyPDF2.PdfReader(f)
                        text_parts = [page.extract_text() or "" for page in reader.pages[:3]]
                        self.parsed_text = " ".join(text_parts)[:3000]
                except ImportError:
                    logger.warning("PyPDF2 not installed for PDF parsing")
                    self.parsed_text = ""
            else:
                logger.warning(f"Unsupported resume format: {path.suffix}")
                return False
            
            logger.info(f"Loaded resume: {path.name} ({len(self.parsed_text)} chars)")
            return True
        except Exception as e:
            logger.error(f"Failed to load resume: {e}")
            return False
    
    def get_for_cover_letter(self) -> str:
        """Return resume summary for cover letter generation."""
        if not self.parsed_text:
            return "Resume on file"
        return self.parsed_text[:1000] + "..." if len(self.parsed_text) > 1000 else self.parsed_text
    
    async def upload_or_attach(self, page, job_platform: str) -> bool:
        """Attempt to attach resume on job application forms."""
        if not self.resume_path or not self.resume_path.exists():
            return False
        
        selectors = [
            "input[type='file']",
            "input[id*='resume']",
            "input[id*='cv']",
            "input[name*='resume']",
            "input[name*='cv']",
            "[class*='resume'] input",
        ]
        
        for selector in selectors:
            try:
                input_el = await page.query_selector(selector)
                if input_el:
                    await input_el.set_input_files(str(self.resume_path))
                    logger.info(f"Attached resume to {job_platform} application")
                    return True
            except Exception:
                continue
        
        logger.info(f"Resume file ready but no upload field found on {job_platform}")
        return False


# ─── Retry Logic ───────────────────────────────────────────────────────────────

async def retry_async(
    func: Callable,
    *args,
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    context: str = "",
    **kwargs
) -> Any:
    """Execute an async function with retry logic and exponential backoff."""
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                delay = min(max_delay, base_delay * (2 ** attempt))
                logger.warning(f"Retry {attempt + 1}/{max_retries} after {delay:.1f}s ({context}): {e}")
                await asyncio.sleep(delay)
            else:
                logger.error(f"All {max_retries} retries exhausted ({context}): {e}")
    
    raise last_exception if last_exception else Exception("All retries failed")