# Competitive Programming Playground

A desktop (PySide6/Qt) practice environment for competitive programming with
**Python** and **C++** support. It downloads problems (with full statements and
sample tests) from **Codeforces**, **LeetCode** and **Codewars**, rates each
problem easy/medium/hard, auto-tests your code locally, refreshes problems
weekly and contests daily, and offers a full **Competition Mode** for solving
live/upcoming contests before you submit on the real site.

![screenshot](smoke.png)

## Features

### Practice
- Browse the entire problem library with filters: platform, difficulty
  (easy/medium/hard/unrated), Codeforces rating range, tags, free-text search,
  hide-solved, and fetch status.
- Every problem is rated on download:
  - Codeforces: rating ≤ 1199 easy · ≤ 1999 medium · else hard
  - LeetCode: native difficulty 1/2/3
  - Codewars: kyu ≥ 6 easy · ≥ 3 medium · else hard
- Editor with syntax highlighting + line numbers, Python and C++.
- One-click **Run all**: judge the solution against every sample test plus any
  custom tests you add (per problem, stored in SQLite). Verdicts include
  AC / WA / TLE / RE / CE / MLE with diffs and timing.
- LeetCode function-based problems are judged through an auto-generated
  harness (args are parsed from `name = value` lines read from stdin).
- Copy / export your solution; accepted submissions are harvested as
  reference solutions where the platform allows (many block bots — best effort).

### Contests (upcoming & live)
- Codeforces and LeetCode contests refreshed **daily** (interval configurable),
  with live countdown timers and phase tracking.
- One click installs a contest into Competition Mode.

### Competition Mode
- Paste any contest link
  (`codeforces.com/contest/…`, `codeforces.com/gym/…`,
  `leetcode.com/contest/<slug>/`) — everything is downloaded: contest info,
  every problem, statement and sample tests.
- Solve under a real countdown, verify locally with the same judge, then open
  the submit page on the real platform.
- Gym contests (login required) degrade gracefully: framework is installed and
  problems can be added manually by URL.

### Free Mode
- A general-purpose scratchpad: write any Python or C++ code, give it custom
  stdin, and run it with the same sandboxed engine used for judging — no
  problem or test comparison needed.
- Syntax highlighting, open/save files, insert snippets, timing + memory
  report per run.

### Tools
- **Starter templates** for Python/C++ (edit them — they are used by every
  new problem).
- **Snippet library** (insertable from the workbenches).
- **Stress tester**: fast solution vs. brute force on random inputs; the first
  mismatch is captured and can be stored as a custom test on any problem.
- **Random test generator**, **math helpers** (gcd/lcm, primes, factorization,
  modular exponentiation, combinations, fibonacci) and a **cheatsheet**.

### Background workers
- **Backfill**: statements + sample tests are fetched for every pending problem
  automatically, with per-host rate limiting (CF 2 s, LC 1.2 s, CW 1.2 s) and
  automatic resume across restarts.
- **Scheduler**: checks every 5 minutes whether contests (default 24 h) or
  problem metadata (default 7 d) are due for refresh, all configurable in
  Settings. Existing problems are never re-downloaded.

## Install & run

Requires Python ≥ 3.10 and `g++` (for C++ judging).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

Data lives in `data/playground.db` (override with `CPP_DATA_DIR`).

## Headless / CI

```bash
xvfb-run -a python3 -m app.main --smoke-test smoke.png # GUI screenshot smoke test
python3 -m app.main --headless-backfill --backfill-max 60  # console backfill
```

## Notes

- LeetCode can require a cookie-seeded session before its GraphQL endpoint
  works; the app retries and degrades gracefully.
- Codeforces submission pages are behind DDoS-Guard: harvesting is
  best-effort and marked `harvest_blocked:<contest>` in the DB when blocked.
- Nothing is guaranteed to match the official judges — you are strongly
  encouraged to submit the final solution on the real platform.