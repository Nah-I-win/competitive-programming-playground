"""Competition Mode: paste a contest link, install every problem + sample
tests, work on them, verify locally, then copy/export and submit on the real
platform."""
from __future__ import annotations

import json
import time

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QColor
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton,
                               QSplitter, QVBoxLayout, QWidget)

from .. import db as dbmod
from ..core.util import fmt_countdown, fmt_dt
from ..services import sync
from ..workers import Job, pool
from .workbench import ProblemWorkbench, VERDICT_COLORS


class CompetitionTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = dbmod.get_db()
        self.current_comp: dict | None = None
        self._comp_problems: list[dict] = []
        self._build_ui()
        self.refresh_competitions()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        top = QVBoxLayout()
        row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(
            "Paste a contest link, e.g. https://codeforces.com/contest/1850  ·  "
            "https://leetcode.com/contest/weekly-contest-XXX/")
        self.btn_install = QPushButton("⬇ Install / Refresh")
        self.btn_install.setStyleSheet("background:#2b5da8; color:white; font-weight:600;")
        row.addWidget(self.url_edit, 1)
        row.addWidget(self.btn_install)
        top.addLayout(row)

        info = QHBoxLayout()
        self.comp_name = QLabel("No competition loaded")
        self.comp_name.setStyleSheet("font-size:14px; font-weight:600;")
        self.comp_time = QLabel("")
        self.comp_time.setStyleSheet("color:#e3b341; font-size:13px; font-weight:600;")
        self.btn_submit = QPushButton("🚀 Open submit page on platform")
        self.btn_submit.setEnabled(False)
        info.addWidget(self.comp_name, 3)
        info.addWidget(self.comp_time, 2)
        info.addStretch(1)
        info.addWidget(self.btn_submit)
        top.addLayout(info)
        root.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.comp_combo = QComboBox()
        self.comp_combo.currentIndexChanged.connect(self._select_competition)
        self.btn_reinstall = QPushButton("Re-install problems")
        add_row = QHBoxLayout()
        self.btn_add_problem = QPushButton("+ Add problem by URL")
        self.btn_reinstall.setEnabled(False)
        add_row.addWidget(self.btn_add_problem)
        add_row.addWidget(self.btn_reinstall)
        ll.addWidget(self.comp_combo)
        ll.addLayout(add_row)
        self.problem_list = QListWidget()
        self.problem_list.setStyleSheet(
            "QListWidget { background:#202127; color:#dfe1e8; border:1px solid #3a3d46;"
            " border-radius:4px; font-size:12.5px; }"
            "QListWidget::item:selected { background:#2b5da8; }")
        self.problem_list.currentRowChanged.connect(self._show_problem)
        ll.addWidget(self.problem_list, 1)
        split.addWidget(left)
        self.workbench = ProblemWorkbench()
        split.addWidget(self.workbench)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        root.addWidget(split, 1)

        self.btn_install.clicked.connect(self._install_from_input)
        self.btn_reinstall.clicked.connect(self._reinstall_current)
        self.btn_add_problem.clicked.connect(self.add_problem_by_url)
        self.btn_submit.clicked.connect(self._open_submit_page)
        self.workbench.judged.connect(self._on_judged)

    # ------------------------------------------------------------------
    def refresh_competitions(self) -> None:
        self.comp_combo.clear()
        for c in self.db.competitions():
            self.comp_combo.addItem(f"{c['name']}  ({c['source']})", c["id"])

    def install_competition_url(self, url: str) -> None:
        self.url_edit.setText(url)
        self._install(url)

    def _install_from_input(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.information(self, "Contest link required", "Paste a contest link first.")
            return
        self._install(url)

    def _install(self, url: str) -> None:
        self.btn_install.setEnabled(False)
        self.btn_install.setText("installing…")
        job = Job(sync.install_competition, url)
        job.signals.progress.connect(
            lambda c, t, m: self.btn_install.setText(f"⏳ {m[:40]}"))
        job.signals.done.connect(self._on_installed)
        job.signals.error.connect(self._on_install_error)
        pool().start(job)

    def _on_install_error(self, msg: str) -> None:
        self.btn_install.setEnabled(True)
        self.btn_install.setText("⬇ Install / Refresh")
        QMessageBox.critical(self, "Install failed", msg)

    def _on_installed(self, result) -> None:
        self.btn_install.setEnabled(True)
        self.btn_install.setText("⬇ Install / Refresh")
        self.refresh_competitions()
        # select installed competition
        idx = self.comp_combo.findData(result["competition_id"])
        if idx >= 0:
            self.comp_combo.setCurrentIndex(idx)
        if result.get("problems", 0) == 0:
            QMessageBox.information(self, "Installed",
                                    "Competition framework installed but no problems could be "
                                    "downloaded (gym contests need a Codeforces login).\n"
                                    "You can add problems manually with '+ Add problem by URL'.")
        else:
            QMessageBox.information(self, "Installed",
                                    f"{result['name']}\n{result['problems']} problems installed "
                                    "with statements + sample tests.")

    # ------------------------------------------------------------------
    def _select_competition(self) -> None:
        cid = self.comp_combo.currentData()
        if cid is None:
            self.current_comp = None
            self._comp_problems = []
            self.problem_list.clear()
            self.comp_name.setText("No competition loaded")
            self.comp_time.setText("")
            self.btn_submit.setEnabled(False)
            self.btn_reinstall.setEnabled(False)
            return
        comp = self.db.competition(cid)
        self.current_comp = comp
        self.btn_reinstall.setEnabled(True)
        self.comp_name.setText(comp["name"])
        self.btn_submit.setEnabled(True)
        self._comp_problems = self.db.competition_problems(cid)
        self.problem_list.clear()
        for i, p in enumerate(self._comp_problems):
            item = QListWidgetItem(f"{_comp_title(p)}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.problem_list.addItem(item)
        if self._comp_problems:
            self.problem_list.setCurrentRow(0)
        self._tick()

    def _problem_dict(self, csp: dict) -> dict:
        """Build a full problem dict for the workbench (from DB or minimal)."""
        if csp.get("problem_id"):
            row = self.db.problem_by_id(csp["problem_id"])
            if row:
                row["samples"] = json.loads(row.get("samples") or "[]")
                row["tags"] = json.loads(row.get("tags") or "[]")
                return row
        comp = self.current_comp or {}
        return {"source": comp.get("source"), "source_id": csp.get("source_id"),
                "title": csp.get("title", "?"),
                "difficulty": None, "rating": None,
                "statement": None, "samples": [], "tags": [],
                "url": csp.get("url"), "contest_id": comp.get("source_id")}

    def _show_problem(self, row: int) -> None:
        if row < 0 or row >= len(self._comp_problems):
            return
        csp = self._comp_problems[row]
        problem = self._problem_dict(csp)
        extra = []
        if not problem.get("statement"):
            extra = ["statement unavailable (possibly gym/login required)"]
        self.workbench.load_problem(
            problem, problem_id=csp.get("problem_id"),
            competition_problem_id=csp["id"], extra_meta=extra)

    def _on_judged(self, info) -> None:
        # refresh badge on the problem list
        row_idx = None
        for i, csp in enumerate(self._comp_problems):
            if csp["id"] == info.get("competition_problem_id"):
                row_idx = i
                break
        if row_idx is None:
            return
        item = self.problem_list.item(row_idx)
        if not item:
            return
        verdict = "AC" if info.get("ok") else "WA"
        prefix = "✔ " if info.get("ok") else "✘ "
        base = item.text()
        if not base.startswith(("✔ ", "✘ ")):
            item.setText(prefix + base)
        item.setForeground(QColor(VERDICT_COLORS["AC"] if info.get("ok")
                                  else VERDICT_COLORS["WA"]))

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        comp = self.current_comp
        if not comp:
            return
        start = comp.get("start_time") or 0
        dur = comp.get("duration") or 0
        now = time.time()
        if start and start > now:
            text = f"starts in {fmt_countdown(int(start - now))}  ·  {fmt_dt(start)}"
        elif start and now < start + dur:
            text = f"⏱ ends in {fmt_countdown(int(start + dur - now))}"
        elif start:
            text = "contest finished"
        else:
            text = "start time unknown"
        self.comp_time.setText(text)

    def add_problem_by_url(self) -> None:
        if not self.current_comp:
            QMessageBox.information(self, "Load a competition first",
                                    "Install a contest before adding problems.")
            return
        from PySide6.QtWidgets import QInputDialog
        url, ok = QInputDialog.getText(self, "Add problem",
                                       "Paste the problem URL (statement will be fetched "
                                       "if publicly available):")
        if not ok or not url.strip():
            return
        comp = self.current_comp
        csp_id = self.db.add_competition_problem(
            comp["id"], _guess_source_id(url, comp), "Manual problem", url.strip())
        self._comp_problems = self.db.competition_problems(comp["id"])
        self.problem_list.clear()
        for i, p in enumerate(self._comp_problems):
            item = QListWidgetItem(_comp_title(p))
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.problem_list.addItem(item)
        self._link_manual(csp_id, url)
        self.problem_list.setCurrentRow(self.problem_list.count() - 1)

    def _link_manual(self, csp_id: int, url: str) -> None:
        from ..fetchers import detect_source, fetch_problem_by_url
        source = detect_source(url)
        if not source:
            return
        job = Job(fetch_problem_by_url, url.strip())
        job.signals.done.connect(
            lambda det: self._after_manual_fetch(csp_id, det, source))
        job.signals.error.connect(lambda e: QMessageBox.warning(self, "Fetch failed", e))
        pool().start(job)

    def _after_manual_fetch(self, csp_id: int, det: dict | None, source: str) -> None:
        if not det:
            return
        self.db.execute(
            "UPDATE competition_problems SET title=?, problem_id=? WHERE id=?",
            (det.get("title") or det["source_id"], det.get("id"), csp_id))
        self.db.commit()
        # refresh list
        if self.current_comp:
            self._comp_problems = self.db.competition_problems(self.current_comp["id"])
            for i, p in enumerate(self._comp_problems):
                if p["id"] == csp_id:
                    self.problem_list.item(i).setText(f"{p['title']}  {p['source_id']}")
                    break

    def _reinstall_current(self) -> None:
        comp = self.current_comp
        if comp:
            self.install_competition_url(comp["url"])

    def _open_submit_page(self) -> None:
        url = None
        if self._comp_problems:
            row = self.problem_list.currentRow()
            if row >= 0:
                url = self._comp_problems[row].get("url")
        if not url and self.current_comp:
            url = self.current_comp.get("url")
        if url:
            QDesktopServices.openUrl(QUrl(url))
        else:
            QMessageBox.information(self, "No URL", "No problem/contest URL available.")


def _letter(index_code: str | None) -> str:
    return f"[{index_code}] " if index_code else ""


def _guess_source_id(url: str, comp: dict) -> str:
    import re
    source = comp.get("source")
    if source == "codeforces":
        m = re.search(r"(?:contest|gym)/\d+/problem/([A-Za-z0-9]+)", url)
        return f"{comp.get('source_id')}/{m.group(1)}" if m else url
    if source == "leetcode":
        m = re.search(r"/problems/([a-z0-9\-]+)/?", url)
        return m.group(1) if m else url
    return url


def _comp_title(p: dict) -> str:
    letter = p.get("source_id", "").split("/")[-1]
    return f"{p['title']}  [{letter}]" if letter else p["title"]