"""SQLite storage layer for the playground."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS problems (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,              -- codeforces | leetcode | codewars
    source_id     TEXT NOT NULL,              -- "1234/A" | "two-sum" | kata slug
    contest_id    TEXT,                       -- CF contest id / LC contest slug
    index_code    TEXT,                       -- problem letter inside contest
    title         TEXT NOT NULL,
    difficulty    TEXT,                       -- easy | medium | hard | unrated
    rating        INTEGER,                    -- CF rating / LC level / CW kyu
    statement     TEXT,                       -- HTML (CF/LC) or markdown (CW)
    starter_py    TEXT,
    starter_cpp   TEXT,
    samples       TEXT,                       -- JSON [{"input","output","explanation"}]
    tags          TEXT,                       -- JSON [..]
    url           TEXT,
    time_limit_ms INTEGER,
    memory_limit_mb INTEGER,
    meta          TEXT,                      -- JSON (LC metaData / extra hints)
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending|fetched|failed|locked
    fetched_at    TEXT,
    last_error    TEXT,
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS solutions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    source     TEXT NOT NULL,                 -- codeforces | codewars
    language   TEXT NOT NULL,
    code       TEXT NOT NULL,
    author     TEXT,
    extra      TEXT,                          -- JSON (votes, verdict, ranking...)
    fetched_at TEXT,
    UNIQUE (problem_id, source, language, code)
);

CREATE TABLE IF NOT EXISTS contests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    source_id    TEXT NOT NULL,               -- CF contest id / LC contest slug
    name         TEXT NOT NULL,
    url          TEXT,
    start_time   INTEGER,                     -- unix seconds
    duration     INTEGER,                     -- seconds
    phase        TEXT NOT NULL,               -- planned | started | finished
    is_gym       INTEGER DEFAULT 0,
    last_check   INTEGER,
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS competitions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    source      TEXT NOT NULL,
    url         TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    start_time  INTEGER,
    duration    INTEGER,
    created_at  INTEGER,
    UNIQUE (source, url)
);

CREATE TABLE IF NOT EXISTS competition_problems (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    competition_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
    source_id     TEXT NOT NULL,              -- contest problem id ("1234/A") or LC slug
    title         TEXT NOT NULL,
    url           TEXT,
    problem_id    INTEGER REFERENCES problems(id) ON DELETE SET NULL,
    UNIQUE (competition_id, source_id)
);

CREATE TABLE IF NOT EXISTS my_submissions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id INTEGER REFERENCES problems(id) ON DELETE SET NULL,
    competition_problem_id INTEGER REFERENCES competition_problems(id) ON DELETE SET NULL,
    language   TEXT NOT NULL,
    code       TEXT NOT NULL,
    verdict    TEXT NOT NULL,                 -- AC | WA | TLE | RE | CE | NONE
    time_ms    REAL,
    memory_kb  INTEGER,
    detail     TEXT,                          -- JSON per-test results
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS custom_tests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    name       TEXT DEFAULT 'custom',
    input      TEXT,
    expected   TEXT
);

CREATE TABLE IF NOT EXISTS snippets (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    language TEXT NOT NULL,                   -- python | cpp | both
    content  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_INSERT_SQL = {
    "problem": """
        INSERT OR IGNORE INTO problems
        (source, source_id, contest_id, index_code, title, difficulty, rating,
         statement, starter_py, starter_cpp, samples, tags, url,
         time_limit_ms, memory_limit_mb, meta, status, fetched_at, last_error)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """,
    "contest": """
        INSERT OR IGNORE INTO contests (source, source_id, name, url, start_time,
                                        duration, phase, is_gym, last_check)
        VALUES (?,?,?,?,?,?,?,?,?)
    """,
}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Database:
    """Thread-safe wrapper around a single sqlite connection pool."""

    _local: threading.local

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config.DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._local = threading.local()
        self._init()

    # -- connection handling -----------------------------------------------
    def _init(self) -> None:
        conn = self._raw_conn()
        conn.executescript(SCHEMA)
        # lightweight migrations for tables created by earlier versions
        for sql in (
            "ALTER TABLE competition_problems ADD COLUMN problem_id INTEGER REFERENCES problems(id) ON DELETE SET NULL",
            "ALTER TABLE problems ADD COLUMN meta TEXT",
        ):
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass
        conn.commit()

    def _raw_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), timeout=60)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._raw_conn()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, tuple(params))
        return cur

    def commit(self) -> None:
        self.conn.commit()

    # -- meta ---------------------------------------------------------------
    def set_meta(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.commit()

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    # -- problems ------------------------------------------------------------
    def upsert_problem(self, p: dict) -> int:
        """Insert-or-ignore a problem dict; returns its row id (new or existing)."""
        with self._lock:
            self.execute(
                _INSERT_SQL["problem"],
                (
                    p["source"], p["source_id"], p.get("contest_id"),
                    p.get("index_code"), p["title"], p.get("difficulty", "unrated"),
                    p.get("rating"), p.get("statement"), p.get("starter_py"),
                    p.get("starter_cpp"),
                    json.dumps(p.get("samples") or []),
                    json.dumps(p.get("tags") or []),
                    p.get("url"), p.get("time_limit_ms"), p.get("memory_limit_mb"),
                    p.get("meta"),
                    p.get("status", "pending"), p.get("fetched_at"), p.get("last_error"),
                ),
            )
            self.commit()
            row = self.execute(
                "SELECT id FROM problems WHERE source=? AND source_id=?",
                (p["source"], p["source_id"]),
            ).fetchone()
            return row["id"]

    def update_problem(self, pid: int, **fields: Any) -> None:
        allowed = {
            "statement", "starter_py", "starter_cpp", "samples", "difficulty",
            "rating", "tags", "url", "time_limit_ms", "memory_limit_mb", "meta",
            "status", "fetched_at", "last_error",
        }
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k}=?")
            vals.append(json.dumps(v) if k in ("samples", "tags") and not isinstance(v, str)
                        else v)
        sets.append("fetched_at=?")
        vals.append(_now())
        vals.append(pid)
        self.execute(f"UPDATE problems SET {', '.join(sets)} WHERE id=?", vals)
        self.commit()

    def problems(self, source: Optional[str] = None, difficulty: Optional[str] = None,
                 rating_min: Optional[int] = None, rating_max: Optional[int] = None,
                 search: str = "", tag: str = "", hide_fetched_only: bool = False,
                 status: Optional[str] = None, limit: int = 2000) -> list:
        q = ["SELECT p.*, (SELECT COUNT(*) FROM my_submissions s "
             " WHERE s.problem_id=p.id AND s.verdict='AC') as solved_ac "
             " FROM problems p WHERE 1=1"]
        args: list = []
        if source:
            q.append("AND p.source=?")
            args.append(source)
        if difficulty and difficulty != "all":
            q.append("AND p.difficulty=?")
            args.append(difficulty)
        if rating_min is not None:
            q.append("AND (p.rating IS NOT NULL AND p.rating>=?)")
            args.append(rating_min)
        if rating_max is not None:
            q.append("AND (p.rating IS NULL OR p.rating<=?)")
            args.append(rating_max)
        if search:
            q.append("AND (p.title LIKE ? OR p.source_id LIKE ? OR p.tags LIKE ?)")
            like = f"%{search}%"
            args += [like, like, like]
        if tag:
            q.append("AND p.tags LIKE ?")
            args.append(f'%"{tag}"%')
        if status:
            q.append("AND p.status=?")
            args.append(status)
        q.append("ORDER BY p.id DESC LIMIT ?")
        args.append(limit)
        return [dict(r) for r in self.execute(" ".join(q), args).fetchall()]

    def problem_by_id(self, pid: int) -> Optional[dict]:
        r = self.execute("SELECT * FROM problems WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None

    def problem_by_source(self, source: str, source_id: str) -> Optional[dict]:
        r = self.execute(
            "SELECT * FROM problems WHERE source=? AND source_id=?",
            (source, source_id),
        ).fetchone()
        return dict(r) if r else None

    def pending_problems(self, limit: int = 100) -> list:
        rows = self.execute(
            "SELECT * FROM problems WHERE status='pending' AND "
            "(last_error IS NULL OR last_error NOT LIKE 'ratelimit%') "
            "ORDER BY id LIMIT ?", (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_problems(self) -> int:
        return self.execute("SELECT COUNT(*) c FROM problems").fetchone()["c"]

    def stats(self) -> dict:
        row = self.execute(
            """SELECT
                 COUNT(*) AS total,
                 SUM(status='pending') AS pending,
                 SUM(status='fetched') AS fetched,
                 SUM(status='failed') AS failed,
                 SUM(difficulty='easy') AS easy,
                 SUM(difficulty='medium') AS medium,
                 SUM(difficulty='hard') AS hard
               FROM problems"""
        ).fetchone()
        return dict(row)

    # -- solutions ------------------------------------------------------------
    def upsert_solution(self, problem_id: int, source: str, language: str,
                        code: str, author: str = "", extra: Optional[dict] = None) -> None:
        self.execute(
            "INSERT OR IGNORE INTO solutions (problem_id, source, language, code, "
            "author, extra, fetched_at) VALUES (?,?,?,?,?,?,?)",
            (problem_id, source, language, code, author,
             json.dumps(extra or {}), _now()),
        )
        self.commit()

    def solutions_for(self, problem_id: int, source: Optional[str] = None) -> list:
        q = "SELECT * FROM solutions WHERE problem_id=?"
        args: list = [problem_id]
        if source:
            q += " AND source=?"
            args.append(source)
        q += " ORDER BY id"
        return [dict(r) for r in self.execute(q, args).fetchall()]

    # -- contests --------------------------------------------------------------
    def upsert_contest(self, c: dict) -> None:
        self.execute(
            _INSERT_SQL["contest"],
            (c["source"], c["source_id"], c["name"], c.get("url"),
             c.get("start_time"), c.get("duration"), c["phase"],
             int(c.get("is_gym", 0)), int(time.time())),
        )
        self.commit()

    def contests(self, phase: Optional[str] = None, source: Optional[str] = None) -> list:
        q = ["SELECT * FROM contests WHERE 1=1"]
        args: list = []
        if phase:
            q.append("AND phase=?")
            args.append(phase)
        if source:
            q.append("AND source=?")
            args.append(source)
        q.append("ORDER BY start_time")
        return [dict(r) for r in self.execute(" ".join(q), args).fetchall()]

    # -- competitions ------------------------------------------------------------
    def upsert_competition(self, comp: dict) -> int:
        self.execute(
            """INSERT OR IGNORE INTO competitions
               (name, source, url, source_id, start_time, duration, created_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(source, url) DO UPDATE SET
                 name=excluded.name, start_time=excluded.start_time,
                 duration=excluded.duration""",
            (comp["name"], comp["source"], comp["url"], comp["source_id"],
             comp.get("start_time"), comp.get("duration"), int(time.time())),
        )
        self.commit()
        r = self.execute(
            "SELECT id FROM competitions WHERE source=? AND url=?",
            (comp["source"], comp["url"]),
        ).fetchone()
        return r["id"]

    def competitions(self) -> list:
        rows = self.execute(
            "SELECT * FROM competitions ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def competition(self, cid: int) -> Optional[dict]:
        r = self.execute("SELECT * FROM competitions WHERE id=?", (cid,)).fetchone()
        return dict(r) if r else None

    def add_competition_problem(self, cid: int, source_id: str, title: str,
                                url: str) -> int:
        self.execute(
            "INSERT OR IGNORE INTO competition_problems "
            "(competition_id, source_id, title, url) VALUES (?,?,?,?)",
            (cid, source_id, title, url),
        )
        self.commit()
        r = self.execute(
            "SELECT id FROM competition_problems WHERE competition_id=? AND source_id=?",
            (cid, source_id),
        ).fetchone()
        return r["id"]

    def competition_problems(self, cid: int) -> list:
        rows = self.execute(
            "SELECT * FROM competition_problems WHERE competition_id=? ORDER BY id",
            (cid,),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- submissions / custom tests ---------------------------------------------
    def record_submission(self, problem_id: Optional[int],
                          competition_problem_id: Optional[int], language: str,
                          code: str, verdict: str, time_ms: Optional[float],
                          memory_kb: Optional[int], detail: Optional[dict]) -> int:
        cur = self.execute(
            "INSERT INTO my_submissions (problem_id, competition_problem_id, language, "
            "code, verdict, time_ms, memory_kb, detail, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (problem_id, competition_problem_id, language, code, verdict, time_ms,
             memory_kb, json.dumps(detail or {}), int(time.time())),
        )
        self.commit()
        return cur.lastrowid

    def submissions_for(self, problem_id: Optional[int] = None,
                        competition_problem_id: Optional[int] = None,
                        limit: int = 100) -> list:
        q = ["SELECT * FROM my_submissions WHERE 1=1"]
        args: list = []
        if problem_id is not None:
            q.append("AND problem_id=?")
            args.append(problem_id)
        if competition_problem_id is not None:
            q.append("AND competition_problem_id=?")
            args.append(competition_problem_id)
        q.append("ORDER BY id DESC LIMIT ?")
        args.append(limit)
        return [dict(r) for r in self.execute(" ".join(q), args).fetchall()]

    def solved_problem_ids(self) -> set:
        rows = self.execute(
            "SELECT DISTINCT problem_id FROM my_submissions WHERE verdict='AC' "
            "AND problem_id IS NOT NULL"
        ).fetchall()
        return {r["problem_id"] for r in rows}

    def add_custom_test(self, problem_id: int, name: str, input_: str,
                        expected: str) -> int:
        cur = self.execute(
            "INSERT INTO custom_tests (problem_id, name, input, expected) VALUES (?,?,?,?)",
            (problem_id, name, input_, expected),
        )
        self.commit()
        return cur.lastrowid

    def delete_custom_test(self, test_id: int) -> None:
        self.execute("DELETE FROM custom_tests WHERE id=?", (test_id,))
        self.commit()

    def custom_tests(self, problem_id: int) -> list:
        return [dict(r) for r in self.execute(
            "SELECT * FROM custom_tests WHERE problem_id=? ORDER BY id",
            (problem_id,)).fetchall()]

    # -- snippets ---------------------------------------------------------------
    def upsert_snippet(self, name: str, language: str, content: str) -> None:
        self.execute(
            "INSERT OR IGNORE INTO snippets (name, language, content) VALUES (?,?,?)",
            (name, language, content),
        )
        self.commit()

    def snippets(self, language: Optional[str] = None) -> list:
        q = "SELECT * FROM snippets"
        args: list = []
        if language:
            q += " WHERE language=? OR language='both'"
            args.append(language)
        q += " ORDER BY name"
        return [dict(r) for r in self.execute(q, args).fetchall()]

    def delete_snippet(self, sid: int) -> None:
        self.execute("DELETE FROM snippets WHERE id=?", (sid,))
        self.commit()


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db