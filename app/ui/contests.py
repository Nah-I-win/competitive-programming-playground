"""Contests tab: upcoming & live contests refreshed daily, with countdowns
and one-click installation into Competition Mode."""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import db as dbmod
from ..core.util import fmt_countdown, fmt_dt
from ..services import sync
from ..workers import Job, pool


class ContestsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = dbmod.get_db()
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self.refresh_table()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        bar = QHBoxLayout()
        self.phase_combo = QComboBox()
        for value, label in (("all", "all contests"), ("planned", "upcoming"),
                             ("started", "running now"), ("finished", "finished")):
            self.phase_combo.addItem(label, value)
        self.src_combo = QComboBox()
        for value, label in (("all", "all sources"), ("codeforces", "Codeforces"),
                             ("leetcode", "LeetCode")):
            self.src_combo.addItem(label, value)
        self.btn_refresh = QPushButton("🔄 Refresh now")
        self.btn_open = QPushButton("⚡ Install selected in Competition Mode")
        self.note = QLabel("Contests refresh automatically once per day.")
        self.note.setStyleSheet("color:#9aa0ad;")
        bar.addWidget(self.phase_combo)
        bar.addWidget(self.src_combo)
        bar.addWidget(self.btn_refresh)
        bar.addWidget(self.btn_open)
        bar.addStretch(1)
        bar.addWidget(self.note)
        root.addLayout(bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["", "Name", "Source", "Starts", "Duration", "Countdown"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet(open_table_style())
        root.addWidget(self.table, 1)

        self.phase_combo.currentIndexChanged.connect(self.refresh_table)
        self.src_combo.currentIndexChanged.connect(self.refresh_table)
        self.btn_refresh.clicked.connect(self.refresh_now)
        self.btn_open.clicked.connect(self.install_selected)

    # ------------------------------------------------------------------
    def refresh_now(self) -> None:
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("refreshing contests…")
        job = Job(sync.refresh_contests)
        job.signals.done.connect(self._on_refreshed)
        job.signals.error.connect(lambda e: (self.btn_refresh.setEnabled(True),
                                             self.btn_refresh.setText("🔄 Refresh now"),
                                             QMessageBox.critical(self, "Contest refresh failed", e)))
        pool().start(job)

    def _on_refreshed(self, counts) -> None:
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("🔄 Refresh now")
        self.refresh_table()
        self.note.setText(f"Last refresh: {fmt_dt(int(time.time()))}  "
                          f"(codeforces: {counts.get('codeforces', 0)}, "
                          f"leetcode: {counts.get('leetcode', 0)})")

    def refresh_table(self) -> None:
        phase = self.phase_combo.currentData()
        src = self.src_combo.currentData()
        rows = self.db.contests(phase=None if phase == "all" else phase,
                                source=None if src == "all" else src)
        rows.sort(key=lambda r: (r["start_time"] or 0))
        self._rows = rows
        self.table.setRowCount(len(rows))
        now = time.time()
        for r, row in enumerate(rows):
            start = row.get("start_time") or 0
            dur = row.get("duration") or 0
            ph = row["phase"]
            self.table.setItem(r, 0, _item("●" if ph == "started" else "○",
                                           color=_phase_color(ph)))
            self.table.setItem(r, 1, _item(row["name"]))
            self.table.setItem(r, 2, _item(row["source"]))
            self.table.setItem(r, 3, _item(fmt_dt(start)))
            self.table.setItem(r, 4, _item(fmt_secs(dur)))
            self.table.setItem(r, 5, _item(self._countdown_text(row, now)))
        self.table.resizeColumnsToContents()

    @staticmethod
    def _countdown_text(row: dict, now: float) -> str:
        start = row.get("start_time") or 0
        dur = row.get("duration") or 0
        if row["phase"] == "finished":
            return "ended"
        remaining = (start + dur) - now if row["phase"] == "started" else start - now
        return fmt_countdown(int(remaining))

    def _tick(self) -> None:
        now = time.time()
        rows = getattr(self, "_rows", None)
        if not rows:
            return
        changed = False
        for r, row in enumerate(rows):
            item = self.table.item(r, 5)
            if not item:
                continue
            new_text = self._countdown_text(row, now)
            if item.text() != new_text:
                item.setText(new_text)
                changed = True
        # promote newly-started contests to the running phase
        if changed:
            for r, row in enumerate(rows):
                if row["phase"] == "planned" and (row.get("start_time") or 0) <= now:
                    row["phase"] = "started"

    # ------------------------------------------------------------------
    def install_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a contest",
                                    "Choose a contest row, then install it.")
            return
        name = self.table.item(row, 1).text()
        source = self.table.item(row, 2).text()
        rows = self.db.contests()
        match = next((c for c in rows if c["name"] == name and c["source"] == source), None)
        if not match:
            QMessageBox.warning(self, "Not found", "Could not locate that contest row.")
            return
        self.open_in_competition(match["url"])

    def open_in_competition(self, contest_url: str) -> None:
        parent = self.window()
        if hasattr(parent, "install_competition_url"):
            parent.install_competition_url(contest_url)
        else:
            QMessageBox.information(self, "Install",
                                    f"Install this contest in Competition Mode:\n{contest_url}")


def _item(text: str, color: str | None = None) -> QTableWidgetItem:
    it = QTableWidgetItem(str(text))
    if color:
        it.setForeground(QColor(color))
    return it


def _phase_color(phase: str) -> str:
    return {"planned": "#e3b341", "started": "#2ea44f", "finished": "#8a8a8a"}.get(phase, "#fff")


def fmt_secs(dur: int | None) -> str:
    if not dur:
        return "—"
    h, m = divmod(int(dur) // 60, 60)
    return f"{h}h {m:02d}m"


def open_table_style() -> str:
    return ("QTableWidget { background:#202127; color:#dfe1e8; border:1px solid #3a3d46;"
            " border-radius:4px; gridline-color:#35383f; }"
            "QHeaderView::section { background:#2a2c34; color:#dfe1e8; border:none;"
            " border-bottom:1px solid #464a55; padding:4px; }"
            "QTableWidget::item:selected { background:#2b5da8; }")