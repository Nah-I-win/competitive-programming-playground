"""Tools tab: starter templates, snippet library, stress tester, random test
generator, math helpers and an algorithm cheatsheet."""
from __future__ import annotations

import math
import random
import string
import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from .. import config, db as dbmod
from ..core.util import md_to_html
from ..templates_data import BUILTIN_SNIPPETS, CPP_TEMPLATE, PYTHON_TEMPLATE
from ..workers import Job, pool
from .widgets import CodeEditor

_TEMPLATE_KEY = {"Python": "template:python", "C++": "template:cpp"}


def get_user_template(db, lang: str) -> str:
    """Starter template from settings, else the builtin."""
    key = _TEMPLATE_KEY.get(lang)
    if not key:
        return ""
    val = db.get_meta(key)
    if val:
        return val
    return PYTHON_TEMPLATE if lang == "Python" else CPP_TEMPLATE


# ===========================================================================
# Starter templates page
# ===========================================================================
class _TemplatesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = dbmod.get_db()
        root = QVBoxLayout(self)
        tip = QLabel("These templates are inserted into the editor when you open a new problem "
                     "with no starter code. Changes apply immediately.")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#9aa0ad;")
        root.addWidget(tip)

        tabs = QTabWidget()
        self._py = CodeEditor()
        self._cpp = CodeEditor()
        self._py.set_language("Python")
        self._cpp.set_language("C++")
        self._py.setPlainText(get_user_template(self.db, "Python"))
        self._cpp.setPlainText(get_user_template(self.db, "C++"))
        tabs.addTab(self._edit_tab(self._py, "Python"), "Python")
        tabs.addTab(self._edit_tab(self._cpp, "C++"), "C++")
        root.addWidget(tabs, 1)

    def _edit_tab(self, editor: CodeEditor, lang: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.addWidget(editor, 1)
        row = QHBoxLayout()
        btn_save = QPushButton("💾 Save template")
        btn_save.clicked.connect(lambda: self._save(lang, editor))
        btn_restore = QPushButton("Restore default")
        btn_restore.clicked.connect(lambda: self._restore(lang, editor))
        row.addStretch(1)
        row.addWidget(btn_restore)
        row.addWidget(btn_save)
        lay.addLayout(row)
        return w

    def _save(self, lang: str, editor: CodeEditor) -> None:
        self.db.set_meta(_TEMPLATE_KEY[lang], editor.toPlainText())
        QMessageBox.information(self, "Saved", f"{lang} starter template saved.")

    def _restore(self, lang: str, editor: CodeEditor) -> None:
        editor.setPlainText(PYTHON_TEMPLATE if lang == "Python" else CPP_TEMPLATE)
        self._save(lang, editor)


# ===========================================================================
# Snippets page
# ===========================================================================
class _SnippetsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = dbmod.get_db()
        self._current_id: int | None = None
        self._build_ui()
        self.refresh_list()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.filter_combo = QComboBox()
        for value, label in (("", "all languages"), ("cpp", "C++"),
                             ("python", "Python"), ("both", "both")):
            self.filter_combo.addItem(label, value)
        self.btn_new = QPushButton("+ New snippet")
        self.btn_delete = QPushButton("🗑 Delete")
        self.btn_copy = QPushButton("Copy to clipboard")
        bar.addWidget(self.filter_combo)
        bar.addWidget(self.btn_new)
        bar.addWidget(self.btn_delete)
        bar.addStretch(1)
        bar.addWidget(self.btn_copy)
        root.addLayout(bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.snip_list = QListWidget()
        self.snip_list.setMaximumWidth(340)
        self.snip_list.setStyleSheet(
            "QListWidget { background:#202127; color:#dfe1e8; border:1px solid #3a3d46;"
            " border-radius:4px; }"
            "QListWidget::item:selected { background:#2b5da8; }")
        split.addWidget(self.snip_list)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("snippet name")
        self.lang_combo = QComboBox()
        for value, label in (("cpp", "C++"), ("python", "Python"), ("both", "both")):
            self.lang_combo.addItem(label, value)
        self.btn_save = QPushButton("💾 Save snippet")
        row.addWidget(self.name_edit, 1)
        row.addWidget(self.lang_combo)
        row.addWidget(self.btn_save)
        rl.addLayout(row)
        self.content_edit = CodeEditor()
        self.content_edit.set_language("C++")
        rl.addWidget(self.content_edit, 1)
        note = QLabel("Snippets you save here appear in the editor's 'Insert template' menu "
                      "of the Practice / Competition workbenches.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#9aa0ad;")
        rl.addWidget(note)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)

        self.filter_combo.currentIndexChanged.connect(self.refresh_list)
        self.snip_list.currentRowChanged.connect(self._select)
        self.btn_new.clicked.connect(self._new)
        self.btn_save.clicked.connect(self._save)
        self.btn_delete.clicked.connect(self._delete)
        self.btn_copy.clicked.connect(self._copy)
        self.name_edit.textChanged.connect(self._note_lang)

    def _note_lang(self) -> None:
        if self.name_edit.text().strip().lower().startswith(("py", "python")):
            self.lang_combo.setCurrentIndex(self.lang_combo.findData("python"))
        elif self.name_edit.text().strip().lower().startswith(("cpp", "c++")):
            self.lang_combo.setCurrentIndex(self.lang_combo.findData("cpp"))

    def refresh_list(self) -> None:
        lang = self.filter_combo.currentData() or None
        rows = self.db.snippets(language=lang)
        self.snip_list.clear()
        for r in rows:
            item = QListWidgetItem(f"{r['name']}  ({r['language']})")
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.snip_list.addItem(item)
        if self.snip_list.count():
            self.snip_list.setCurrentRow(0)
        else:
            self._clear_editor()

    def _clear_editor(self) -> None:
        self._current_id = None
        self.name_edit.clear()
        self.content_edit.clear()

    def _select(self, row: int) -> None:
        item = self.snip_list.item(row)
        if not item:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        row_data = next((s for s in self.db.snippets() if s["id"] == sid), None)
        if not row_data:
            return
        self._current_id = sid
        self.name_edit.setText(row_data["name"])
        lang = row_data["language"]
        idx = self.lang_combo.findData(lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.content_edit.set_language("C++" if "cpp" in lang else "Python")
        self.content_edit.setPlainText(row_data["content"])

    def _new(self) -> None:
        self._clear_editor()
        self.snip_list.clearSelection()
        self.name_edit.setFocus()
        idx = self.lang_combo.findData("cpp")
        self.lang_combo.setCurrentIndex(idx)
        self.content_edit.set_language("C++")

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        content = self.content_edit.toPlainText()
        if not name or not content.strip():
            QMessageBox.warning(self, "Incomplete", "Provide a name and snippet content.")
            return
        lang = self.lang_combo.currentData()
        # duplicate-name check (ignoring the row being edited)
        dup = next((s for s in self.db.snippets() if s["name"] == name
                    and s["id"] != self._current_id), None)
        if dup:
            QMessageBox.warning(self, "Duplicate name",
                                f"A snippet named '{name}' already exists.")
            return
        if self._current_id is not None:
            self.db.execute("UPDATE snippets SET name=?, language=?, content=? WHERE id=?",
                            (name, lang, content, self._current_id))
            self.db.commit()
        else:
            self.db.upsert_snippet(name, lang, content)
        self.refresh_list()
        # select the saved row
        for i in range(self.snip_list.count()):
            if self.snip_list.item(i).text().startswith(name):
                self.snip_list.setCurrentRow(i)
                break

    def _delete(self) -> None:
        if self._current_id is None:
            QMessageBox.information(self, "Nothing selected", "Select a snippet to delete.")
            return
        if QMessageBox.question(self, "Delete snippet", "Delete this snippet?") == \
                QMessageBox.StandardButton.Yes:
            self.db.delete_snippet(self._current_id)
            self.refresh_list()

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.content_edit.toPlainText())


# ===========================================================================
# Stress tester page
# ===========================================================================
class _StressPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = dbmod.get_db()
        self._stop = threading.Event()
        self._running = False
        self._result = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        tip = QLabel("Pit your fast solution against a brute-force reference on random inputs. "
                     "The first mismatch is captured as a counterexample you can store as a "
                     "custom test.")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#9aa0ad;")
        root.addWidget(tip)

        controls = QHBoxLayout()
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Python", "Python")
        self.lang_combo.addItem("C++", "C++")
        self.iter_spin = QSpinBox()
        self.iter_spin.setRange(10, 5000)
        self.iter_spin.setValue(300)
        self.tl_spin = QSpinBox()
        self.tl_spin.setRange(100, 20000)
        self.tl_spin.setValue(2000)
        self.tl_spin.setSuffix(" ms")
        self.mem_spin = QSpinBox()
        self.mem_spin.setRange(64, 1024)
        self.mem_spin.setValue(256)
        self.mem_spin.setSuffix(" MB")
        self.btn_run = QPushButton("▶ Run stress")
        self.btn_run.setStyleSheet("background:#2b5da8; color:white; font-weight:600;")
        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setEnabled(False)
        self.progress_label = QLabel("")
        controls.addWidget(QLabel("language"))
        controls.addWidget(self.lang_combo)
        controls.addWidget(QLabel("iterations"))
        controls.addWidget(self.iter_spin)
        controls.addWidget(self.tl_spin)
        controls.addWidget(self.mem_spin)
        controls.addWidget(self.btn_run)
        controls.addWidget(self.btn_stop)
        controls.addStretch(1)
        controls.addWidget(self.progress_label)
        root.addLayout(controls)

        split = QSplitter(Qt.Orientation.Vertical)
        top = QSplitter(Qt.Orientation.Horizontal)
        self.brute_edit = CodeEditor()
        self.brute_edit.set_language("Python")
        self.fast_edit = CodeEditor()
        self.fast_edit.set_language("Python")
        for w, t in ((self.brute_edit, "Brute force (reference)"),
                     (self.fast_edit, "Fast solution (being tested)")):
            box = QGroupBox(t)
            box.setLayout(QVBoxLayout())
            box.layout().addWidget(w)
            top.addWidget(box)
        top.setSizes([400, 400])
        split.addWidget(top)

        self.gen_edit = CodeEditor()
        self.gen_edit.set_language("Python")
        gen_box = QGroupBox("Generator — prints ONE random test case to stdout each run (always Python)")
        gen_box.setLayout(QVBoxLayout())
        gen_box.layout().addWidget(self.gen_edit)
        split.addWidget(gen_box)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(140)
        bl.addWidget(self.log_view, 1)
        actions = QHBoxLayout()
        self.btn_copy_case = QPushButton("📋 Copy counterexample")
        self.btn_copy_case.setEnabled(False)
        self.problem_combo = QComboBox()
        self.btn_refresh_problems = QPushButton("refresh")
        self.btn_save_case = QPushButton("＋ Store as custom test on selected problem")
        self.btn_save_case.setEnabled(False)
        actions.addWidget(self.btn_copy_case)
        actions.addWidget(QLabel("problem:"))
        actions.addWidget(self.problem_combo, 1)
        actions.addWidget(self.btn_refresh_problems)
        actions.addWidget(self.btn_save_case)
        bl.addLayout(actions)
        split.addWidget(bottom)
        root.addWidget(split, 1)

        self.btn_run.clicked.connect(self._run)
        self.btn_stop.clicked.connect(self._stop.set)
        self.btn_copy_case.clicked.connect(self._copy_case)
        self.btn_save_case.clicked.connect(self._save_case)
        self.btn_refresh_problems.clicked.connect(self._refresh_problems)
        self.lang_combo.currentIndexChanged.connect(
            lambda: (self.fast_edit.set_language(self.lang_combo.currentData()),
                     self.brute_edit.set_language(self.lang_combo.currentData())))
        self._refresh_problems()

    def _refresh_problems(self) -> None:
        self.problem_combo.clear()
        rows = self.db.problems(status="fetched", limit=500)
        for r in rows:
            self.problem_combo.addItem(f"[{r.get('source','')}] {r.get('title','?')}", r["id"])
        self.problem_combo.setCurrentIndex(-1)
        self.problem_combo.setPlaceholderText("select a problem…")

    def _run(self) -> None:
        if self._running:
            return
        gen = self.gen_edit.toPlainText().strip()
        brute = self.brute_edit.toPlainText().strip()
        fast = self.fast_edit.toPlainText().strip()
        if not gen or not brute or not fast:
            QMessageBox.warning(self, "Missing code", "Fill in generator, brute force and fast code.")
            return
        self._stop.clear()
        self._running = True
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.log_view.setPlainText("")
        job = Job(_stress_job, fast, brute, gen, self.lang_combo.currentData(),
                  self.iter_spin.value(), self.tl_spin.value(), self.mem_spin.value(),
                  self._stop, _progress=self._on_progress)
        job.signals.done.connect(self._on_done)
        job.signals.error.connect(self._on_error)
        pool().start(job)

    def _on_progress(self, cur, total, msg) -> None:
        if cur % 25 == 0 or cur == total:
            self.progress_label.setText(msg if msg else f"{cur}/{total}")

    def _log(self, text: str) -> None:
        self.log_view.setPlainText((self.log_view.toPlainText() + text + "\n")[-4000:])

    def _on_done(self, res) -> None:
        self._running = False
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_label.setText("")
        self._result = res
        if res.ok:
            self._log(f"✔ {res.iterations} random cases — no mismatch found.")
            self.btn_copy_case.setEnabled(False)
            self.btn_save_case.setEnabled(False)
            return
        if res.error:
            self._log(f"✘ stopped after {res.iterations} runs: {res.error}")
            self.btn_copy_case.setEnabled(False)
            self.btn_save_case.setEnabled(False)
            return
        self._log(f"✘ MISMATCH after {res.iterations} runs:\n"
                  f"--- input ---\n{res.input.strip()}\n"
                  f"--- fast output ---\n{res.fast_out.strip()}\n"
                  f"--- brute output ---\n{res.brute_out.strip()}")
        self.btn_copy_case.setEnabled(True)
        self.btn_save_case.setEnabled(bool(self.problem_combo.currentData()))

    def _on_error(self, msg: str) -> None:
        self._running = False
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_label.setText("")
        self._log(f"error: {msg}")

    def _copy_case(self) -> None:
        if self._result and self._result.input:
            QApplication.clipboard().setText(self._result.input)
            self._log("counterexample input copied to clipboard")

    def _save_case(self) -> None:
        if not self._result:
            return
        pid = self.problem_combo.currentData()
        if not pid:
            QMessageBox.information(self, "Select a problem", "Choose a problem to attach the test to.")
            return
        n = 1
        while True:
            name = f"stress counterexample #{n}"
            if not any(c["name"] == name for c in self.db.custom_tests(pid)):
                break
            n += 1
        expected = self._result.brute_out.strip() or self._result.fast_out.strip()
        self.db.add_custom_test(pid, name, self._result.input, expected)
        QMessageBox.information(
            self, "Stored",
            f"Stored '{name}' on problem {pid}.\nIt will be judged on the next "
            "'Run all' in that problem's workbench.")
        self.btn_save_case.setEnabled(False)


def _stress_job(fast: str, brute: str, gen: str, language: str, iterations: int,
                tlm: int, mmb: int, stop_event: threading.Event,
                progress=None):
    from ..core.stress import run_stress

    def cb(i: int) -> None:
        if progress:
            progress(i, iterations, f"stress {i}/{iterations}")

    return run_stress(fast, brute, gen, language, iterations=iterations,
                      time_limit_ms=tlm, memory_mb=mmb, progress=cb,
                      stop_event=stop_event)


# ===========================================================================
# Random test generator page
# ===========================================================================
class _GenPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.format_combo = QComboBox()
        for value, label in (("array", "array of ints"),
                             ("matrix", "matrix"),
                             ("string", "binary / lowercase string"),
                             ("pairs", "n pairs (edges)"),
                             ("queries", "array + q queries")):
            self.format_combo.addItem(label, value)
        self.n_spin = QSpinBox()
        self.n_spin.setRange(1, 100000)
        self.n_spin.setValue(10)
        self.val_spin = QSpinBox()
        self.val_spin.setRange(0, 10**9)
        self.val_spin.setValue(100)
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 2**31 - 1)
        self.seed_spin.setValue(int(time.time()) % (2**31))
        self.btn_gen = QPushButton("🎲 Generate")
        self.btn_gen.setStyleSheet("background:#2b5da8; color:white; font-weight:600;")
        self.btn_copy = QPushButton("📋 Copy")
        bar.addWidget(QLabel("format"))
        bar.addWidget(self.format_combo)
        bar.addWidget(QLabel("n"))
        bar.addWidget(self.n_spin)
        bar.addWidget(QLabel("max value"))
        bar.addWidget(self.val_spin)
        bar.addWidget(QLabel("seed"))
        bar.addWidget(self.seed_spin)
        bar.addWidget(self.btn_gen)
        bar.addWidget(self.btn_copy)
        bar.addStretch(1)
        root.addLayout(bar)

        self.out_view = QPlainTextEdit()
        self.out_view.setReadOnly(True)
        root.addWidget(self.out_view, 1)

        self.btn_gen.clicked.connect(self._generate)
        self.btn_copy.clicked.connect(
            lambda: QApplication.clipboard().setText(self.out_view.toPlainText()))

    def _generate(self) -> None:
        rng = random.Random(self.seed_spin.value())
        fmt = self.format_combo.currentData()
        n = self.n_spin.value()
        hi = self.val_spin.value()
        lines: list[str] = []
        if fmt == "array":
            lines.append(str(n))
            lines.append(" ".join(str(rng.randint(1, hi)) for _ in range(n)))
        elif fmt == "matrix":
            m = max(1, min(20, n))
            lines.append(f"{n} {m}")
            for _ in range(n):
                lines.append(" ".join(str(rng.randint(0, hi)) for _ in range(m)))
        elif fmt == "string":
            if (hi & 1) == 0:
                lines.append(f"{n}")
                lines.append("".join(rng.choice("01") for _ in range(n)))
            else:
                lines.append(f"{n}")
                lines.append("".join(rng.choice(string.ascii_lowercase) for _ in range(n)))
        elif fmt == "pairs":
            lines.append(f"{n}")
            for _ in range(n):
                lines.append(f"{rng.randint(1, max(1, hi))} {rng.randint(1, max(1, hi))}")
        else:  # queries
            q = max(1, min(n, 200))
            lines.append(f"{n} {q}")
            lines.append(" ".join(str(rng.randint(1, hi)) for _ in range(n)))
            for _ in range(q):
                l = rng.randint(1, n)
                r = rng.randint(l, n)
                lines.append(f"{l} {r} {rng.randint(0, hi)}")
        self.out_view.setPlainText("\n".join(lines))


