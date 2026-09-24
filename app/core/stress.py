"""Stress tester: pit your fast solution against a brute-force reference.

Repeatedly generates random inputs and runs both programs, stopping at the
first disagreement so you can copy the counterexample into your custom tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from . import judge


@dataclass
class StressResult:
    ok: bool
    iterations: int
    input: str = ""
    fast_out: str = ""
    brute_out: str = ""
    error: str = ""


def run_stress(
    fast_code: str,
    brute_code: str,
    gen_code: str,
    language: str,
    iterations: int = 500,
    time_limit_ms: int = 2000,
    memory_mb: int = 256,
    progress: Optional[Callable[[int], None]] = None,
    stop_event=None,  # threading.Event-like
) -> StressResult:
    j = judge.Judge()
    try:
        for i in range(1, iterations + 1):
            if stop_event is not None and stop_event.is_set():
                return StressResult(ok=False, iterations=i - 1, error="stopped by user")
            gen = _run_one(j, gen_code, "python", "", 3000, memory_mb)
            if gen.returncode != 0:
                return StressResult(ok=False, iterations=i - 1,
                                    error=f"generator failed:\n{gen.stderr[:800]}")
            case_in = gen.stdout
            fast = _run_one(j, fast_code, language, case_in, time_limit_ms, memory_mb)
            brute = _run_one(j, brute_code, language, case_in, time_limit_ms, memory_mb)
            if fast.timed_out or brute.timed_out:
                return StressResult(ok=False, iterations=i,
                                    error="time limit exceeded "
                                          f"(fast={fast.timed_out}, brute={brute.timed_out})")
            if fast.returncode != 0 or brute.returncode != 0:
                return StressResult(
                    ok=False, iterations=i, input=case_in,
                    fast_out=fast.stdout, brute_out=brute.stdout,
                    error=f"runtime error: fast rc={fast.returncode}, "
                          f"brute rc={brute.returncode}",
                )
            same, _ = judge.compare(fast.stdout, brute.stdout, mode="exact")
            if not same:
                return StressResult(
                    ok=False, iterations=i, input=case_in,
                    fast_out=fast.stdout, brute_out=brute.stdout,
                )
            if progress:
                progress(i)
    finally:
        j.cleanup()
    return StressResult(ok=True, iterations=iterations)


def _run_one(j: judge.Judge, code: str, language, stdin_text: str,
             time_limit_ms: int, memory_mb: int) -> judge.RunResult:
    import tempfile
    from pathlib import Path
    import shutil
    sandbox = Path(tempfile.mkdtemp(prefix="stress_", dir=str(j.tmp_root)))
    try:
        if str(language).lower() in ("python", "py"):
            src = sandbox / "s.py"
            src.write_text(code, encoding="utf-8")
            return j.run(sandbox, src, judge.LANG_PY, stdin_text, time_limit_ms, memory_mb)
        src = sandbox / "s.cpp"
        src.write_text(code, encoding="utf-8")
        ok, err = j.compile(sandbox, src)
        if not ok:
            return judge.RunResult(returncode=-3, stderr=f"compilation error:\n{err[:1000]}")
        return j.run(sandbox, sandbox / "s", judge.LANG_CPP, stdin_text,
                     time_limit_ms, memory_mb)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)