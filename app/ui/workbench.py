"""ProblemWorkbench: statement + editor + tests + judging results.

Shared by the Practice tab and Competition Mode so both behave identically.
"""
from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from .. import db as dbmod
from ..services import sync
from ..templates_data import CPP_TEMPLATE, PYTHON_TEMPLATE
from .widgets import CodeEditor, StatementViewer

VERDICT_COLORS = {
    "AC": "#2ea44f", "WA": "#d73a49", "TLE": "#e37933",
    "RE": "#d73a49", "CE": "#a371f7", "MLE": "#e37933", "SKIP": "#8a8a8a",
}


class _CustomTestDialog(QDialog):
    def __init__(self, parent=None, name="custom test", input_="", expected=""):
        super().__init__(parent)
        self.setWindowTitle("Custom test")
        self.setMinimumSize(520, 380)
        lay = QVBoxLayout(self)
        self.name_edit = QPlainTextEdit(name)
        self.name_edit.setFixedHeight(34)
        self.in_edit = QPlainTextEdit(input_)
        self.exp_edit = QPlainTextEdit(expected)
        lay.addWidget(QLabel("Name:"))
        lay.addWidget(self.name_edit)
        lay.addWidget(QLabel("Input (stdin):"))
        lay.addWidget(self.in_edit)
        lay.addWidget(QLabel("Expected output:"))
        lay.addWidget(self.exp_edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def values(self) -> tuple[str, str, str]:
        return (self.name_edit.toPlainText().strip() or "custom",
                self.in_edit.toPlainText(), self.exp_edit.toPlainText())


class ProblemWorkbench(QWidget):
    judged = Signal(object)          # {'problem_id', 'competition_problem_id', 'ok', 'summary'}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.problem: Optional[dict] = None
        self.problem_id: Optional[int] = None
        self.competition_problem_id: Optional[int] = None
        self.samples: list[dict] = []
        self.custom: list[dict] = []
        self._saved_code: dict[str, str] = {}
        self._pristine = True
        self._last_run: list[dict] = []
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        # header
        self.title_label = QLabel("No problem selected")
        self.title_label.setStyleSheet("font-size:15px; font-weight:600;")
        self.meta_label = QLabel("")
        self.meta_label.setStyleSheet("color:#9aa0ad;")
        head = QHBoxLayout()
        head.addWidget(self.title_label, 4)
        head.addWidget(self.meta_label, 5)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        # ---- left: statement + tests ---------------------------------
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.viewer = StatementViewer()
        ll.addWidget(self.viewer, 6)

        tests_box = QVBoxLayout()
        self.tests_list = QListWidget()
        self.tests_list.currentRowChanged.connect(self._show_test_detail)
        self.tests_list.setMaximumHeight(110)
        tests_box.addWidget(QLabel("Tests:"))
        tests_box.addWidget(self.tests_list)
        io_row = QHBoxLayout()
        self.test_in = QPlainTextEdit()
        self.test_in.setReadOnly(True)
        self.test_in.setPlaceholderText("input")
        self.test_out = QPlainTextEdit()
        self.test_out.setReadOnly(True)
        self.test_out.setPlaceholderText("expected")
        io_row.addWidget(self.test_in, 1)
        io_row.addWidget(self.test_out, 1)
        tests_box.addLayout(io_row)
        ll.addLayout(tests_box, 3)
        split.addWidget(left)

        # ---- right: editor + results ---------------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        self.btn_run_all = QPushButton("▶ Run all tests")
        self.btn_run_selected = QPushButton("Run selected")
        self.btn_add_custom = QPushButton("+ Custom test")
        self.btn_del_custom = QPushButton("− Custom test")
        self.btn_save = QPushButton("Save")
        self.btn_copy = QPushButton("Copy code")
        self.btn_export = QPushButton("Export…")
        self.btn_run_all.setStyleSheet("background:#2ea44f; color:white; font-weight:600;")
        for b in (self.btn_run_all, self.btn_run_selected, self.btn_add_custom,
                  self.btn_del_custom, self.btn_save, self.btn_copy, self.btn_export):
            toolbar.addWidget(b)
        self.lang_combo = QComboBox()
        self.lang_combo.addItems([judge_lang_py(), judge_lang_cpp()])
        self.lang_combo.currentTextChanged.connect(self._on_lang_changed)
        self.template_combo = QComboBox()
        self.template_combo.addItem("Insert template…")
        self.template_combo.addItems(
            ["Python starter", "C++ starter"] +
            [s["name"] for s in dbmod.get_db().snippets()] +
            ["Fast IO (cpp)", "DSU (Union-Find)", "Fenwick Tree",
             "Segment Tree", "modpow / modinv", "Prime Sieve", "LCM / GCD (py)"])
        self.template_combo.activated.connect(self._insert_template_at)
        toolbar.addWidget(QLabel("Lang:"))
        toolbar.addWidget(self.lang_combo)
        toolbar.addWidget(self.template_combo)
        rl.addLayout(toolbar)

        self.editor = CodeEditor()
        self.editor.set_language(judge_lang_py())
        rl.addWidget(self.editor, 5)

        # results
        self.verdict_label = QLabel("")
        self.verdict_label.setStyleSheet("font-size:14px; font-weight:700;")
        rl.addWidget(self.verdict_label)
        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(
            ["Test", "Verdict", "Time (ms)", "Mem (KB)", "diff"])
        self.results_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.itemSelectionChanged.connect(self._show_result_diff)
        self.results_table.setMaximumHeight(170)
        rl.addWidget(self.results_table, 2)
        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setMaximumHeight(120)
        self.diff_view.setPlaceholderText("diff / stderr / explanation will appear here")
        rl.addWidget(self.diff_view, 1)

        split.addWidget(right)
        split.setSizes([560, 640])
        root.addLayout(head)
        root.addWidget(split, 1)

        self._wire()
        self.tests_list.setEnabled(False)
        self.btn_run_all.setEnabled(False)

    def _wire(self) -> None:
        self.btn_run_all.clicked.connect(self.run_all)
        self.btn_run_selected.clicked.connect(self.run_selected)
        self.btn_add_custom.clicked.connect(self.add_custom_test)
        self.btn_del_custom.clicked.connect(self.delete_custom_test)
        self.btn_save.clicked.connect(self.save_code)
        self.btn_copy.clicked.connect(self.copy_code)
        self.btn_export.clicked.connect(self.export_code)
        self.editor.textChanged.connect(self._mark_dirty)

    # ------------------------------------------------------------------
    def load_problem(self, problem: Optional[dict], problem_id: Optional[int] = None,
                     competition_problem_id: Optional[int] = None,
                     extra_meta: list[str] = None) -> None:
        self.problem = problem
        self.problem_id = problem_id
        self.competition_problem_id = competition_problem_id
        if problem:
            self.title_label.setText(problem.get("title", ""))
            meta = []
            diff = problem.get("difficulty") or "unrated"
            meta.append(f"difficulty: {diff}")
            if problem.get("rating"):
                meta.append(f"rating: {problem['rating']}")
            if problem.get("time_limit_ms"):
                meta.append(f"time limit: {problem['time_limit_ms']} ms")
            if problem.get("memory_limit_mb"):
                meta.append(f"memory: {problem['memory_limit_mb']} MB")
            if problem.get("contest_id"):
                meta.append(f"contest: {problem['contest_id']}")
            if problem.get("source"):
                meta.append(f"source: {problem['source']}")
            if extra_meta:
                meta += extra_meta
            self.meta_label.setText("  |  ".join(meta))

            stmt = problem.get("statement") or ""
            is_html = problem.get("source") != "codewars"
            if problem.get("source") == "codewars" and stmt:
                from ..core.util import md_to_html
                self.viewer.setHtml(_html_doc(md_to_html(stmt)))
            else:
                self.viewer.show_statement(stmt, is_html=is_html,
                                           title=problem.get("title", ""),
                                           meta_lines=None)
            self.samples = problem.get("samples") or []
        else:
            self.title_label.setText("No problem selected")
            self.meta_label.setText("")
            self.viewer.show_plain("Select a problem from the list to begin.")
            self.samples = []

        # custom tests
        self.custom = []
        if self.problem_id:
            self.custom = dbmod.get_db().custom_tests(self.problem_id)

        self._rebuild_tests_list()
        self._load_editor_code()
        self.results_table.setRowCount(0)
        self.verdict_label.setText("")
        self.diff_view.clear()

    def _load_editor_code(self) -> None:
        lang = self.language()
        code = self._saved_code.get(self._code_key(), "")
        if code:
            self.editor.setPlainText(code)
            self._pristine = False
            return
        # starter code for the current language, else default template
        starter = None
        if self.problem:
            starter = self.problem.get("starter_py") if lang == judge_lang_py() \
                else self.problem.get("starter_cpp")
        if starter and starter.strip():
            self.editor.setPlainText(starter)
        else:
            from .tools import get_user_template as _get_template
            self.editor.setPlainText(_get_template(dbmod.get_db(), lang))
        self._pristine = True

    def language(self) -> str:
        return self.lang_combo.currentText()

    def current_code(self) -> str:
        return self.editor.toPlainText()

    def _code_key(self) -> str:
        return f"{self.problem_id or self.competition_problem_id or 0}:{self.language()}"

    def _mark_dirty(self) -> None:
        self._pristine = False
        # autosave in memory
        if self.problem_id is not None or self.competition_problem_id is not None:
            self._saved_code[self._code_key()] = self.editor.toPlainText()

    def _on_lang_changed(self, lang: str) -> None:
        self.editor.set_language(lang)
        if self.problem_id is None and self.competition_problem_id is None:
            return
        if self._pristine or not self.editor.toPlainText().strip():
            self._load_editor_code()
        else:
            self.editor.setPlainText(self._saved_code.get(self._code_key(), self.editor.toPlainText()))

    # ------------------------------------------------------------------
    def _rebuild_tests_list(self) -> None:
        self.tests_list.clear()
        for i, s in enumerate(self.samples or []):
            item = QListWidgetItem(f"Sample {i + 1}")
            item.setData(Qt.ItemDataRole.UserRole, ("sample", i))
            self.tests_list.addItem(item)
        for i, c in enumerate(self.custom or []):
            item = QListWidgetItem(f"Custom: {c.get('name', 'test')}")
            item.setData(Qt.ItemDataRole.UserRole, ("custom", i))
            self.tests_list.addItem(item)
        self.tests_list.setEnabled(True)
        self.btn_run_all.setEnabled(bool(self.samples or self.custom))

    def _all_tests(self) -> list[dict]:
        tests = []
        for i, s in enumerate(self.samples or []):
            tests.append({"name": f"Sample {i + 1}", "input": s.get("input", ""),
                          "expected": s.get("output", "")})
        for i, c in enumerate(self.custom or []):
            tests.append({"name": f"Custom: {c.get('name', i + 1)}",
                          "input": c.get("input", ""), "expected": c.get("expected", "")})
        return tests

    def _show_test_detail(self, row: int) -> None:
        if row < 0 or row >= self.tests_list.count():
            self.test_in.clear()
            self.test_out.clear()
            return
        kind, idx = self.tests_list.item(row).data(Qt.ItemDataRole.UserRole)
        if kind == "sample":
            s = self.samples[idx]
        else:
            s = self.custom[idx]
        self.test_in.setPlainText(s.get("input", ""))
        self.test_out.setPlainText(s.get("output", "") if kind == "sample" else s.get("expected", ""))

    # ------------------------------------------------------------------
    def run_all(self) -> None:
        self._run_tests(self.samples, self.custom)

    def run_selected(self) -> None:
        row = self.tests_list.currentRow()
        if row < 0:
            return
        kind, idx = self.tests_list.item(row).data(Qt.ItemDataRole.UserRole)
        if kind == "sample":
            self._run_tests([self.samples[idx]], [])
        else:
            self._run_tests([], [self.custom[idx]])

    def _run_tests(self, samples: list[dict], custom: list[dict]) -> None:
        if not samples and not custom:
            QMessageBox.information(self, "No tests",
                                    "Add a custom test or load a problem with samples.")
            return
        code = self.current_code()
        language = self.language()
        problem = self.problem
        self.verdict_label.setText("⏳ judging…")
        self.verdict_label.setStyleSheet("color:#9aa0ad; font-size:14px; font-weight:700;")
        job = _JudgeJob(self, problem, code, language, samples, custom)
        job.signals.done.connect(self._on_judge_done)
        job.signals.error.connect(_on_judge_error)
        sync_pool().start(job)

    def _on_judge_done(self, result) -> None:
        summary, ok, details = result
        self.verdict_label.setText(summary)
        self.verdict_label.setStyleSheet(
            f"color:{VERDICT_COLORS.get(summary.split()[0], '#9aa0ad')}; font-size:15px; font-weight:700;")
        self._last_run = details
        self.results_table.setRowCount(len(details))
        for r, d in enumerate(details):
            for c, val in enumerate((d.get("name"), d.get("verdict"),
                                     f"{d.get('time_ms', 0):.0f}",
                                     d.get("memory_kb", 0), "")):
                item = QTableWidgetItem(str(val))
                if c == 1:
                    item.setForeground(QColor(VERDICT_COLORS.get(val, "#fff")))
                if c == 4:
                    item = QTableWidgetItem((d.get("diff") or "")[:60].replace("\n", " "))
                    item.setToolTip(d.get("diff") or "")
                self.results_table.setItem(r, c, item)
        # record submission
        try:
            dbmod.get_db().record_submission(
                self.problem_id, self.competition_problem_id, self.language(),
                self.current_code(), summary.split()[0],
                max((d.get("time_ms") or 0) for d in details) if details else None,
                max((d.get("memory_kb") or 0) for d in details) if details else None,
                {"results": details},
            )
        except Exception:
            pass
        self.judged.emit({"problem_id": self.problem_id,
                          "competition_problem_id": self.competition_problem_id,
                          "ok": ok, "summary": summary})

    def _show_result_diff(self) -> None:
        rows = self.results_table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self._last_run):
            return
        d = self._last_run[rows[0].row()]
        text = d.get("diff") or ""
        if d.get("verdict") == "AC":
            text = "output matches expected ✔"
        self.diff_view.setPlainText(text)

    # ------------------------------------------------------------------
    def add_custom_test(self) -> None:
        dlg = _CustomTestDialog(self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        name, input_, expected = dlg.values()
        if self.problem_id:
            dbmod.get_db().add_custom_test(self.problem_id, name, input_, expected)
        else:
            self.custom.append({"name": name, "input": input_, "expected": expected})
        self._rebuild_tests_list()
        self.tests_list.setCurrentRow(self.tests_list.count() - 1)

    def delete_custom_test(self) -> None:
        row = self.tests_list.currentRow()
        if row < 0:
            return
        kind, idx = self.tests_list.item(row).data(Qt.ItemDataRole.UserRole)
        if kind != "custom":
            return
        test = self.custom[idx]
        if self.problem_id and test.get("id"):
            dbmod.get_db().delete_custom_test(test["id"])
        self.custom.pop(idx)
        self._rebuild_tests_list()

    def save_code(self) -> None:
        self._saved_code[self._code_key()] = self.editor.toPlainText()
        QMessageBox.information(self, "Saved", "Your code is kept for this session "
                               "(use Export… to write it to a file).")

    def copy_code(self) -> None:
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.verdict_label.setText("copied to clipboard ✔")
        self.verdict_label.setStyleSheet("color:#2ea44f; font-weight:600;")

    def export_code(self) -> None:
        ext = ".py" if self.language() == judge_lang_py() else ".cpp"
        default = f"{self.problem_id or self.competition_problem_id or 'solution'}{ext}"
        path, _ = QFileDialog.getSaveFileName(self, "Export solution", default)
        if path:
            from ..core.util import atomic_write_text
            atomic_write_text(path, self.editor.toPlainText())
            QMessageBox.information(self, "Exported", f"Saved to:\n{path}")

    # ------------------------------------------------------------------
    def _insert_template_at(self, index: int) -> None:
        if index <= 0:
            return
        name = self.template_combo.itemText(index)
        content = self._template_content(name)
        if content:
            self.editor.insert_from_template(content)
        self.template_combo.setCurrentIndex(0)

    def _template_content(self, name: str) -> Optional[str]:
        if name == "Python starter":
            return PYTHON_TEMPLATE
        if name == "C++ starter":
            return CPP_TEMPLATE
        db = dbmod.get_db()
        for s in db.snippets():
            if s["name"] == name:
                return s["content"]
        raw = {"Fast IO (cpp)": "ios::sync_with_stdio(false);\ncin.tie(nullptr);",
               "DSU (Union-Find)": _dsu, "Fenwick Tree": _fenwick,
               "Segment Tree": _segtree, "modpow / modinv": _modpow,
               "Prime Sieve": _sieve, "LCM / GCD (py)": _lcm}.get(name)
        return raw


def _dsu() -> str:
    from ..templates_data import BUILTIN_SNIPPETS
    return next(s["content"] for s in BUILTIN_SNIPPETS if s["name"] == "DSU (Union-Find)")


def _fenwick() -> str:
    from ..templates_data import BUILTIN_SNIPPETS
    return next(s["content"] for s in BUILTIN_SNIPPETS if s["name"] == "Fenwick Tree")


def _segtree() -> str:
    from ..templates_data import BUILTIN_SNIPPETS
    return next(s["content"] for s in BUILTIN_SNIPPETS if s["name"] == "Segment Tree (range sums)")


def _modpow() -> str:
    from ..templates_data import BUILTIN_SNIPPETS
    return next(s["content"] for s in BUILTIN_SNIPPETS if s["name"] == "modpow / modinv")


def _sieve() -> str:
    from ..templates_data import BUILTIN_SNIPPETS
    return next(s["content"] for s in BUILTIN_SNIPPETS if s["name"] == "Prime Sieve")


def _lcm() -> str:
    from ..templates_data import BUILTIN_SNIPPETS
    return next(s["content"] for s in BUILTIN_SNIPPETS if s["name"] == "LCM / GCD (py)")


# ---------------------------------------------------------------------------
# Judge job (needs a QObject signal holder)
# ---------------------------------------------------------------------------
from PySide6.QtCore import QObject, QRunnable  # noqa: E402

from .. import workers  # noqa: E402


class _JudgeSignals(QObject):
    done = Signal(object)
    error = Signal(str)


class _JudgeJob(QRunnable):
    def __init__(self, workbench, problem, code, language, samples, custom):
        super().__init__()
        self.signals = _JudgeSignals()
        self.workbench = workbench
        self.problem = problem
        self.code = code
        self.language = language
        self.samples = samples
        self.custom = custom
        self.setAutoDelete(True)

    def run(self):  # noqa: A003
        try:
            from .. import config as _cfg
            from ..services import sync
            problem = self.problem
            result = sync.judge_problem(
                problem, self.code, self.language,
                samples=self.samples, custom=self.custom,
                time_limit_ms=(problem or {}).get("time_limit_ms"),
                memory_mb=(problem or {}).get("memory_limit_mb"),
                compare_mode=_cfg.COMPARE_MODE)
            self.signals.done.emit(result)
        except Exception as exc:
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")


def _on_judge_error(msg: str) -> None:
    QMessageBox.critical(None, "Judge error", msg)


def judge_lang_py() -> str:
    from ..core.judge import LANG_PY
    return LANG_PY


def judge_lang_cpp() -> str:
    from ..core.judge import LANG_CPP
    return LANG_CPP


def sync_pool():
    from ..workers import pool
    return pool()


def _html_doc(body_html: str) -> str:
    from .widgets import _STYLE
    return _STYLE + body_html