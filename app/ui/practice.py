"""Practice tab: browse the full problem library, filter, solve & judge."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QSplitter, QSpinBox,
                               QVBoxLayout, QWidget)

from .. import db as dbmod
from ..workers import Job, pool
from .workbench import ProblemWorkbench

SOURCES = [("all", "All sources"), ("codeforces", "Codeforces"),
           ("leetcode", "LeetCode"), ("codewars", "Codewars")]


class PracticeTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = dbmod.get_db()
        self._current_filter: dict = {}
        self._build_ui()
        self.refresh_list()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        # filter bar
        bar = QHBoxLayout()
        self.src_combo = QComboBox()
        for value, label in SOURCES:
            self.src_combo.addItem(label, value)
        self.diff_combo = QComboBox()
        for value, label in (("all", "all difficulties"), ("easy", "easy"),
                             ("medium", "medium"), ("hard", "hard"),
                             ("unrated", "unrated")):
            self.diff_combo.addItem(label, value)
        self.rating_min = QSpinBox()
        self.rating_min.setRange(0, 4000)
        self.rating_min.setSpecialValueText("min")
        self.rating_max = QSpinBox()
        self.rating_max.setRange(0, 4000)
        self.rating_max.setValue(4000)
        self.rating_max.setSpecialValueText("max")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 search title / id / tag…")
        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText("tag (e.g. graphs)")
        self.hide_solved = QCheckBox("hide solved")
        self.status_combo = QComboBox()
        for value, label in (("all", "any status"), ("fetched", "with statement"),
                             ("pending", "pending fetch")):
            self.status_combo.addItem(label, value)
        self.btn_refresh = QPushButton("Refresh list")
        self.btn_meta = QPushButton("Sync metadata now")
        bar.addWidget(self.src_combo)
        bar.addWidget(self.diff_combo)
        bar.addWidget(self.rating_min)
        bar.addWidget(QLabel("–"))
        bar.addWidget(self.rating_max)
        bar.addWidget(self.search_edit, 2)
        bar.addWidget(self.tag_edit, 1)
        bar.addWidget(self.status_combo)
        bar.addWidget(self.hide_solved)
        bar.addWidget(self.btn_refresh)
        bar.addWidget(self.btn_meta)
        root.addLayout(bar)

        btn_row = QHBoxLayout()
        self.btn_add_url = QPushButton("➕ Add problem by URL")
        self.count_label = QLabel("")
        btn_row.addWidget(self.btn_add_url)
        btn_row.addStretch(1)
        btn_row.addWidget(self.count_label)
        root.addLayout(btn_row)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.problem_list = QListWidget()
        self.problem_list.setMaximumWidth(420)
        self.problem_list.setStyleSheet(
            "QListWidget { background:#202127; color:#dfe1e8; border:1px solid #3a3d46;"
            " border-radius:4px; font-size:12.5px; }"
            "QListWidget::item:selected { background:#2b5da8; }")
        self.workbench = ProblemWorkbench()
        split.addWidget(self.problem_list)
        split.addWidget(self.workbench)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        root.addWidget(split, 1)

        # wiring
        self.btn_refresh.clicked.connect(self.refresh_list)
        self.search_edit.textChanged.connect(self.refresh_list)
        self.tag_edit.textChanged.connect(self.refresh_list)
        self.src_combo.currentIndexChanged.connect(self.refresh_list)
        self.diff_combo.currentIndexChanged.connect(self.refresh_list)
        self.rating_min.valueChanged.connect(self.refresh_list)
        self.rating_max.valueChanged.connect(self.refresh_list)
        self.hide_solved.toggled.connect(self.refresh_list)
        self.status_combo.currentIndexChanged.connect(self.refresh_list)
        self.problem_list.currentRowChanged.connect(self._on_select)
        self.btn_add_url.clicked.connect(self.add_problem_by_url)
        self.btn_meta.clicked.connect(self.sync_metadata)
        self.workbench.judged.connect(lambda _: self._refresh_solved_badges())

    # ------------------------------------------------------------------
    def refresh_list(self) -> None:
        src = self.src_combo.currentData()
        diff = self.diff_combo.currentData()
        status = self.status_combo.currentData()
        rmin = self.rating_min.value() or None
        rmax = self.rating_max.value() or 4000
        rows = self.db.problems(
            source=None if src == "all" else src,
            difficulty=None if diff == "all" else diff,
            rating_min=rmin, rating_max=rmax,
            search=self.search_edit.text().strip(),
            tag=self.tag_edit.text().strip(),
            status=None if status == "all" else status,
            limit=5000,
        )
        if self.hide_solved.isChecked():
            solved = self.db.solved_problem_ids()
            rows = [r for r in rows if r["id"] not in solved]
        self.problem_list.clear()
        for r in rows:
            item = QListWidgetItem(_format_row(r))
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            item.setToolTip(_tooltip(r))
            self.problem_list.addItem(item)
        self.count_label.setText(f"{len(rows):,} problems")

    def _on_select(self, row: int) -> None:
        item = self.problem_list.item(row)
        if not item:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        problem = self.db.problem_by_id(pid)
        if not problem:
            return
        problem["samples"] = json.loads(problem.get("samples") or "[]")
        problem["tags"] = json.loads(problem.get("tags") or "[]")
        self.workbench.load_problem(problem, problem_id=pid)

    def _refresh_solved_badges(self) -> None:
        solved = self.db.solved_problem_ids()
        for i in range(self.problem_list.count()):
            item = self.problem_list.item(i)
            pid = item.data(Qt.ItemDataRole.UserRole)
            text = item.text()
            if pid in solved and not text.startswith("✔ "):
                item.setText("✔ " + text)

    # ------------------------------------------------------------------
    def add_problem_by_url(self) -> None:
        url, ok = QInputDialog.getText(self, "Add problem by URL",
                                       "Paste a problem URL:\n"
                                       "(codeforces.com/contest/1234/problem/A · "
                                       "leetcode.com/problems/two-sum · codewars.com/kata/slug)")
        if not ok or not url.strip():
            return
        job = Job(_fetch_problem, url.strip())
        job.signals.done.connect(self._on_fetched)
        job.signals.error.connect(lambda e: QMessageBox.critical(self, "Fetch failed", e))
        pool().start(job)

    def _on_fetched(self, result) -> None:
        if not result:
            QMessageBox.warning(self, "Not found",
                                "Could not fetch that problem (unsupported URL or blocked).")
            return
        QMessageBox.information(self, "Added", f"Stored: {result.get('source_id')}")
        self.refresh_list()
        # select it
        for i in range(self.problem_list.count()):
            if self.problem_list.item(i).data(Qt.ItemDataRole.UserRole) == result.get("id"):
                self.problem_list.setCurrentRow(i)
                break

    # ------------------------------------------------------------------
    def sync_metadata(self) -> None:
        self.btn_meta.setEnabled(False)
        job = Job(_metadata_job)
        job.signals.progress.connect(
            lambda c, t, m: self.btn_meta.setText(f"syncing… {m[:38]}"))
        job.signals.done.connect(self._on_meta_done)
        job.signals.error.connect(lambda e: (self.btn_meta.setEnabled(True),
                                             QMessageBox.critical(self, "Sync error", e)))
        pool().start(job)

    def _on_meta_done(self, stats) -> None:
        self.btn_meta.setEnabled(True)
        self.btn_meta.setText("Sync metadata now")
        self.refresh_list()
        QMessageBox.information(self, "Metadata refreshed",
                                f"New problems stored: {stats.get('new', 0)}\n"
                                f"per source: {stats.get('sources', {})}\n"
                                "The background backfill will now fetch statements "
                                "+ sample tests for anything pending.")


def _fetch_problem(url: str, progress=None):
    from ..fetchers import fetch_problem_by_url
    return fetch_problem_by_url(url)


def _metadata_job(progress=None):
    from ..services import sync
    return sync.refresh_metadata(progress)


def _format_row(r: dict) -> str:
    diff = r.get("difficulty") or "unrated"
    rating = f" {r['rating']}★" if r.get("rating") else ""
    tags = ""
    try:
        tl = json.loads(r.get("tags") or "[]")
        tags = "  [" + ", ".join(tl[:3]) + "]" if tl else ""
    except Exception:
        pass
    src = {"codeforces": "CF", "leetcode": "LC", "codewars": "CW"}.get(r.get("source"), r.get("source"))
    st = "✓" if r.get("status") == "fetched" else "…"
    return f"[{src}] {st} {r.get('title', '?')}  —  {diff}{rating}{tags}"


def _tooltip(r: dict) -> str:
    try:
        tags = ", ".join(json.loads(r.get("tags") or "[]"))
    except Exception:
        tags = ""
    return (f"{r.get('source')} {r.get('source_id')}\nContest: {r.get('contest_id')}\n"
            f"Difficulty: {r.get('difficulty')}  rating {r.get('rating')}\nTags: {tags or '-'}\n"
            f"{r.get('url', '')}")