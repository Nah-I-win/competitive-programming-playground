"""Codewars fetcher.

- Discovery: server-rendered kata-search pages (per language), 30 katas/page.
- Details: public API v1 (single challenge) — description, rank, tags, sample tests.
- Solutions: best effort — modern Codewars locks solution data behind the
  trainer (auth/gating); stored only when the legacy pages expose them.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from .. import config
from ..core import difficulty as diff
from ..core.http import hub
from ..core.util import md_to_html
from .base import Fetcher, Progress, parse_megabytes, parse_seconds

log = logging.getLogger("cw")

API = "https://www.codewars.com/api/v1"
SEARCH = "https://www.codewars.com/kata/search/"
KATA = "https://www.codewars.com/kata"


class Codewars(Fetcher):
    source = "codewars"
    host = "codewars.com"

    def __init__(self) -> None:
        super().__init__()
        self._api_session = hub.for_host("www.codewars.com")
        self._web_session = hub.for_host("codewars.com")

    # ------------------------------------------------------------------
    def refresh_contests(self, progress: Progress = None) -> list[dict]:
        return []                        # Codewars has no contests

    # ------------------------------------------------------------------
    def _api_meta(self, slug_or_id: str) -> Optional[dict]:
        status, text = self._api_session.get(f"/api/v1/code-challenges/{slug_or_id}")
        if status != 200:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    def refresh_metadata(self, progress: Progress = None,
                         resume_from: int = 0, pages: int = 0) -> list[dict]:
        """Discover katas from search pages and return metadata dicts.

        resume_from: search page offset (persisted so weekly refreshes only
                     crawl new region); pages: 0 -> crawl up to CW_MAX_SEARCH_PAGES.
        """
        out: list[dict] = []
        max_pages = pages or config.CW_MAX_SEARCH_PAGES
        for page in range(resume_from, resume_from + max_pages):
            slugs = self._search_page_slugs(page)
            if not slugs:
                break
            for slug in slugs:
                meta = self._api_meta(slug)
                if meta:
                    out.append(_kata_to_problem(meta))
            self._emit(progress, page + 1, resume_from + max_pages,
                       f"codewars page {page + 1} ({len(slugs)} katas)")
        return out

    def _search_page_slugs(self, page: int) -> list[str]:
        lang = config.CW_SEARCH_LANG
        status, html = self._web_session.get(
            f"/kata/search/{lang}?q=&page={page}",
            referer=f"{KATA}/search/{lang}",
        )
        if status != 200:
            return []
        slugs = sorted(set(re.findall(r'href="/kata/([a-z0-9\-]+)"', html)))
        return [s for s in slugs]

    # ------------------------------------------------------------------
    def fetch_problem_details(self, source_id: str) -> Optional[dict]:
        slug = source_id
        if source_id.startswith("http"):
            m = re.search(r"/kata/([a-z0-9\-]+)", source_id)
            slug = m.group(1) if m else source_id
        meta = self._api_meta(slug)
        if not meta:
            return None
        p = _kata_to_problem(meta)
        p["status"] = "fetched"
        p["last_error"] = None
        return p

    # ------------------------------------------------------------------
    def problems_for_contest(self, source_id: str) -> Optional[tuple[dict, list]]:
        return None

    # ------------------------------------------------------------------
    def harvest_solutions(self, source_id: str, max_per_problem: int = 3,
                          progress: Progress = None) -> dict:
        """Best effort for a single kata slug: returns {slug: [sol..]}."""
        langs = ("python", "cpp")
        out: list[dict] = []
        for lang in langs:
            for page in range(2):
                status, html = self._web_session.get(
                    f"/kata/{source_id}/solutions/{lang}?page={page}",
                    referer=f"/kata/{source_id}",
                )
                if status != 200:
                    break
                codes = _parse_solution_html(html, lang)
                if not codes:
                    break
                for code, author in codes:
                    out.append({"language": lang, "code": code, "author": author})
        return {source_id: out[:max_per_problem]}


def _kata_to_problem(meta: dict) -> dict:
    rank = meta.get("rank") or {}
    rank_id = rank.get("id") or 0          # -8 .. -1 (kyu), 1..8 (dan)
    kyu = -rank_id if rank_id < 0 else None
    raw_tags = meta.get("tags") or []
    if raw_tags and isinstance(raw_tags[0], dict):
        tags = [t.get("name", "") for t in raw_tags]
    else:
        tags = list(raw_tags)
    return {
        "source": "codewars",
        "source_id": meta["slug"],
        "title": meta["name"],
        "difficulty": diff.codewars_kyu_to_level(kyu),
        "rating": kyu,
        "statement": (meta.get("description") or "").strip(),
        "samples": _extract_sample_tests(meta.get("description") or ""),
        "tags": tags,
        "url": f"https://www.codewars.com/kata/{meta['slug']}",
        "time_limit_ms": None,
        "memory_limit_mb": None,
        "status": "pending",
        "last_error": None,
    }


_SAMPLE_RE = re.compile(
    r"(?is)```(?:python|cpp|c\+\+)?\s*\n(.*?)(?:```|$)"
)


def _extract_sample_tests(description: str) -> list[dict]:
    """Most katas embed sample tests as code blocks; store the block text so
    the user sees the real assertion style."""
    blocks = [m.group(1) for m in _SAMPLE_RE.finditer(description)]
    return [{"input": b.strip(), "output": "", "explanation": "sample test code block"}
            for b in blocks]


def _parse_solution_html(html: str, lang: str) -> list[tuple[str, str]]:
    """Solutions were historically server-rendered; now often a Vue shell.
    Parse whatever <pre>/<code> blocks exist."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    for pre in soup.find_all("pre"):
        code = pre.get_text("\n", strip=False).strip()
        author = ""
        parent = pre.find_parent()
        if parent:
            a = parent.find("a", class_=re.compile("user|author", re.I))
            if a:
                author = a.get_text(" ", strip=True)
        if code:
            out.append((code, author))
    return out