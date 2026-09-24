"""Main window: tabs for Practice / Contests / Competition Mode / Tools /
Settings, plus the status bar with the background backfill worker and the
automatic refresh scheduler."""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QLabel, QMainWindow, QProgressBar, QTabWidget)

from .. import config, db as dbmod
from ..workers import BackfillThread, Job, pool
from .competition import CompetitionTab
from .contests import ContestsTab
from .free_mode import FreeModeTab
from .practice import PracticeTab
from .settings import (SettingsTab, contest_refresh_hours, metadata_refresh_days)
from .tools import ToolsTab

log = logging.getLogger("main_window")


class MainWindow(QMainWindow):
    def __init__(self, auto_backfill: bool = True):
        super().__init__()
        self.db = dbmod.get_db()
        self.setWindowTitle(config.APP_NAME)
        self.resize(1440, 900)

        self._backfill: BackfillThread | None = None
        self._syncing: bool = False

        self._build_tabs()
        self._build_statusbar()

        if not auto_backfill:
            return

        self._start_scheduler()
        # Give the UI a moment to paint before hitting the network.
        QTimer.singleShot(1500, self._start_backfill)
        self._scheduled_tasks()       # also run the "due" check immediately

    # ------------------------------------------------------------------
    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.practice_tab = PracticeTab()
        self.contests_tab = ContestsTab()
        self.competition_tab = CompetitionTab()
        self.free_tab = FreeModeTab()
        self.tools_tab = ToolsTab()
        self.settings_tab = SettingsTab()

        self.tabs.addTab(self.practice_tab, "Practice")
        self.tabs.addTab(self.contests_tab, "Contests")
        self.tabs.addTab(self.competition_tab, "Competition Mode")
        self.tabs.addTab(self.free_tab, "Free Mode")
        self.tabs.addTab(self.tools_tab, "Tools")
        self.tabs.addTab(self.settings_tab, "Settings")
        self.setCentralWidget(self.tabs)

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.backfill_bar = QProgressBar()
        self.backfill_bar.setRange(0, 0)          # busy indicator shape
        self.backfill_bar.setMaximumWidth(160)
        self.backfill_bar.setVisible(False)
        self.status_label = QLabel(" ready")
        sb.addWidget(self.status_label, 1)
        sb.addPermanentWidget(self.backfill_bar)

    # ------------------------------------------------------------------
    # Background backfill
    # ------------------------------------------------------------------
    def _start_backfill(self) -> None:
        if self._backfill is not None:
            return
        self.backfill_bar.setVisible(True)
        thread = BackfillThread(self)
        thread.progress.connect(self._on_backfill_progress)
        thread.finished_stats.connect(self._on_backfill_finished)
        thread.log_message.connect(log.info)
        thread.finished.connect(lambda: setattr(self, "_backfill", None))
        self._backfill = thread
        thread.start()

    def _stop_backfill(self) -> None:
        if self._backfill is not None:
            self._backfill.request_stop()

    def _on_backfill_progress(self, cur: int, total: int, msg: str) -> None:
        self.status_label.setText(f" {msg}" if msg else " backfilling…")

    def _on_backfill_finished(self, stats) -> None:
        self.backfill_bar.setVisible(False)
        self.status_label.setText(
            f" backfill finished — {stats.get('done', 0)} detailed, "
            f"{stats.get('failed', 0)} failed")

    # ------------------------------------------------------------------
    # Automatic refresh scheduler (check every 5 minutes)
    # ------------------------------------------------------------------
    def _start_scheduler(self) -> None:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._scheduled_tasks)
        self._timer.start(5 * 60 * 1000)

    @staticmethod
    def _due(last_key: str, refresh_seconds: int) -> bool:
        last = MainWindow._meta_int(last_key)
        return not last or (time.time() - last) > refresh_seconds

    @staticmethod
    def _meta_int(key: str):
        try:
            return int(dbmod.get_db().get_meta(key))
        except (TypeError, ValueError):
            return 0

    def _scheduled_tasks(self) -> None:
        if self._syncing:
            return
        try:
            hours = contest_refresh_hours(self.db)
            days = metadata_refresh_days(self.db)
        except Exception:
            hours, days = config.CONTEST_REFRESH_HOURS, config.METADATA_REFRESH_DAYS
        if self._due("last_contest_refresh", hours * 3600):
            self._sync("contests")
        elif self._due("last_metadata_refresh", days * 86400):
            self._sync("metadata")

    def _sync(self, what: str) -> None:
        from ..services import sync as sync_mod
        self._syncing = True
        self.status_label.setText(f" {what} refresh: running…")
        fn = sync_mod.refresh_contests if what == "contests" else sync_mod.refresh_metadata
        job = Job(fn)
        job.signals.done.connect(self._on_synced(what))
        job.signals.error.connect(self._on_sync_error(what))
        pool().start(job)

    def _on_synced(self, what: str):
        def _done(stats) -> None:
            self._syncing = False
            if what == "contests":
                counts = stats or {}
                self.status_label.setText(
                    f" contests refreshed (cf {counts.get('codeforces', 0)}, "
                    f"lc {counts.get('leetcode', 0)})")
            else:
                self.status_label.setText(
                    f" metadata refreshed — {stats.get('new', 0)} new problems")
                if stats.get("new", 0):
                    self._start_backfill()
        return _done

    def _on_sync_error(self, what: str):
        def _err(msg: str) -> None:
            self._syncing = False
            log.warning("%s refresh failed: %s", what, msg)
            self.status_label.setText(f" {what} refresh failed: {msg[:80]}")
        return _err

    # ------------------------------------------------------------------
    # Cross-tab wiring: Contests -> Competition Mode
    # ------------------------------------------------------------------
    def install_competition_url(self, url: str) -> None:
        self.tabs.setCurrentWidget(self.competition_tab)
        self.competition_tab.install_competition_url(url)

    # ------------------------------------------------------------------
    def closeEvent(self, event):  # noqa: N802
        self._stop_backfill()
        if self._backfill is not None:
            self._backfill.wait(5000)
        super().closeEvent(event)