"""Fetcher base class + shared helpers."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from ..core.http import hub

log = logging.getLogger("fetchers")

Progress = Optional[Callable[[int, int, str], None]]


class Fetcher:
    source: str = "base"

    def __init__(self) -> None:
        self.host = "example.com"
        self.session = hub.for_host(self.host)

    # ---- implemented by subclasses --------------------------------------
    def refresh_contests(self, progress: Progress = None) -> list[dict]: ...  # pragma: no cover

    def refresh_metadata(self, progress: Progress = None) -> list[dict]:
        """Return a list of problem dicts (metadata only)."""

    def fetch_problem_details(self, source_id: str) -> Optional[dict]:
        """Return full problem dict (statement, samples, limits, starters)."""

    def problems_for_contest(self, source_id: str, gym: bool = False) -> Optional[tuple[dict, list]]:
        """Return (contest_info, [problem dicts]) for competition mode."""

    def harvest_solutions(self, source_id: str, max_per_problem: int = 3,
                          progress: Progress = None) -> dict:
        """Return map problems -> [{language, code, author}]. Best effort."""

    # ---- helpers -----------------------------------------------------------
    def _emit(self, progress: Progress, cur: int, total: int, msg: str) -> None:
        if progress:
            try:
                progress(cur, total, msg)
            except Exception:
                pass


def parse_seconds(value: str) -> int:
    """'2 seconds' / '1.5 s' -> ms."""
    try:
        return int(float(value.split()[0].replace(",", "")) * 1000)
    except Exception:
        return 0


def parse_megabytes(value: str) -> int:
    """'256 megabytes' / '256 MB' -> MB."""
    try:
        v = float(value.split()[0].replace(",", ""))
        if "kilo" in value.lower() or "kb" in value.lower():
            return max(1, int(v / 1024))
        return max(1, int(v))
    except Exception:
        return 0