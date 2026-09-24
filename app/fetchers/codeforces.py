"""Codeforces fetcher: official API (contests, problemset, standings, status)
+ statement/sample scraping from problem pages + best-effort harvesting of
accepted submission sources."""
from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from .. import config
from ..core import difficulty as diff
from ..core.http import hub
from ..core.util import html_to_text
from .base import Fetcher, Progress, parse_megabytes, parse_seconds

log = logging.getLogger("cf")

API = "https://codeforces.com/api"
WEB = "https://codeforces.com"


class Codeforces(Fetcher):
    source = "codeforces"
    host = "codeforces.com"

    def __init__(self) -> None:
        super().__init__()
        # use one session for API (same host, one throttle) — the hub session

    # ------------------------------------------------------------------
    def _api(self, method: str, params: dict | None = None) -> Optional[list | dict]:
        status, text = self.session.get(f"{API}/{method}", params=params or {})
        if status is None:
            return None
        try:
            import json
            data = json.loads(text)
        except Exception:
            log.warning("cf api %s bad json (status %s)", method, status)
            return None
        if data.get("status") != "OK":
            log.warning("cf api %s error: %s", method, data.get("comment"))
            return None
        return data.get("result")

    # ------------------------------------------------------------------
    def refresh_contests(self, progress: Progress = None) -> list[dict]:
        out: list[dict] = []
        for gym in (False, True):
            res = self._api("contest.list", {"gym": "true" if gym else "false"})
            if not isinstance(res, list):
                continue
            for c in res:
                phase = c.get("phase", "FINISHED")
                if phase == "BEFORE":
                    ph = "planned"
                elif phase == "CODING":
                    ph = "started"
                else:
                    ph = "finished"
                out.append({
                    "source": self.source,
                    "source_id": str(c["id"]),
                    "name": c["name"],
                    "url": f"{WEB}/contest/{c['id']}",
                    "start_time": c.get("startTimeSeconds"),
                    "duration": c.get("durationSeconds"),
                    "phase": ph,
                    "is_gym": int(bool(gym)),
                })
        return out

    # ------------------------------------------------------------------
    def refresh_metadata(self, progress: Progress = None) -> list[dict]:
        res = self._api("problemset.problems")
        if not isinstance(res, dict):
            return []
        problems = res.get("problems", [])
        total = len(problems)
        out: list[dict] = []
        for i, p in enumerate(problems):
            rating = p.get("rating")
            pid = f"{p['contestId']}/{p['index']}"
            out.append({
                "source": self.source,
                "source_id": pid,
                "contest_id": str(p["contestId"]),
                "index_code": p["index"],
                "title": p["name"],
                "difficulty": diff.cf_rating_to_level(rating),
                "rating": rating,
                "tags": p.get("tags", []),
                "url": f"{WEB}/contest/{p['contestId']}/problem/{p['index']}",
                "status": "pending",
            })
            self._emit(progress, i + 1, total, f"codeforces metadata {i+1}/{total}")
        return out

    # ------------------------------------------------------------------
    def fetch_problem_details(self, source_id: str) -> Optional[dict]:
        """source_id like '1234/A' or 'https://codeforces.com/contest/1234/problem/A'"""
        if source_id.startswith("http"):
            return self.fetch_problem_from_url(source_id)
        cid, idx = source_id.split("/", 1)
        return self._scrape_problem(cid, idx)

    def fetch_problem_from_url(self, url: str) -> Optional[dict]:
        m = re.search(r"(?:contest|problemset/problem)/(\d+)/problem/([A-Za-z0-9]+)", url)
        if not m:
            return None
        return self._scrape_problem(m.group(1), m.group(2))

    def _scrape_problem(self, cid: str, idx: str) -> Optional[dict]:
        page = f"/contest/{cid}/problem/{idx}"
        status, html = self.session.get(page)
        if status is None:
            return {"source_id": f"{cid}/{idx}", "status": "failed",
                    "last_error": "network error"}
        data = _parse_problem_page(html)
        if not data:
            return {"source_id": f"{cid}/{idx}", "status": "failed",
                    "last_error": f"statement page not parseable (status {status}); "
                                  "gym problems may require a login"}
        data.update({
            "source": self.source,
            "source_id": f"{cid}/{idx}",
            "contest_id": cid,
            "index_code": idx,
            "url": f"{WEB}{page}",
            "status": "fetched",
            "last_error": None,
        })
        return data

    # ------------------------------------------------------------------
    def problems_for_contest(self, source_id: str, gym: bool = False) -> Optional[tuple[dict, list]]:
        """Fetch contest info + problem list.

        The standings API only accepts from/count params for gym contests;
        for normal contests we take the problem list from problemset.problems
        (which also gives ratings). Contest info comes from contest.list."""
        cid = str(source_id)
        problems: list[dict] = []
        if gym:
            # gym standings require authentication; fall back to contest.list info
            info = {"source": self.source, "source_id": cid,
                    "name": f"Gym {cid}", "url": f"{WEB}/gym/{cid}",
                    "start_time": None, "duration": None, "needs_login": True}
            for c in self.refresh_contests():
                if str(c["source_id"]) == cid and c.get("is_gym"):
                    info.update(name=c["name"], start_time=c.get("start_time"),
                                duration=c.get("duration"))
                    break
        else:
            meta = self._api("problemset.problems")
            if not isinstance(meta, dict):
                return None
            info = {"source": self.source, "source_id": cid,
                    "name": f"Codeforces #{cid}", "url": f"{WEB}/contest/{cid}",
                    "start_time": None, "duration": None}
            iset = 0
            for p in meta.get("problems", []):
                if str(p.get("contestId")) == cid:
                    index = p.get("index", "")
                    problems.append({
                        "source_id": f"{cid}/{index}",
                        "index_code": index,
                        "title": p.get("name", index),
                        "url": f"{WEB}/contest/{cid}/problem/{index}",
                        "rating": p.get("rating"),
                    })
            # use contest.list to enrich info (name/start/duration)
            for c in self.refresh_contests():
                if str(c["source_id"]) == cid:
                    info.update(name=c["name"], start_time=c.get("start_time"),
                                duration=c.get("duration"))
                    break
        problems.sort(key=lambda x: _index_key(x.get("index_code", "")))
        return info, problems


