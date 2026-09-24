"""Application entry point.

Usage:
    python3 -m app.main                 # launch the GUI
    python3 -m app.main --smoke-test [out.png]
    python3 -m app.main --headless-backfill [--backfill-max N]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys


def _parse_args(argv) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Competitive Programming Playground")
    p.add_argument("--smoke-test", nargs="?", const="smoke.png", default=None,
                   metavar="PNG",
                   help="Open the window headlessly, save a screenshot, exit.")
    p.add_argument("--headless-backfill", action="store_true",
                   help="Refresh metadata/contests then backfill without opening a window.")
    p.add_argument("--backfill-max", type=int, default=60,
                   help="Problems to backfill in headless mode (default 60).")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p.parse_args(argv)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def _run_headless(args) -> int:
    """Console-only run: refresh contests + metadata, backfill N problems."""
    from . import db as dbmod
    from .services import sync

    db = dbmod.get_db()
    print("== refreshing contests ==", flush=True)
    counts = sync.refresh_contests()
    print(f"contests: {counts}", flush=True)
    print("== refreshing metadata ==", flush=True)
    stats = sync.refresh_metadata()
    print(f"metadata: new={stats.get('new')} per-source={stats.get('sources')}", flush=True)
    print(f"== backfilling up to {args.backfill_max} problems ==", flush=True)

    def cb(cur, total, msg):
        print(f"  {msg}", flush=True)

    res = sync.run_backfill(lambda: False, cb, max_problems=args.backfill_max)
    print(f"backfill: {res}", flush=True)
    print(f"total problems in db: {db.count_problems()}", flush=True)
    return 0


def _run_gui(args) -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .ui.main_window import MainWindow

    QApplication.setApplicationName("cpplayground")
    app = QApplication(sys.argv)
    window = MainWindow(auto_backfill=not args.smoke_test)
    window.show()

    if args.smoke_test:
        from PySide6.QtCore import QTimer as _T

        def _shot() -> None:
            path = args.smoke_test
            window.grab().save(path)
            print(f"screenshot saved to {path}", flush=True)
            app.quit()

        _T.singleShot(4000, _shot)

    return app.exec()


def main(argv=None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    _setup_logging(args.verbose)
    if args.headless_backfill:
        return _run_headless(args)
    if args.smoke_test and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        # allow explicit platform override (e.g. xvfb-run supplies DISPLAY)
        pass
    return _run_gui(args)


if __name__ == "__main__":
    sys.exit(main())