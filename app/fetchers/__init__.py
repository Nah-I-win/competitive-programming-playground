"""Fetcher registry + URL-based dispatch."""
from __future__ import annotations

from typing import Optional

from .base import Fetcher
from .codeforces import Codeforces
from .codewars import Codewars
from .leetcode import LeetCode

FETCHERS: dict[str, type[Fetcher]] = {
    "codeforces": Codeforces,
    "leetcode": LeetCode,
    "codewars": Codewars,
}


def fetcher_for(source: str) -> Fetcher:
    return FETCHERS[source]()


def detect_source(url: str) -> Optional[str]:
    u = url.lower()
    if "codeforces.com" in u:
        return "codeforces"
    if "codeforces" in u:
        return "codeforces"
    if "leetcode" in u:
        return "leetcode"
    if "codewars.com" in u or "codewars" in u:
        return "codewars"
    return None


def fetch_problem_by_url(url: str) -> Optional[dict]:
    """Fetch a problem dict from any supported URL and store it in the DB."""
    from .. import db
    source = detect_source(url)
    if not source:
        return None
    f = fetcher_for(source)
    details = f.fetch_problem_details(url)
    if not details or not details.get("source") or not details.get("source_id"):
        return None
    if details.get("status") == "failed":
        return None
    # carry over difficulty from existing metadata if present
    existing = db.get_db().problem_by_source(source, details["source_id"])
    if existing and existing.get("difficulty"):
        details.setdefault("difficulty", existing["difficulty"])
    pid = db.get_db().upsert_problem(details)
    details["id"] = pid
    return details