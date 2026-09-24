"""Central configuration for the Competitive Programming Playground."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Competitive Programming Playground"
APP_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent          # /programming-playground
DATA_DIR = Path(os.environ.get("CPP_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "playground.db"
TMP_DIR = Path(os.environ.get("CPP_TMP_DIR", "/tmp/opencode")) / "cpplayground"

for _p in (DATA_DIR, TMP_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Networking / rate limiting (seconds between requests, per host)
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = 25
MAX_RETRIES = 3
RATE_LIMITS = {               # min seconds between consecutive hits to a host
    "codeforces.com": 2.0,
    "leetcode.com": 1.2,
    "codewars.com": 1.2,
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_LANGUAGE = "Python"          # "Python" | "C++"
DEFAULT_TIME_LIMIT_MS = 2000         # used when a problem states no limit
DEFAULT_MEMORY_LIMIT_MB = 256

# Judging
COMPARE_MODE = "tokens"              # exact | tokens | numeric
FLOAT_TOLERANCE = 1e-6               # relative tolerance for numeric compare

# Difficulty mapping  (kept in sync with core.difficulty)
CF_EASY_RATING_MAX = 1199
CF_MEDIUM_RATING_MAX = 1999
CW_EASY_KYU_MIN = 6                  # kyu >= 6 -> easy (6,7,8)
CW_MEDIUM_KYU_MIN = 3                # 3 <= kyu < 6 -> medium

# Backfill
BACKFILL_BATCH = 60                  # problems processed in one worker cycle
BACKFILL_SLEEP_S = 2.0               # pause between cycles when idle
SOLUTIONS_PER_PROBLEM = 3            # max harvested accepted CF submissions/problem
HARVEST_ENABLED = True               # fetch accepted solutions (may be blocked)
SOL_HARVEST_TARGET_LANGS = ("GNU C++", "Python")  # preference order substring match

# Refresh schedules
CONTEST_REFRESH_HOURS = 24
METADATA_REFRESH_DAYS = 7
JOB_RETRY_BACKOFF_BASE_S = 60        # failed item retried after base * 2^attempts

# Codewars discovery
CW_SEARCH_LANG = "python"            # search pages are per-language
CW_MAX_SEARCH_PAGES = 200            # cap for initial discovery (200*30 katas)
CW_NEW_PAGES_PER_REFRESH = 10        # per weekly refresh, after first run

# Competition mode
SUPPORTED_PLATFORMS = ("codeforces", "leetcode")
COMPETITIONS_DIR = DATA_DIR / "competitions"