def _index_key(index: str) -> tuple:
    """'A' -> (1,0), 'A2' -> (1,2), '10' -> (10,0)."""
    m = re.match(r"(\d+|[A-Za-z]+)(\d*)", index or "")
    if not m:
        return (ord(index[0]) if index else 0, 0)
    a, b = m.group(1), m.group(2)
    if a.isdigit():
        a_key = 10_000 + int(a)
    elif len(a) == 1:
        a_key = ord(a.upper()) - 64
    else:
        a_key = 5000 + sum((ord(ch) - 64) for ch in a.upper())
    return (a_key, int(b or 0) if b.isdigit() else 0)

    # ------------------------------------------------------------------
    def harvest_solutions(self, source_id: str, max_per_problem: int = 3,
                          progress: Progress = None) -> dict:
        """Fetch accepted submissions ids for a contest, then scrape source
        pages. Source pages are often DDoS-Guard protected (403) — we then
        simply skip, nothing is marked as failed forever (retried next cycle)."""
        res = self._api("contest.status",
                        {"contestId": source_id, "from": 1, "count": 2000, "verdict": "OK"})
        if not isinstance(res, list):
            return {}
        best: dict[str, list] = {}
        for s in res:
            idx = s.get("problem", {}).get("index", "")
            lang = s.get("programmingLanguage", "")
            sub_id = s.get("id")
            author = ", ".join(m.get("handle", "") for m in s.get("author", {}).get("members", []))
            if not idx or not sub_id:
                continue
            bucket = best.setdefault(idx, [])
            prio = _lang_priority(lang)
            if len(bucket) >= max_per_problem:
                continue
            bucket.append({
                "language": lang, "submission_id": sub_id, "author": author,
                "priority": prio, "timeMs": s.get("timeConsumedMillis"),
                "memoryKb": s.get("memoryConsumedBytes", 0) // 1024 if s.get("memoryConsumedBytes") else None,
            })
        result: dict[str, list] = {}
        for idx, subs in best.items():
            subs.sort(key=lambda x: x["priority"])
            picked: list[dict] = []
            seen_langs: set[str] = set()
            for s in subs:
                lang_key = "cpp" if "C++" in s["language"] else ("py" if "ython" in s["language"] else "other")
                if lang_key in seen_langs:
                    continue
                seen_langs.add(lang_key)
                picked.append(s)
            result[idx] = picked
        # now scrape each source page
        for idx, subs in result.items():
            with_sources: list[dict] = []
            for s in subs:
                code = self._fetch_submission_source(source_id, s["submission_id"])
                if code:
                    s["code"] = code
                    with_sources.append(s)
                else:
                    # keep placeholder so we don't re-harvest endlessly
                    s["code"] = None
            result[idx] = with_sources
            if progress:
                progress(0, 0, f"harvested {len(with_sources)}/{len(subs)} for problem {idx}")
        return result

    def _fetch_submission_source(self, cid: str, sid: int) -> Optional[str]:
        status, html = self.session.get(
            f"/contest/{cid}/submission/{sid}",
            referer=f"{WEB}/contest/{cid}/problem/A",
            allow_403=True,
        )
        if status != 200:
            return None
        m = re.search(r'<pre[^>]*id="program-source-text"[^>]*>(.*?)</pre>', html, re.S)
        if not m:
            return None
        return _unescape_code(m.group(1))


