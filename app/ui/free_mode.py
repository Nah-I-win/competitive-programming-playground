"""Free Mode: a general-purpose scratchpad. Write any Python or C++ code,
feed it custom stdin, run it with the same sandboxed engine used for
judging — no problem, no test comparison needed."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGroupBox,
                               QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QSplitter, QVBoxLayout,
                               QWidget)

from .. import db as dbmod
from ..workers import Job, pool
from .widgets import CodeEditor


class FreeModeTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = dbmod.get_db()
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        bar = QHBoxLayout()
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Python", "Python")
        self.lang_combo.addItem("C++", "C++")
        self.tl_spin = QSpinBox()
        self.tl_spin.setRange(100, 30000)
        self.tl_spin.setValue(2000)
        self.tl_spin.setSuffix(" ms")
        self.mem_spin = QSpinBox()
        self.mem_spin.setRange(64, 1024)
        self.mem_spin.setValue(256)
        self.mem_spin.setSuffix(" MB")
        self.btn_run = QPushButton("▶ Run")
        self.btn_run.setStyleSheet("background:#2b5da8; color:white; font-weight:600;")
        self.btn_clear = QPushButton("Clear output")
        self.btn_open = QPushButton("Open file…")
        self.btn_save = QPushButton("Save…")
        self.snippet_combo = QComboBox()
        self.snippet_combo.setMinimumWidth(200)
        self.snippet_combo.addItem("insert snippet…", None)

        bar.addWidget(QLabel("language"))
        bar.addWidget(self.lang_combo)
        bar.addWidget(self.tl_spin)
        bar.addWidget(self.mem_spin)
        bar.addWidget(self.btn_run)
        bar.addWidget(self.snippet_combo)
        bar.addStretch(1)
        bar.addWidget(self.btn_open)
        bar.addWidget(self.btn_save)
        bar.addWidget(self.btn_clear)
        root.addLayout(bar)

        # editor (fills most of the space)
        self.editor = CodeEditor()
        self.editor.set_language("Python")
        self.editor.setPlainText(_FREE_PY_SCAFFOLD)
        root.addWidget(self.editor, 4)

        # stdin + output
        split = QSplitter(Qt.Orientation.Horizontal)
        in_box = QGroupBox("Standard input")
        in_lay = QVBoxLayout(in_box)
        self.stdin_edit = QPlainTextEdit()
        self.stdin_edit.setPlaceholderText("type stdin here (empty is fine)…")
        in_lay.addWidget(self.stdin_edit)
        out_box = QGroupBox("Output")
        out_lay = QVBoxLayout(out_box)
        self.out_view = QPlainTextEdit()
        self.out_view.setReadOnly(True)
        out_lay.addWidget(self.out_view)
        split.addWidget(in_box)
        split.addWidget(out_box)
        split.setSizes([400, 600])
        root.addWidget(split, 3)

        # wiring
        self.btn_run.clicked.connect(self.run_code)
        self.btn_clear.clicked.connect(lambda: self.out_view.clear())
        self.btn_open.clicked.connect(self.open_file)
        self.btn_save.clicked.connect(self.save_file)
        self.lang_combo.currentIndexChanged.connect(self._on_lang)
        self.snippet_combo.currentIndexChanged.connect(self._insert_snippet)
        self._feed_snippets()

    # ------------------------------------------------------------------
    def _on_lang(self) -> None:
        lang = self.lang_combo.currentData()
        self.editor.set_language(lang)
        if not self.editor.toPlainText().strip():
            self.editor.setPlainText(_FREE_PY_SCAFFOLD if lang == "Python"
                                     else _FREE_CPP_SCAFFOLD)

    def _feed_snippets(self) -> None:
        current = self.snippet_combo.currentData()
        self.snippet_combo.blockSignals(True)
        self.snippet_combo.clear()
        self.snippet_combo.addItem("insert snippet…", None)
        for s in self.db.snippets():
            self.snippet_combo.addItem(f"{s['name']} ({s['language']})",
                                       ("snippet", s["id"], s["content"]))
        # restore selection display
        if current is not None:
            idx = self.snippet_combo.findData(current)
            if idx >= 0:
                self.snippet_combo.setCurrentIndex(idx)
        self.snippet_combo.blockSignals(False)

    def _insert_snippet(self) -> None:
        data = self.snippet_combo.currentData()
        if not data:
            return
        self.snippet_combo.setCurrentIndex(0)
        _, _, content = data
        self.editor.insert_from_template(content)

    # ------------------------------------------------------------------
    def run_code(self) -> None:
        code = self.editor.toPlainText()
        if not code.strip():
            QMessageBox.information(self, "Empty editor", "Write some code first.")
            return
        lang = self.lang_combo.currentData()
        self.out_view.setPlainText(
            f"$ {lang} … running (limit {self.tl_spin.value()} ms / "
            f"{self.mem_spin.value()} MB)…")
        job = Job(_run_free, code, lang, self.stdin_edit.toPlainText(),
                  self.tl_spin.value(), self.mem_spin.value())
        job.signals.done.connect(self._on_run_done)
        job.signals.error.connect(self._on_run_error)
        pool().start(job)

    def _on_run_done(self, r) -> None:
        lang = self.lang_combo.currentData()
        lines = [f"$ {lang} finished in {r.time_ms:.0f} ms, "
                 f"{r.memory_kb / 1024:.1f} MB"]
        if r.timed_out:
            lines.append(f"✘ TIME LIMIT EXCEEDED ({self.tl_spin.value()} ms)")
        elif r.returncode != 0:
            lines.append(f"✘ exit code {r.returncode}")
            if r.stderr:
                lines.append("── stderr ──")
                lines.append(r.stderr)
            lines.append("── stdout ──")
            lines.append(r.stdout or "(none)")
        else:
            if r.stderr:
                lines.append("── stderr ──")
                lines.append(r.stderr)
            lines.append("── stdout ──")
            lines.append(r.stdout or "(empty)")
        self.out_view.setPlainText("\n".join(lines) + ("\n" if lines[-1] else ""))

    def _on_run_error(self, msg: str) -> None:
        self.out_view.setPlainText(f"error: {msg}")

    # ------------------------------------------------------------------
    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open code file", "", "Source files (*.py *.cpp *.txt);;All files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        lang = "Python" if path.endswith(".py") else "C++"
        idx = self.lang_combo.findData(lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.editor.setPlainText(text)
        self.stdin_edit.clear()
        self.out_view.clear()

    def save_file(self) -> None:
        ext = ".py" if self.lang_combo.currentData() == "Python" else ".cpp"
        path, _ = QFileDialog.getSaveFileName(self, "Save code", f"free_code{ext}")
        if not path:
            return
        try:
            from ..core.util import atomic_write_text
            atomic_write_text(path, self.editor.toPlainText())
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.out_view.setPlainText(f"saved to {path}")


def _run_free(code: str, lang: str, stdin_text: str,
              tlm: int, mmb: int, progress=None):
    from ..core.judge import run_standalone
    return run_standalone(code, lang, stdin_text, time_limit_ms=tlm, memory_mb=mmb)


_FREE_PY_SCAFFOLD = '''import sys

def main():
    # read all input
    data = sys.stdin.buffer.read().split()
    # ... your arbitrary Python code here ...
    print("Hello from Free Mode!")

if __name__ == "__main__":
    main()
'''

_FREE_CPP_SCAFFOLD = r'''#include <bits/stdc++.h>
using namespace std;

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    // ... your arbitrary C++ code here ...
    cout << "Hello from Free Mode!" << "\n";
    return 0;
}
'''