"""Local judge: compile, run, and compare Python / C++ solutions.

Runs submissions in an isolated temp directory with CPU / memory limits
(linux resource module) and returns per-test verdicts + diffs, mirroring
how Codeforces-style judges work.
"""
from __future__ import annotations

import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .. import config

PYTHON = sys.executable or "python3"
CXX_BIN = os.environ.get("CXX", "g++")
CXX_FLAGS = ["-std=c++20", "-O2", "-pipe", "-DONLINE_JUDGE"]

AC, WA, TLE, RE, CE, MLE, SKIP = "AC", "WA", "TLE", "RE", "CE", "MLE", "SKIP"

MAX_OUTPUT_CHARS = 4000

LANG_PY, LANG_CPP = "Python", "C++"


@dataclass
class RunResult:
    returncode: int = -1
    stdout: str = ""
    stderr: str = ""
    time_ms: float = 0.0
    memory_kb: int = 0
    timed_out: bool = False
    memory_exceeded: bool = False
    signal: int = 0


@dataclass
class TestResult:
    name: str
    verdict: str = WA
    input: str = ""
    expected: str = ""
    got: str = ""
    time_ms: float = 0.0
    memory_kb: int = 0
    diff: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name, "verdict": self.verdict, "input": self.input,
            "expected": self.expected, "got": self.got,
            "time_ms": round(self.time_ms, 1), "memory_kb": self.memory_kb,
            "diff": self.diff,
        }


def _limit_setter(time_limit_ms: int, memory_mb: int, is_python: bool) -> callable:
    cpu_sec = max(1, int(time_limit_ms / 1000))
    mem_bytes = memory_mb * 1024 * 1024
    if is_python:
        mem_bytes = max(mem_bytes, 480 * 1024 * 1024)   # interpreter headroom

    def _set() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_sec, cpu_sec + 1))
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024,) * 2)
        os.umask(0o077)

    return _set


def _read_maxrss_kb() -> int:
    try:
        return int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    except Exception:
        return 0


class Judge:
    def __init__(self, tmp_root: Path | None = None):
        self.tmp_root = Path(tmp_root) if tmp_root else Path(tempfile.mkdtemp(prefix="cp_judge_"))
        self.tmp_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def _make_sandbox(self, code: str, language: str) -> tuple[Path, Path]:
        sandbox = Path(tempfile.mkdtemp(prefix="sb_", dir=str(self.tmp_root)))
        if language == LANG_PY:
            src = sandbox / "solution.py"
            src.write_text(code, encoding="utf-8")
            run_target = src
        else:
            src = sandbox / "solution.cpp"
            src.write_text(code, encoding="utf-8")
            run_target = sandbox / "solution"
        return sandbox, run_target

    def compile(self, sandbox: Path, src: Path) -> tuple[bool, str]:
        cmd = [CXX_BIN, *CXX_FLAGS, "-o", str(sandbox / "solution"), str(src)]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except Exception as exc:
            return False, f"failed to launch compiler: {exc}"
        if p.returncode != 0:
            return False, p.stderr.strip() or p.stdout.strip() or "compilation failed"
        return True, ""

    def run(self, sandbox: Path, target: Path, language: str, stdin_text: str,
            time_limit_ms: int, memory_mb: int, storage_limit_mb: int = 64) -> RunResult:
        before_rss = _read_maxrss_kb()
        is_python = language == LANG_PY
        cmd = [str(target)] if not is_python else [PYTHON, str(target)]
        timeout_wall = time_limit_ms / 1000 + 3.0
        res = RunResult()
        try:
            start = time.monotonic()
            p = subprocess.run(
                cmd,
                input=stdin_text,
                capture_output=True,
                text=True,
                cwd=str(sandbox),
                timeout=timeout_wall,
                preexec_fn=_limit_setter(time_limit_ms, memory_mb, is_python),
                errors="replace",
            )
            res.time_ms = (time.monotonic() - start) * 1000
            res.returncode = p.returncode
            res.stdout = _cap(p.stdout)
            res.stderr = _cap(p.stderr)
        except subprocess.TimeoutExpired as exc:
            res.timed_out = True
            res.stdout = _cap(exc.stdout or "")
            res.stderr = _cap(exc.stderr or "")
        except OSError as exc:
            res.returncode = -2
            res.stderr = _cap(str(exc))
        # memory: max rss seen across all children (cumulative max)
        res.memory_kb = max(0, _read_maxrss_kb() - before_rss)
        if res.timed_out or res.returncode == -24:   # -24 = SIGXCPU (CPU limit hit)
            res.timed_out = True
            res.returncode = -10
        return res

    # ------------------------------------------------------------------
    def judge_code(self, code: str, language: str, tests: list[dict],
                   time_limit_ms: int, memory_mb: int,
                   compare_mode: str = config.COMPARE_MODE,
                   tolerance: float = config.FLOAT_TOLERANCE) -> list[TestResult]:
        if language not in (LANG_PY, LANG_CPP):
            return [TestResult(name="config", verdict=CE, diff="unsupported language")]
        sandbox, target = self._make_sandbox(code, language)
        results: list[TestResult] = []
        try:
            if language == LANG_CPP:
                ok, err = self.compile(sandbox, sandbox / "solution.cpp")
                if not ok:
                    return [_ce_result("compilation", err)]
            for idx, t in enumerate(tests or []):
                name = t.get("name", f"test {idx + 1}")
                r = self.run(sandbox, target, language,
                             t.get("input", ""), time_limit_ms, memory_mb)
                tr = TestResult(
                    name=name, input=t.get("input", ""),
                    expected=t.get("expected", ""), got=r.stdout,
                    time_ms=r.time_ms, memory_kb=r.memory_kb,
                )
                if r.timed_out:
                    tr.verdict = TLE
                    tr.diff = f"time limit exceeded ({time_limit_ms} ms)"
                elif r.memory_exceeded:
                    tr.verdict = MLE
                    tr.diff = f"memory limit exceeded ({memory_mb} MB)"
                elif r.returncode != 0:
                    tr.verdict = RE
                    sig = f" (signal {r.signal})" if r.signal else ""
                    tr.diff = (f"runtime error, exit code {r.returncode}{sig}\n"
                               f"stderr:\n{r.stderr[:1500] or '(empty)'}")
                else:
                    ok, diff = compare(r.stdout, t.get("expected", ""),
                                       mode=compare_mode, tolerance=tolerance)
                    tr.verdict = AC if ok else WA
                    tr.diff = diff
                results.append(tr)
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)
        return results

    def cleanup(self) -> None:
        shutil.rmtree(self.tmp_root, ignore_errors=True)


