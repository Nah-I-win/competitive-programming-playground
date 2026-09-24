"""Synchronization service: metadata refresh, contest refresh, background
backfill, solution harvesting and competition-mode installation."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Callable, Optional

from .. import config, db as dbmod
from ..core import judge, lc_harness as harness
from ..fetchers import FETCHERS, fetcher_for

log = logging.getLogger("sync")

Progress = Callable[[int, int, str], None]
Stop = Callable[[], bool]


def _noop(a: int = 0, b: int = 0, msg: str = "") -> None:
    pass


# ===========================================================================
# Contests (daily refresh)
# ===========================================================================
def refresh_contests(progress: Progress = _noop) -> dict:
    db = dbmod.get_db()
    counts = {"codeforces": 0, "leetcode": 0}
    for source in ("codeforces", "leetcode"):
        try:
            rows = fetcher_for(source).refresh_contests(progress)
        except Exception as exc:
            log.exception("contests refresh failed for %s", source)
            continue
        for c in rows:
            db.upsert_contest(c)
        counts[source] = len(rows)
    db.set_meta("last_contest_refresh", int(time.time()))
    return counts


# ===========================================================================
# Metadata (weekly refresh) — incremental, skips existing problems
# ===========================================================================
def refresh_metadata(progress: Progress = _noop) -> dict:
    db = dbmod.get_db()
    stats = {"new": 0, "sources": {}}
    for source in ("codeforces", "leetcode"):
        try:
            problems = fetcher_for(source).refresh_metadata(progress)
            new = _bulk_upsert(problems, progress)
            stats["new"] += new
            stats["sources"][source] = new
        except Exception as exc:
            log.exception("metadata refresh failed for %s", source)
            stats["sources"][source] = f"error: {type(exc).__name__}"

    # Codewars: incremental crawl of search pages using the persisted offset.
    # The first run crawls the full window; later runs only new pages.
    cw = fetcher_for("codewars")
    resume = int(db.get_meta("cw_resume_page", 0) or 0)
    cw_pages = _advance_codewars(db, cw, resume, progress, stats)

    db.set_meta("last_metadata_refresh", int(time.time()))
    db.set_meta("total_problems", db.count_problems())
    if cw_pages:
        db.set_meta("cw_resume_page", resume + cw_pages)
    stats["cw_resume_page"] = resume + cw_pages
    return stats


def _advance_codewars(db, cw, resume, progress, stats) -> int:
    """Crawl CW search pages incrementally; returns number of pages crawled."""
    initial = resume == 0 and db.count_problems() == 0
    pages = config.CW_MAX_SEARCH_PAGES if initial else config.CW_NEW_PAGES_PER_REFRESH
    try:
        problems = cw.refresh_metadata(progress, resume_from=resume, pages=pages)
        new = _bulk_upsert(problems, progress)
        stats["new"] += new
        stats["sources"]["codewars"] = new
        return pages
    except Exception as exc:
        log.exception("codewars crawl failed")
        stats["sources"]["codewars"] = f"error: {type(exc).__name__}"
        return 0


def _bulk_upsert(problems: list[dict], progress: Progress) -> int:
    db = dbmod.get_db()
    new = 0
    total = len(problems)
    for i, p in enumerate(problems):
        try:
            db.upsert_problem(p)
            new += 1
        except Exception:
            log.exception("upsert failed: %s", p.get("source_id"))
        if (i + 1) % 100 == 0:
            progress(i + 1, total, f"storing metadata {i + 1}/{total}")
    return new


# ===========================================================================
# Backfill worker: fetch statements + sample tests for every pending problem
# ===========================================================================
def run_backfill(should_stop: Stop, progress: Progress = _noop,
                 max_problems: int = 0) -> dict:
    """Continuously fetches problem details. Returns stats when stopped or
    when max_problems was reached."""
    db = dbmod.get_db()
    done, failed, skipped = 0, 0, 0
    seen_batch = 0
    while not should_stop():
        pending = db.pending_problems(config.BACKFILL_BATCH)
        if not pending:
            if max_problems and seen_batch:
                break
            time.sleep(config.BACKFILL_SLEEP_S)
            continue
        seen_batch += 1
        for p in pending:
            if should_stop():
                break
            src = p["source"]
            try:
                f = fetcher_for(src)
                details = f.fetch_problem_details(p["source_id"])
            except Exception as exc:
                log.exception("backfill detail failed: %s/%s", src, p["source_id"])
                details = {"status": "failed", "last_error": f"exception: {exc}"}
            if details:
                _merge_details(db, p["id"], src, details)
                if details.get("status") == "fetched":
                    done += 1
                else:
                    failed += 1
            else:
                db.update_problem(p["id"], status="failed",
                                  last_error="fetch returned nothing")
                failed += 1
            progress(done + failed, done + failed,
                     f"backfill {src}: {p['source_id']} "
                     f"({done} ok, {failed} failed)")
            time.sleep(0.2)
        if max_problems and seen_batch >= max_problems:
            break
    return {"done": done, "failed": failed, "skipped": skipped}


def _merge_details(db, pid: int, source: str, details: dict) -> None:
    """Write details into the problems row, preserving rating/difficulty from
    the metadata already stored."""
    cur = db.problem_by_id(pid)
    fields: dict = {}
    for k in ("statement", "starter_py", "starter_cpp", "samples", "tags",
              "url", "time_limit_ms", "memory_limit_mb", "status", "last_error",
              "difficulty", "rating", "meta"):
        v = details.get(k)
        if v is not None and k not in ("difficulty", "rating"):
            fields[k] = v
    # keep known difficulty/rating if the page didn't provide better data
    if details.get("difficulty") and details["difficulty"] != "unrated":
        fields["difficulty"] = details["difficulty"]
    elif cur and cur.get("difficulty"):
        fields["difficulty"] = cur["difficulty"]
    if details.get("rating") is not None and not cur.get("rating"):
        fields["rating"] = details["rating"]
    fields.setdefault("status", "fetched")
    fields.setdefault("last_error", None)
    db.update_problem(pid, **fields)


# ===========================================================================
# Solution harvesting (Codeforces accepted submissions)
# ===========================================================================
def harvest_contest(contest_id: str, max_per_problem: int = None,
                    progress: Progress = _noop) -> dict:
    db = dbmod.get_db()
    max_per_problem = max_per_problem or config.SOLUTIONS_PER_PROBLEM
    key = f"harvest_blocked:{contest_id}"
    if db.get_meta(key):
        return {"blocked": True, "reason": db.get_meta(key)}

    f = fetcher_for("codeforces")
    result = f.harvest_solutions(contest_id, max_per_problem, progress)
    if not result:
        db.set_meta(key, "no acceptable data (source pages blocked?)")
        return {"blocked": True, "reason": key}
    stored = 0
    present = 0
    for idx, subs in result.items():
        pid_row = db.execute(
            "SELECT id FROM problems WHERE source='codeforces' AND source_id=?",
            (f"{contest_id}/{idx}",),
        ).fetchone()
        for s in subs:
            if s.get("code"):
                if pid_row:
                    db.upsert_solution(pid_row["id"], "codeforces",
                                       s["language"], s["code"], s.get("author", ""),
                                       {"submission_id": s.get("submission_id")})
                    stored += 1
            else:
                present += len([x for x in subs if x.get("code")])
    db.set_meta(f"harvest_last:{contest_id}", stored)
    return {"stored": stored}


# ===========================================================================
# Competition mode: install a contest from a URL
# ===========================================================================
def parse_contest_url(url: str) -> Optional[tuple[str, str, Optional[bool]]]:
    """Return (source, source_id, is_gym) or None."""
    u = url.strip()
    if "codeforces.com" in u:
        m = re.search(r"(?:contest|gym|problemset/problem)/(\d+)", u)
        if m:
            is_gym = "gym" in u
            return "codeforces", m.group(1), is_gym
    elif "leetcode.com" in u:
        m = re.search(r"/contest/([a-z0-9\-]+)", u)
        if m:
            return "leetcode", m.group(1), None
    return None


def install_competition(url: str, progress: Progress = _noop) -> dict:
    """Download everything for a contest link: info + problems (+ statement/
    samples where public). Creates a competition row and returns its id."""
    db = dbmod.get_db()
    parsed = parse_contest_url(url)
    if not parsed:
        raise ValueError(
            "Unsupported contest link. Supported: codeforces.com/contest/<id>, "
            "codeforces.com/gym/<id>, leetcode.com/contest/<slug>/"
        )
    source, source_id, is_gym = parsed
    f = fetcher_for(source)
    progress(0, 0, f"resolving contest {source_id} on {source}…")
    info, problems = f.problems_for_contest(source_id, gym=bool(is_gym))
    if not info:
        raise ValueError("Could not resolve that contest (not found or blocked).")

    comp_id = db.upsert_competition({
        "name": info["name"], "source": source, "url": info["url"],
        "source_id": info["source_id"],
        "start_time": info.get("start_time"), "duration": info.get("duration"),
    })
    names = {p["source_id"]: p["title"] for p in problems}
    urls = {p["source_id"]: p.get("url", "") for p in problems}
    if source == "codeforces" and is_gym:
        info["is_gym"] = True
    db.set_meta(f"comp_{comp_id}_is_gym", int(bool(is_gym)))

    total = len(problems)
    for i, p in enumerate(problems):
        sid = p["source_id"]
        cpid = db.add_competition_problem(comp_id, sid, p["title"], p.get("url", ""))
        progress(i + 1, total, f"downloading problem {i + 1}/{total}: {p['title']}")
        # try to fetch full details (statement + samples) and store in problems
        try:
            details = f.fetch_problem_details(sid)
        except Exception as exc:
            details = {"status": "failed", "last_error": str(exc)}
        if details and details.get("source") and details.get("source_id") \
                and details.get("status") != "failed":
            details.setdefault("title", names.get(sid, p["title"]))
            details.setdefault("url", urls.get(sid, p.get("url", "")))
            details.setdefault("contest_id", source_id)
            db.upsert_problem(details)
            _link_problem(cpid, source, details["source_id"])
            progress(i + 1, total, f"problem {i + 1}/{total} stored: {p['title']}")

    db.set_meta(f"comp_{comp_id}_installed_at", int(time.time()))
    return {"competition_id": comp_id, "name": info["name"], "problems": len(problems)}


def _link_problem(competition_problem_id: int, source: str, source_id: str) -> None:
    db = dbmod.get_db()
    row = db.execute(
        "SELECT id FROM problems WHERE source=? AND source_id=?",
        (source, source_id),
    ).fetchone()
    if row:
        db.execute(
            "UPDATE competition_problems SET problem_id=? WHERE id=?",
            (row["id"], competition_problem_id),
        )
        db.commit()


# ===========================================================================
# Convenience: judge a code string for a problem's tests and record the run
# ===========================================================================
def judge_problem(problem: Optional[dict], code: str, language: str,
                  samples: list[dict], custom: list[dict],
                  time_limit_ms: Optional[int], memory_mb: Optional[int],
                  compare_mode: str = config.COMPARE_MODE) -> tuple[str, bool, list[dict]]:
    tests = []
    for i, s in enumerate(samples or []):
        tests.append({"name": f"sample {i + 1}", "input": s.get("input", ""),
                      "expected": s.get("output", "")})
    for i, c in enumerate(custom or []):
        tests.append({"name": c.get("name", f"custom {i + 1}"),
                      "input": c.get("input", ""), "expected": c.get("expected", "")})
    if not tests:
        return "no tests", False, []
    tlm = time_limit_ms or config.DEFAULT_TIME_LIMIT_MS
    mmb = memory_mb or config.DEFAULT_MEMORY_LIMIT_MB

    # LeetCode Python solutions run through the auto-harness (function -> stdin)
    run_code = code
    if problem and problem.get("source") == "leetcode" and language == judge.LANG_PY:
        try:
            if any(harness.needs_harness(problem.get("meta"), t.get("input", ""))
                   for t in tests):
                wrapped = harness.build_python_harness(code, problem.get("meta"))
                if wrapped:
                    run_code = wrapped
        except Exception:
            pass

    j = judge.Judge()
    try:
        results = j.judge_code(run_code, language, tests, int(tlm), int(mmb),
                               compare_mode=compare_mode)
    finally:
        j.cleanup()
    nd = [r.as_dict() for r in results]
    summary, ok = judge.verdict_summary(results)
    return summary, ok, nd