"""Difficulty classification helpers.

Ratings are mapped into easy / medium / hard so every problem (from any
source) can be filtered uniformly. Mapping rules in config.py.
"""
from __future__ import annotations

from .. import config


def cf_rating_to_level(rating: int | None) -> str:
    if not rating:
        return "unrated"
    if rating <= config.CF_EASY_RATING_MAX:
        return "easy"
    if rating <= config.CF_MEDIUM_RATING_MAX:
        return "medium"
    return "hard"


def cf_level_range(level: str) -> tuple[int | None, int | None]:
    """Return (min_rating, max_rating) for a level, for filtering."""
    if level == "easy":
        return None, config.CF_EASY_RATING_MAX
    if level == "medium":
        return config.CF_EASY_RATING_MAX + 1, config.CF_MEDIUM_RATING_MAX
    if level == "hard":
        return config.CF_MEDIUM_RATING_MAX + 1, None
    return None, None


def codewars_kyu_to_level(kyu: int | None) -> str:
    """Codewars rank: 8 kyu = easiest ... 1 kyu = hardest, then dan ranks."""
    if not kyu:
        return "unrated"
    if kyu >= config.CW_EASY_KYU_MIN:          # 6,7,8
        return "easy"
    if kyu >= config.CW_MEDIUM_KYU_MIN:        # 3,4,5
        return "medium"
    return "hard"                              # 1,2 kyu + dan


def level_from_any(source: str, rating: int | None) -> str:
    if source == "leetcode":
        return {1: "easy", 2: "medium", 3: "hard"}.get(rating, "unrated")
    if source == "codewars":
        return codewars_kyu_to_level(rating)
    return cf_rating_to_level(rating)


def kyu_to_stars(kyu: int | None) -> str:
    if not kyu:
        return "?"
    if kyu >= 8:
        return "★"
    if kyu >= 7:
        return "★★"
    if kyu >= 6:
        return "★★★"
    if kyu >= 4:
        return "★★★★"
    if kyu >= 2:
        return "★★★★★"
    return "★★★★★★"