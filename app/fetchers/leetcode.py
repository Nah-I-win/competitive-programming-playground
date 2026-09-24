"""LeetCode fetcher.

Discovery + details use the public GraphQL endpoint. A cookie-seeding GET is
done first because the origin returns 403 to bare POSTs; with a browser
User-Agent + Referer + cookie jar the same POST succeeds.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from .. import config
from ..core.http import hub
from ..core.util import html_to_text
from .base import Fetcher, Progress

log = logging.getLogger("lc")

GRAPHQL = "https://leetcode.com/graphql"
API_ALL = "https://leetcode.com/api/problems/all/"
API_TAGS = "https://leetcode.com/api/tags/"

_Q_QUESTION = """query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionId questionFrontendId title titleSlug content
    exampleTestcaseList codeSnippets { lang langSlug code }
    difficulty topicTags { slug name } stats metaData
  }
}"""

_Q_PROBLEMSET = """query { problemsetQuestionList: questionList(categorySlug:"",limit:1,skip:0,filters:{}){ totalNum } }"""

_Q_CONTESTS = """query allContests { allContests { title titleSlug startTime duration } }"""


class LeetCode(Fetcher):
    source = "leetcode"
    host = "leetcode.com"

    def __init__(self) -> None:
        super().__init__()
        self._warmed = False

    # ------------------------------------------------------------------
    def _warm(self) -> None:
        if self._warmed:
            return
        # seed cookies (home page may 403 before JS — harmless)
        self.session.get("/", allow_403=True)
        self._warmed = True

    def _graphql(self, query: str, variables: dict) -> Optional[dict]:
        self._warm()
        status, text = self.session.post_json(
            GRAPHQL, {"operationName": None, "variables": variables, "query": query},
            referer="https://leetcode.com/problemset/all/",
        )
        if status is None or status >= 400:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    # ------------------------------------------------------------------
    def refresh_contests(self, progress: Progress = None) -> list[dict]:
        data = self._graphql(_Q_CONTESTS, {})
        if not data:
            return []
        out: list[dict] = []
        now = __import__("time").time()
        for c in data.get("data", {}).get("allContests", []) or []:
            start = int(c.get("startTime") or 0)
            # LeetCode does not expose endTime reliably; weekly/biweekly = 90 min
            duration = int(c.get("duration") or 5400)
            if not start:
                continue
            if start > now:
                phase = "planned"
            elif now < start + duration:
                phase = "started"
            else:
                phase = "finished"
            out.append({
                "source": self.source,
                "source_id": c["titleSlug"],
                "name": c["title"],
                "url": f"https://leetcode.com/contest/{c['titleSlug']}/",
                "start_time": start,
                "duration": duration,
                "phase": phase,
                "is_gym": 0,
            })
        return out

    # ------------------------------------------------------------------
    def refresh_metadata(self, progress: Progress = None) -> list[dict]:
        status, text = self.session.get(API_ALL, allow_403=True)
        if status != 200:
            log.warning("leetcode problem list status %s", status)
            return []
        try:
            data = json.loads(text)
            pairs = data.get("stat_status_pairs", [])
        except Exception:
            return []
        tags_map = self._topic_map()
        out: list[dict] = []
        total = len(pairs)
        for i, p in enumerate(pairs):
            st = p.get("stat", {})
            slug = st.get("question__title_slug")
            if not slug:
                continue
            lvl = (p.get("difficulty") or {}).get("level")
            out.append({
                "source": self.source,
                "source_id": slug,
                "title": st.get("question__title") or slug,
                "difficulty": {1: "easy", 2: "medium", 3: "hard"}.get(lvl, "unrated"),
                "rating": lvl,
                "tags": tags_map.get(st.get("question_id"), []),
                "url": f"https://leetcode.com/problems/{slug}/",
                "status": "pending",
                "paid_only": bool(p.get("paid_only")),
            })
            self._emit(progress, i + 1, total, f"leetcode metadata {i+1}/{total}")
        return out

    def _topic_map(self) -> dict:
        status, text = self.session.get(API_TAGS, allow_403=True)
        if status != 200:
            return {}
        try:
            data = json.loads(text)
        except Exception:
            return {}
        m: dict[int, list[str]] = {}
        for topic in data.get("topics", []) or []:
            for qid in topic.get("questions", []) or []:
                m.setdefault(qid, []).append(topic.get("slug", ""))
        return m

    # ------------------------------------------------------------------
    def fetch_problem_details(self, source_id: str) -> Optional[dict]:
        slug = source_id
        if source_id.startswith("http"):
            m = re.search(r"/problems/([a-z0-9\-]+)/?", source_id)
            slug = m.group(1) if m else source_id
        if "leetcode-cn.com" in source_id:
            return {"source_id": slug, "status": "failed", "last_error": "leetcode-cn not supported; use leetcode.com"}
        data = self._graphql(_Q_QUESTION, {"titleSlug": slug})
        if not data:
            return None
        q = (data.get("data") or {}).get("question")
        if not q:
            return None
        content = q.get("content") or ""
        samples = _extract_samples_from_content(content) or \
            _parse_examples(q.get("exampleTestcaseList") or [])
        return {
            "source": self.source,
            "source_id": slug,
            "title": q.get("title") or slug,
            "difficulty": q.get("difficulty", "").lower(),
            "rating": {"easy": 1, "medium": 2, "hard": 3}.get(q.get("difficulty", "").lower()),
            "statement": _lc_statement_to_text(content),
            "samples": samples,
            "starter_py": _starter(q, "python3"),
            "starter_cpp": _starter(q, "cpp"),
            "tags": [t.get("slug") for t in (q.get("topicTags") or []) if t.get("slug")],
            "url": f"https://leetcode.com/problems/{slug}/",
            "time_limit_ms": None,
            "memory_limit_mb": None,
            "meta": q.get("metaData"),
            "status": "fetched",
            "last_error": None,
        }

    # ------------------------------------------------------------------
    def problems_for_contest(self, source_id: str, gym: bool = False) -> Optional[tuple[dict, list]]:
        data = self._graphql(_Q_CONTESTS, {})
        contests = ((data or {}).get("data") or {}).get("allContests") or []
        match = next((c for c in contests if c.get("titleSlug") == source_id), None)
        if not match:
            return None
        info = {
            "source": self.source,
            "source_id": source_id,
            "name": match["title"],
            "url": f"https://leetcode.com/contest/{source_id}/",
            "start_time": int(match.get("startTime") or 0),
            "duration": int(match.get("duration") or 5400),
        }
        problems = self._contest_problems(source_id)
        return info, problems

    def _contest_problems(self, slug: str) -> list[dict]:
        """Historically the contest questions are only visible while running /
        shortly before. Best effort; falls back to empty list."""
        q = """query contestProblems($titleSlug: String!) {
          contest(titleSlug: $titleSlug) {
            questions { titleSlug title questionFrontendId difficulty }
          }
        }"""
        data = self._graphql(q, {"titleSlug": slug})
        qs = ((data or {}).get("data") or {}).get("contest", {}).get("questions")
        if not qs:
            return []
        out: list[dict] = []
        for p in qs:
            out.append({
                "source_id": p.get("titleSlug"),
                "title": p.get("title"),
                "url": f"https://leetcode.com/problems/{p.get('titleSlug')}/",
                "difficulty": p.get("difficulty"),
            })
        return out


def _starter(q: dict, lang_slug: str) -> Optional[str]:
    for s in q.get("codeSnippets") or []:
        if s.get("langSlug") == lang_slug:
            return s.get("code")
    return None


_SAMPLE_PRE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.S)


def _extract_samples_from_content(content: str) -> list[dict]:
    """Parse LC content HTML. Modern pages use `div.example-block` with
    Input/Output spans; older pages embed samples inside `<pre>` blocks."""
    out: list[dict] = []
    if content:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, "html.parser")
            for block in soup.select("div.example-block"):
                inp, exp = "", ""
                for strong in block.find_all("strong"):
                    label = (strong.get_text(" ", strip=True) or "").lower()
                    text = _collect_text_after(strong)
                    if label.startswith("input"):
                        inp = text
                    elif label.startswith("output"):
                        exp = text
                if inp or exp:
                    out.append({"input": inp, "output": exp, "explanation": ""})
        except Exception:
            out = []
    if not out:
        out = _extract_samples_legacy(content or "")
    # dedupe (content may repeat examples)
    seen: set = set()
    uniq: list[dict] = []
    for s in out:
        key = (s["input"], s["output"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    return uniq


def _collect_text_after(node) -> str:
    """Concatenate the text right after a <strong> label up to the next
    <strong> (handles <span class=example-io> and plain text alike)."""
    parts: list[str] = []
    nxt = node.next_sibling
    while nxt is not None:
        name = getattr(nxt, "name", None)
        if name == "strong":
            break
        t = " ".join(nxt.get_text(" ", strip=True).split()) if name else str(nxt)
        t = t.strip()
        if t:
            parts.append(t)
        nxt = nxt.next_sibling
    return " ".join(parts).strip()


def _extract_samples_legacy(content: str) -> list[dict]:
    out: list[dict] = []
    for m in _SAMPLE_PRE.finditer(content or ""):
        block = re.sub(r"<[^>]+>", "", m.group(1))
        # strip html entities
        import html as _h
        block = _h.unescape(block)
        im = re.search(r"Input:\s*(.*?)\s*Output:\s*(.*)", block, re.S)
        if not im:
            continue
        inp = im.group(1).strip()
        rest = im.group(2).strip()
        exp = re.split(r"\s*Explanation:\s*", rest, maxsplit=1)[0].strip()
        # LC content displays string outputs quoted: Output: "fl" -> fl
        if re.fullmatch(r'"(?:[^"\\]|\\.)*"', exp):
            import json as _json
            exp = _json.loads(exp)
        out.append({"input": inp, "output": exp, "explanation": ""})
    return out


def _parse_examples(example_list: list[str]) -> list[dict]:
    """Each element is 'input lines \\n output line(s)'. LeetCode formats:
    'nums = [2,7,11,15]\\ntarget = 9\\n[0,1]' — the last non-comment block is
    the expected output."""
    out: list[dict] = []
    for ex in example_list or []:
        lines = [ln for ln in ex.splitlines() if ln.strip()]
        if not lines:
            continue
        # separate expected output: lines like "x = ..." are inputs, the rest is output
        expected_lines: list[str] = []
        input_lines: list[str] = []
        for ln in lines:
            if re.match(r"^[a-zA-Z_][\w]*\s*=", ln):
                input_lines.append(ln)
            else:
                expected_lines.append(ln)
        # heuristic fallback: if all lines look like variables, take last as output
        if not expected_lines:
            expected_lines = [lines[-1]]
            input_lines = lines[:-1]
        inp = "\n".join(input_lines).strip()
        exp = "\n".join(expected_lines).strip()
        out.append({"input": inp, "output": exp, "explanation": ""})
    return out


def _lc_statement_to_text(content: str) -> str:
    if not content:
        return ""
    text = html_to_text(content)
    return re.sub(r"\n{3,}", "\n\n", text).strip()