# ===========================================================================
# Math helpers page
# ===========================================================================
class _MathPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        grid = QHBoxLayout()
        self.a_spin = QSpinBox()
        self.a_spin.setRange(-10**9, 10**9)
        self.a_spin.setValue(48)
        self.b_spin = QSpinBox()
        self.b_spin.setRange(-10**9, 10**9)
        self.b_spin.setValue(18)
        self.m_spin = QSpinBox()
        self.m_spin.setRange(1, 10**9)
        self.m_spin.setValue(1_000_000_007)
        self.k_spin = QSpinBox()
        self.k_spin.setRange(0, 100)
        self.k_spin.setValue(5)
        grid.addWidget(QLabel("a"))
        grid.addWidget(self.a_spin)
        grid.addWidget(QLabel("b"))
        grid.addWidget(self.b_spin)
        grid.addWidget(QLabel("mod m"))
        grid.addWidget(self.m_spin)
        grid.addWidget(QLabel("k"))
        grid.addWidget(self.k_spin)
        grid.addStretch(1)
        root.addLayout(grid)

        buttons = QHBoxLayout()
        self.btn_gcd = QPushButton("gcd / lcm(a,b)")
        self.btn_primes = QPushButton("primes ≤ n")
        self.btn_factor = QPushButton("factorize n")
        self.btn_modpow = QPushButton("a^b mod m")
        self.btn_comb = QPushButton("C(a, b)")
        self.btn_fib = QPushButton("fib k")
        for b in (self.btn_gcd, self.btn_primes, self.btn_factor,
                  self.btn_modpow, self.btn_comb, self.btn_fib):
            buttons.addWidget(b)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.out_view = QPlainTextEdit()
        self.out_view.setReadOnly(True)
        self.out_view.setMaximumHeight(220)
        root.addWidget(self.out_view, 1)

        self.btn_gcd.clicked.connect(self._gcd)
        self.btn_primes.clicked.connect(self._primes)
        self.btn_factor.clicked.connect(self._factor)
        self.btn_modpow.clicked.connect(self._modpow)
        self.btn_comb.clicked.connect(self._comb)
        self.btn_fib.clicked.connect(self._fib)

    def _show(self, lines) -> None:
        self.out_view.setPlainText("\n".join(lines))

    def _gcd(self) -> None:
        a, b = self.a_spin.value(), self.b_spin.value()
        g = math.gcd(abs(a), abs(b))
        l = abs(a * b) // g if g else 0
        self._show([f"gcd({a}, {b}) = {g}", f"lcm({a}, {b}) = {l}"])

    def _primes(self) -> None:
        n = self.a_spin.value()
        if n < 2:
            self._show(["nothing to sieve below 2"])
            return
        if n > 2_000_000:
            self._show([f"n too large to sieve quickly (max 2,000,000), got {n}"])
            return
        sieve = bytearray(b"\x01") * (n + 1)
        sieve[0] = sieve[1] = 0
        for i in range(2, int(n ** 0.5) + 1):
            if sieve[i]:
                sieve[i * i::i] = b"\x00" * (((n - i * i) // i) + 1)
        primes = [i for i in range(2, n + 1) if sieve[i]]
        self._show([f"{len(primes)} primes ≤ {n}:", " ".join(map(str, primes[:200]))
                    + (" …" if len(primes) > 200 else "")])

    def _factor(self) -> None:
        n = self.a_spin.value()
        if n == 0:
            self._show(["0"])
            return
        x, out = abs(n), []
        neg = n < 0
        d = 2
        while d * d <= x:
            cnt = 0
            while x % d == 0:
                x //= d
                cnt += 1
            if cnt:
                out.append(f"{d}^{cnt}" if cnt > 1 else str(d))
            d += 1 if d == 2 else 2
        if x > 1:
            out.append(str(x))
        self._show([f"{n} = " + ("-1 × " if neg else "") + " × ".join(out)])

    def _modpow(self) -> None:
        base = self.a_spin.value()
        e = self.b_spin.value()
        m = self.m_spin.value()
        r = pow(base % m, e, m)
        self._show([f"{base}^{e} mod {m} = {r}",
                    f"(inverse of {base} mod {m} = {pow(base % m, -1, m) if math.gcd(base % m, m) == 1 else 'n/a'})"])

    def _comb(self) -> None:
        a, b = self.a_spin.value(), self.b_spin.value()
        if a < 0 or b < 0 or b > a:
            self._show(["need 0 ≤ b ≤ a"])
            return
        self._show([f"C({a}, {b}) = {math.comb(a, b)}",
                    f"P({a}, {b}) = {math.perm(a, b)}"])

    def _fib(self) -> None:
        k = self.k_spin.value()
        if k > 10000:
            self._show([f"k too large (max 10000), got {k}"])
            return
        a, b = 0, 1
        series = []
        for _ in range(min(k + 1, 200)):
            series.append(str(a))
            a, b = b, a + b
        self._show([f"fib(0..{k}):", " ".join(series)])


# ===========================================================================
# Cheatsheet page
# ===========================================================================
_CHEATSHEET_MD = r"""
# Competitive Programming Cheatsheet

## Fast input

**Python**
```python
import sys
data = sys.stdin.buffer.read().split()
it = iter(data)
n = int(next(it))
a = [int(next(it)) for _ in range(n)]
```

**C++**
```cpp
ios::sync_with_stdio(false);
cin.tie(nullptr);
```

## Common algorithms (C++)

**Binary search on answer**
```cpp
long long lo = 0, hi = 1e18;
while (lo < hi) {
    long long mid = (lo + hi + 1) / 2;
    if (check(mid)) lo = mid;
    else hi = mid - 1;
}
```

**DSU / Union-Find**
```cpp
struct DSU {
    vector<int> p, sz;
    DSU(int n): p(n), sz(n, 1) { iota(p.begin(), p.end(), 0); }
    int find(int x) { return p[x] == x ? x : p[x] = find(p[x]); }
    bool unite(int a, int b) {
        a = find(a); b = find(b);
        if (a == b) return false;
        if (sz[a] < sz[b]) swap(a, b);
        p[b] = a; sz[a] += sz[b];
        return true;
    }
};
```

**Dijkstra (priority queue)**
```cpp
const long long INF = 4e18;
vector<long long> dist(n, INF);
priority_queue<pair<ll,int>, vector<pair<ll,int>>, greater<>> pq;
dist[s] = 0; pq.push({0, s});
while (!pq.empty()) {
    auto [d, u] = pq.top(); pq.pop();
    if (d != dist[u]) continue;
    for (auto [v, w] : g[u]) if (dist[u] + w < dist[v]) {
        dist[v] = dist[u] + w; pq.push({dist[v], v});
    }
}
```

**Segment tree (range sum)**
```cpp
struct SegTree {
    int n; vector<long long> t;
    SegTree(const vector<long long>& a) {
        n = a.size(); t.assign(2*n, 0);
        for (int i = 0; i < n; ++i) t[n+i] = a[i];
        for (int i = n-1; i > 0; --i) t[i] = t[i<<1] + t[i<<1|1];
    }
    void upd(int p, long long v) { for (t[p+=n]=v; p>1; p>>=1) t[p>>1] = t[p] + t[p^1]; }
    long long qry(int l, int r) { // [l, r)
        ll s = 0; for (l+=n, r+=n; l<r; l>>=1, r>>=1) {
            if (l&1) s += t[l++]; if (r&1) s += t[--r]; }
        return s;
    }
};
```

**Modular exponentiation**
```cpp
long long modpow(long long b, long long e, long long mod) {
    long long r = 1 % mod;
    for (; e; e >>= 1) { if (e & 1) r = r * b % mod; b = b * b % mod; }
    return r;
}
```

## Common algorithms (Python)

**Prefix sums**
```python
p = [0]
for x in a: p.append(p[-1] + x)        # sum(l..r) = p[r+1] - p[l]
```

**Two pointers / sliding window**
```python
l = 0
for r in range(n):
    # extend window with a[r]
    while l <= r and not good():
        # shrink: remove a[l]; l += 1
```

**Knapsack 0/1**
```python
dp = [0] * (W + 1)
for w, v in items:
    for s in range(W, w - 1, -1):
        dp[s] = max(dp[s], dp[s - w] + v)
```

## Bit tricks
- `n & (n - 1)` clears the lowest set bit; `n & -n` isolates it.
- iterate subsets: `for s in range(1, 1 << n)` and `sub = s; while sub: ... sub = (sub-1) & s`.
- check bit k: `x >> k & 1`.

## Judging notes
- The judge compares outputs **token-wise** or **exactly** (Settings).
- Use the **Stress tester** when your fast solution fails a hidden case.
- **Competition Mode**: paste a contest link → problems + samples are downloaded
  and judged with the same engine used in Practice.
"""


class _CheatPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QTextBrowser

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        viewer = QTextBrowser()
        viewer.setOpenExternalLinks(False)
        viewer.setStyleSheet("QTextBrowser { background:#1e1f24; color:#dfe1e8;"
                             " border:1px solid #3a3d46; border-radius:4px; }")
        html = ("<style>"
                "body { font-family:'Segoe UI', sans-serif; font-size:13px; background:#1e1f24; }"
                "h1,h2,h3 { color:#e3b341; } h1 { font-size:19px; }"
                "pre { background:#26272e; padding:10px; border-radius:5px;"
                " font-family:'DejaVu Sans Mono', monospace; font-size:12px; }"
                "code { background:#26272e; padding:1px 4px; border-radius:3px;"
                " font-family:'DejaVu Sans Mono', monospace; }"
                "p { margin:6px 0; }"
                "</style>" + md_to_html(_CHEATSHEET_MD))
        viewer.setHtml(html)
        lay.addWidget(viewer)


# ===========================================================================
# The tab itself
# ===========================================================================
class ToolsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        self.tabs = QTabWidget()
        self.snippets_page = _SnippetsPage()
        self.templates_page = _TemplatesPage()
        self.stress_page = _StressPage()
        self.gen_page = _GenPage()
        self.math_page = _MathPage()
        self.cheat_page = _CheatPage()
        self.tabs.addTab(self.templates_page, "Starter templates")
        self.tabs.addTab(self.snippets_page, "Snippets")
        self.tabs.addTab(self.stress_page, "Stress tester")
        self.tabs.addTab(self.gen_page, "Random tests")
        self.tabs.addTab(self.math_page, "Math helpers")
        self.tabs.addTab(self.cheat_page, "Cheatsheet")
        root.addWidget(self.tabs, 1)