def run_standalone(code: str, language: str, stdin_text: str = "",
                   time_limit_ms: int = config.DEFAULT_TIME_LIMIT_MS,
                   memory_mb: int = config.DEFAULT_MEMORY_LIMIT_MB) -> RunResult:
    """Free-run: compile (if C++) and execute `code` with the given stdin,
    returning a RunResult — no judging, no comparison. Used by Free Mode."""
    if language not in (LANG_PY, LANG_CPP):
        return RunResult(returncode=-3, stderr=f"unsupported language: {language}")
    j = Judge()
    try:
        sandbox, target = j._make_sandbox(code, language)
        if language == LANG_CPP:
            ok, err = j.compile(sandbox, sandbox / "solution.cpp")
            if not ok:
                return RunResult(returncode=-3,
                                 stderr=f"compilation error:\n{err[:2000]}")
        return j.run(sandbox, target, language, stdin_text or "",
                     int(time_limit_ms), int(memory_mb))
    finally:
        j.cleanup()


def _ce_result(name: str, err: str) -> TestResult:
    return TestResult(name=name, verdict=CE, diff=err[:4000])


def _cap(s: str) -> str:
    if len(s) > MAX_OUTPUT_CHARS:
        return s[:MAX_OUTPUT_CHARS] + "\n… [output truncated]"
    return s


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
_NUM_RE = r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$"


def _is_number(tok: str) -> bool:
    import re
    return bool(re.match(_NUM_RE, tok))


def compare(actual: str, expected: str, mode: str = "tokens",
            tolerance: float = 1e-6) -> tuple[bool, str]:
    """Return (ok, human readable diff)."""
    if mode == "exact":
        a_lines = _normalize_lines(actual)
        e_lines = _normalize_lines(expected)
        if a_lines == e_lines:
            return True, ""
        return False, _line_diff(e_lines, a_lines)

    # tokens / numeric modes
    a_toks = actual.split() if mode == "tokens" else [
        t for t in actual.split() if _is_number(t)]
    e_toks = expected.split() if mode == "tokens" else [
        t for t in expected.split() if _is_number(t)]
    if mode == "numeric":
        e_toks = [t for t in e_toks if _is_number(t)]
    if len(a_toks) != len(e_toks):
        return False, (f"token count mismatch: expected {len(e_toks)}, got {len(a_toks)}\n"
                       f"expected: {_preview(expected)}\n"
                       f"got:      {_preview(actual)}")
    bad: list[tuple[str, str]] = []
    for i, (a, e) in enumerate(zip(a_toks, e_toks)):
        if a == e:
            continue
        if _is_number(a) and _is_number(e):
            if _close_enough(float(a), float(e), tolerance):
                continue
        bad.append((e, a))
        if len(bad) >= 5:
            break
    if not bad:
        return True, ""
    lines = [f"mismatch at token {i}: expected {e!r}, got {a!r}" for i, (e, a) in enumerate(bad)]
    return False, "\n".join(lines) + "\nexpected: " + _preview(expected) + "\ngot:      " + _preview(actual)


def _close_enough(a: float, b: float, rel: float) -> bool:
    if a == b:
        return True
    return abs(a - b) <= rel * max(abs(a), abs(b)) + 1e-12


def _normalize_lines(s: str) -> list[str]:
    lines = [ln.rstrip() for ln in s.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    return lines


def _preview(s: str, n: int = 200) -> str:
    s = s.replace("\n", "⏎ ")
    return s[:n] + ("…" if len(s) > n else "")


def _line_diff(expected: list[str], actual: list[str]) -> str:
    n = max(len(expected), len(actual))
    out: list[str] = []
    for i in range(n):
        e = expected[i] if i < len(expected) else "<missing>"
        a = actual[i] if i < len(actual) else "<missing>"
        if e != a:
            out.append(f"line {i}: expected {e!r}  got {a!r}")
            if len(out) >= 8:
                out.append("…")
                break
    return "\n".join(out) or "output differs"


def verdict_summary(results: list[TestResult]) -> str:
    if not results:
        return "no tests"
    counts: dict[str, int] = {}
    for r in results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    best = AC if counts.get(AC) == len(results) else max(counts, key=lambda k: (counts[k], k))
    parts = " ".join(f"{k}:{v}" for k, v in sorted(counts.items()))
    return f"{best}  ({parts})", best == AC