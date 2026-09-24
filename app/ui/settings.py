"""Settings tab: refresh schedules, solution harvesting, judging comparison
mode, plus maintenance buttons."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGroupBox,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from .. import config, db as dbmod
from ..templates_data import BUILTIN_SNIPPETS
from ..workers import Job, pool

# ---------------------------------------------------------------------------
# Settings persistence (meta table, str values)
# ---------------------------------------------------------------------------
KEY_CONTEST_HOURS = "setting:contest_refresh_hours"
KEY_METADATA_DAYS = "setting:metadata_refresh_days"
KEY_HARVEST = "setting:harvest_enabled"
KEY_SOLUTIONS = "setting:solutions_per_problem"
KEY_COMPARE = "setting:compare_mode"
KEY_TOLERANCE = "setting:float_tolerance"


def setting_int(db, key: str, default: int) -> int:
    try:
        return int(db.get_meta(key))
    except (TypeError, ValueError):
        return default


def setting_float(db, key: str, default: float) -> float:
    try:
        return float(db.get_meta(key))
    except (TypeError, ValueError):
        return default


def setting_bool(db, key: str, default: bool) -> bool:
    try:
        return str(db.get_meta(key)).lower() in ("1", "true", "yes", "on")
    except (TypeError, ValueError):
        return default


def setting_str(db, key: str, default: str) -> str:
    val = db.get_meta(key)
    return val if isinstance(val, str) and val else default


def save_int(db, key: str, value: int) -> None:
    db.set_meta(key, str(int(value)))


def contest_refresh_hours(db) -> int:
    return setting_int(db, KEY_CONTEST_HOURS, config.CONTEST_REFRESH_HOURS)


def metadata_refresh_days(db) -> int:
    return setting_int(db, KEY_METADATA_DAYS, config.METADATA_REFRESH_DAYS)


def harvest_enabled(db) -> bool:
    return setting_bool(db, KEY_HARVEST, config.HARVEST_ENABLED)


def solutions_per_problem(db) -> int:
    return setting_int(db, KEY_SOLUTIONS, config.SOLUTIONS_PER_PROBLEM)


def compare_mode(db) -> str:
    return setting_str(db, KEY_COMPARE, config.COMPARE_MODE)


def float_tolerance(db) -> float:
    return setting_float(db, KEY_TOLERANCE, config.FLOAT_TOLERANCE)


# ---------------------------------------------------------------------------
# The tab
# ---------------------------------------------------------------------------
class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = dbmod.get_db()
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        # -- refresh schedules ------------------------------------------------
        g = QGroupBox("Refresh schedules")
        gl = QVBoxLayout(g)
        self.hours_spin = QSpinBox()
        self.hours_spin.setRange(6, 168)
        self.hours_spin.setSuffix(" h")
        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 60)
        self.days_spin.setSuffix(" d")
        self.hours_spin.setValue(contest_refresh_hours(self.db))
        self.days_spin.setValue(metadata_refresh_days(self.db))
        row = QHBoxLayout()
        row.addWidget(QLabel("Refresh contests every"))
        row.addWidget(self.hours_spin)
        row.addWidget(QLabel("   Refresh problem metadata every"))
        row.addWidget(self.days_spin)
        row.addStretch(1)
        gl.addLayout(row)
        root.addWidget(g)

        # -- harvesting --------------------------------------------------------
        g = QGroupBox("Solution harvesting")
        gl = QVBoxLayout(g)
        self.harvest_check = QCheckBox(
            "Harvest accepted Codeforces submissions as reference solutions "
            "(best effort — many platforms block automated access)")
        self.harvest_check.setChecked(harvest_enabled(self.db))
        self.solutions_spin = QSpinBox()
        self.solutions_spin.setRange(0, 50)
        self.solutions_spin.setValue(solutions_per_problem(self.db))
        row = QHBoxLayout()
        row.addWidget(QLabel("Max harvested solutions per problem"))
        row.addWidget(self.solutions_spin)
        row.addStretch(1)
        gl.addWidget(self.harvest_check)
        gl.addLayout(row)
        root.addWidget(g)

        # -- judging ------------------------------------------------------------
        g = QGroupBox("Judging comparison")
        gl = QVBoxLayout(g)
        self.compare_combo = QComboBox()
        for value, label in (("exact", "exact (full lines)"),
                             ("tokens", "token-wise (whitespace-insensitive)"),
                             ("numeric", "numeric with tolerance")):
            self.compare_combo.addItem(label, value)
        idx = self.compare_combo.findData(compare_mode(self.db))
        self.compare_combo.setCurrentIndex(max(0, idx))
        self.tol_spin = QDoubleSpinBox()
        self.tol_spin.setRange(1e-12, 1.0)
        self.tol_spin.setDecimals(9)
        self.tol_spin.setValue(float_tolerance(self.db))
        row = QHBoxLayout()
        row.addWidget(QLabel("Compare mode"))
        row.addWidget(self.compare_combo)
        row.addWidget(QLabel("Numeric tolerance"))
        row.addWidget(self.tol_spin)
        row.addStretch(1)
        gl.addLayout(row)
        root.addWidget(g)

        # -- actions --------------------------------------------------------------
        g = QGroupBox("Actions")
        gl = QHBoxLayout(g)
        self.btn_refresh_contests = QPushButton("🔁 Refresh contests now")
        self.btn_refresh_meta = QPushButton("↻ Refresh metadata now")
        self.btn_restore = QPushButton("Restore built-in snippets")
        self.btn_open_data = QPushButton("Open data folder")
        self.btn_about = QPushButton("About")
        for b in (self.btn_refresh_contests, self.btn_refresh_meta,
                  self.btn_restore, self.btn_open_data, self.btn_about):
            gl.addWidget(b)
        gl.addStretch(1)
        root.addWidget(g)

        note = QLabel("Harvesting and refresh options are also read by the background scheduler "
                      "in the status bar.")
        note.setStyleSheet("color:#9aa0ad;")
        root.addWidget(note)
        root.addStretch(1)

        self.hours_spin.valueChanged.connect(self._on_hours)
        self.days_spin.valueChanged.connect(self._on_days)
        self.harvest_check.toggled.connect(
            lambda v: self.db.set_meta(KEY_HARVEST, "1" if v else "0"))
        self.solutions_spin.valueChanged.connect(
            lambda v: save_int(self.db, KEY_SOLUTIONS, v))
        self.compare_combo.currentIndexChanged.connect(self._on_compare)
        self.tol_spin.valueChanged.connect(
            lambda v: self.db.set_meta(KEY_TOLERANCE, repr(float(v))))
        self.btn_refresh_contests.clicked.connect(self._refresh_contests)
        self.btn_refresh_meta.clicked.connect(self._refresh_metadata)
        self.btn_restore.clicked.connect(self._restore_snippets)
        self.btn_open_data.clicked.connect(self._open_data)
        self.btn_about.clicked.connect(self._about)

    # -- handlers ----------------------------------------------------------------
    def _on_hours(self, value: int) -> None:
        save_int(self.db, KEY_CONTEST_HOURS, value)

    def _on_days(self, value: int) -> None:
        save_int(self.db, KEY_METADATA_DAYS, value)

    def _on_compare(self) -> None:
        mode = self.compare_combo.currentData()
        if mode:
            self.db.set_meta(KEY_COMPARE, mode)
            self.tol_spin.setEnabled(mode == "numeric")

    def _refresh_contests(self) -> None:
        from ..services import sync
        self.btn_refresh_contests.setEnabled(False)
        self.btn_refresh_contests.setText("refreshing…")
        job = Job(sync.refresh_contests)
        job.signals.done.connect(self._on_contests_done)
        job.signals.error.connect(self._on_job_error(self.btn_refresh_contests,
                                                     "🔁 Refresh contests now"))
        pool().start(job)

    def _on_contests_done(self, counts) -> None:
        self.btn_refresh_contests.setEnabled(True)
        self.btn_refresh_contests.setText("🔁 Refresh contests now")
        QMessageBox.information(self, "Contests refreshed",
                                f"codeforces: {counts.get('codeforces', 0)} added\n"
                                f"leetcode: {counts.get('leetcode', 0)} added")

    def _refresh_metadata(self) -> None:
        from ..services import sync
        self.btn_refresh_meta.setEnabled(False)
        self.btn_refresh_meta.setText("syncing…")
        job = Job(sync.refresh_metadata)
        job.signals.progress.connect(
            lambda c, t, m: self.btn_refresh_meta.setText(f"syncing… {m[:30]}"))
        job.signals.done.connect(self._on_meta_done)
        job.signals.error.connect(self._on_job_error(self.btn_refresh_meta,
                                                     "↻ Refresh metadata now"))
        pool().start(job)

    def _on_meta_done(self, stats) -> None:
        self.btn_refresh_meta.setEnabled(True)
        self.btn_refresh_meta.setText("↻ Refresh metadata now")
        QMessageBox.information(
            self, "Metadata refreshed",
            f"New problems: {stats.get('new', 0)}\n"
            f"per source: {stats.get('sources', {})}\n\n"
            "Pending problems are now backfilled in the background (see status bar).")

    def _on_job_error(self, btn, restore_text):
        def _err(msg: str):
            btn.setEnabled(True)
            btn.setText(restore_text)
            QMessageBox.critical(self, "Failed", msg)
        return _err

    def _restore_snippets(self) -> None:
        if QMessageBox.question(
                self, "Restore built-in snippets",
                "Reset the built-in snippets to their defaults?\n"
                "Your own snippets are kept.") != QMessageBox.StandardButton.Yes:
            return
        names = {s["name"] for s in BUILTIN_SNIPPETS}
        for s in self.db.snippets():
            if s["name"] in names:
                self.db.delete_snippet(s["id"])
        for s in BUILTIN_SNIPPETS:
            self.db.upsert_snippet(s["name"], s["language"], s["content"])
        QMessageBox.information(self, "Restored", f"{len(BUILTIN_SNIPPETS)} built-in snippets restored.")

    def _open_data(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.DATA_DIR)))

    def _about(self) -> None:
        from .. import __version__
        QMessageBox.about(
            self, f"About {config.APP_NAME}",
            f"<h3>{config.APP_NAME}</h3><p>version {__version__}</p>"
            "<p>A desktop practice environment for competitive programming.</p>"
            "<ul><li><b>Practice</b> — rate &amp; solve Codeforces / LeetCode / Codewars "
            "problems, judged locally against sample + custom tests.</li>"
            "<li><b>Contests</b> — upcoming &amp; live contests, refreshed daily.</li>"
            "<li><b>Competition Mode</b> — paste a contest link, download all problems &amp; "
            "samples, practice under a countdown, then submit on the real platform.</li>"
            "<li><b>Free Mode</b> — write &amp; run any Python/C++ code with custom stdin.</li>"
            "<li><b>Tools</b> — snippets, templates, stress tester, test &amp; math helpers.</li></ul>"
            "<p>SQLite database: <code>{}</code></p>".format(config.DB_PATH))