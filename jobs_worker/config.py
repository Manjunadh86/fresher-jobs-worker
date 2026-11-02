"""Environment-driven settings. Everything has a sane default so `python -m jobs_worker run` works bare."""
from __future__ import annotations

import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


# Where the SQLite DB, digests and caches live. Mount this as a volume in Docker.
DATA_DIR = Path(_env("JOBS_DATA_DIR", str(Path(__file__).resolve().parents[1] / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "jobs.sqlite3"

TZ = _env("TZ", "Asia/Kolkata")
DIGEST_TIME = _env("DIGEST_TIME", "08:30")            # HH:MM local time, daily
RUN_ON_START = _bool("RUN_ON_START", False)          # run immediately when `serve` starts

MNC_DAYS = _int("MNC_DAYS", 3)
STARTUP_DAYS = _int("STARTUP_DAYS", 10)
MNC_COUNT = _int("MNC_COUNT", 10)
STARTUP_MIN = _int("STARTUP_MIN", 10)
STARTUP_MAX = _int("STARTUP_MAX", 15)
INCLUDE_INTERNS = _bool("INCLUDE_INTERNS", False)
VERIFY_LINKS = _bool("VERIFY_LINKS", True)

ENABLE_ATS = _bool("ENABLE_ATS", True)
ENABLE_TALENTD = _bool("ENABLE_TALENTD", True)
ENABLE_LINKEDIN = _bool("ENABLE_LINKEDIN", True)
ENABLE_UNSTOP = _bool("ENABLE_UNSTOP", True)
ENABLE_INTERNSHALA = _bool("ENABLE_INTERNSHALA", True)
ADZUNA_APP_ID = _env("ADZUNA_APP_ID", "")          # optional: free key from developer.adzuna.com
ADZUNA_APP_KEY = _env("ADZUNA_APP_KEY", "")

# Control panel
ADMIN_TOKEN = _env("ADMIN_TOKEN", "")              # if set, Scrape/Hide in the web UI and Streamlit app require it

# Optional delivery
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK_URL = _env("DISCORD_WEBHOOK_URL", "")
SLACK_WEBHOOK_URL = _env("SLACK_WEBHOOK_URL", "")
GENERIC_WEBHOOK_URL = _env("GENERIC_WEBHOOK_URL", "")   # receives the digest JSON via POST