def _lang_priority(lang: str) -> int:
    """lower = preferred."""
    if "C++" in lang:
        return 0
    if "Python" in lang or "PyPy" in lang:
        return 1
    return 2


def _unescape_code(s: str) -> str:
    import html as h
    s = re.sub(r"<br\s*/?>", "\n", s)
    return h.unescape(re.sub(r"<[^>]+>", "", s)).strip("\n")


def _parse_problem_page(html: str) -> Optional[dict]:
    soup = BeautifulSoup(html, "html.parser")
    ps = soup.find("div", class_="problem-statement")
    if not ps:
        return None
    header = ps.find("div", class_="header")
    title = ""
    time_ms = config.DEFAULT_TIME_LIMIT_MS
    mem_mb = config.DEFAULT_MEMORY_LIMIT_MB
    if header:
        t = header.find("div", class_="title")
        if t:
            m_t = re.match(r"^[A-Za-z0-9]+\.\s*(.*)$", " ".join(t.get_text(" ", strip=True).split()))
            if m_t:
                title = m_t.group(1)
            else:
                title = " ".join(t.get_text(" ", strip=True).split())
        tl = header.find("div", class_="time-limit")
        if tl:
            time_ms = parse_seconds(tl.get_text(" ", strip=True).replace("time limit per test", ""))
        ml = header.find("div", class_="memory-limit")
        if ml:
            mem_mb = parse_megabytes(ml.get_text(" ", strip=True).replace("memory limit per test", ""))

    samples: list[dict] = []
    st = ps.find("div", class_="sample-test")
    if st:
        blocks = st.find_all(["div"], recursive=False)
        cur: dict | None = None
        for b in blocks:
            cls = " ".join(b.get("class", []))
            pre = b.find("pre")
            if not pre:
                continue
            text = pre.get_text("", strip=False).replace("\r", "").strip("\n")
            if "input" in cls:
                if cur:
                    samples.append(cur)
                cur = {"input": text, "output": "", "explanation": ""}
            elif "output" in cls and cur is not None:
                cur["output"] = text
        if cur:
            samples.append(cur)

    # samples excluded from the statement text, header stripped as well
    if st:
        st.extract()
    stmt_text = html_to_text(str(ps))
    return {
        "title": title or "Untitled",
        "statement": stmt_text,
        "samples": samples,
        "time_limit_ms": time_ms,
        "memory_limit_mb": mem_mb,
        "difficulty": None,          # filled from metadata
    }