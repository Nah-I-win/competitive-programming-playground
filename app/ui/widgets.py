"""Shared UI widgets: syntax-highlighted code editor, statement viewer."""
from __future__ import annotations

import re

from PySide6.QtCore import QRect, Qt, QSize
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QSyntaxHighlighter,
                           QTextCharFormat, QTextFormat)
from PySide6.QtWidgets import (QPlainTextEdit, QTextBrowser, QWidget)

FONT_FAMILY = "Menlo, Consolas, DejaVu Sans Mono, monospace"
EDITOR_FONT = QFont("DejaVu Sans Mono", 11)
EDITOR_FONT.setStyleHint(QFont.StyleHint.Monospace)


# ---------------------------------------------------------------------------
# Syntax highlighters
# ---------------------------------------------------------------------------
class _BaseHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)
        self._rules: list[tuple[re.Pattern, QTextCharFormat]] = []
        base = QTextCharFormat()

    def add_rule(self, pattern: str, fmt: QTextCharFormat, flags: int = 0):
        self._rules.append((re.compile(pattern, flags | re.MULTILINE), fmt))

    def highlightBlock(self, text: str):  # noqa: N802
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


def _fmt(color: str, bold=False, italic=False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    f.setFontItalic(italic)
    return f


class PythonHighlighter(_BaseHighlighter):
    def __init__(self, parent):
        super().__init__(parent)
        self.add_rule(r'\b(?:def|class|return|if|elif|else|for|while|in|not|and|or|is|None|True|False|import|from|as|with|try|except|finally|raise|global|nonlocal|lambda|pass|break|continue|yield|assert|del)\b', _fmt("#0072bd", bold=True))
        self.add_rule(r'\b(?:print|len|range|int|float|str|list|dict|set|tuple|sum|min|max|abs|sorted|enumerate|zip|map|filter|open|input|repr|bool|type|isinstance|any|all|reversed|round)\b', _fmt("#1a6e1d"))
        self.add_rule(r'#[^\n]*', _fmt("#8a8a8a", italic=True))
        self.add_rule(r'"""(?:[^"\\]|\\.|"(?!""))*"""|\'\'\'(?:[^\'\\]|\\.|\'(?!\'\'))*\'\'\'', _fmt("#b7561b"))
        self.add_rule(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'', _fmt("#b7561b"))
        self.add_rule(r'\b\d+(?:\.\d+)?\b', _fmt("#a72247"))
        self.add_rule(r'@\w+', _fmt("#7d4fb6"))
        self.add_rule(r'\b[A-Za-z_]\w*(?=\s*\()', _fmt("#7d4fb6"))


class CppHighlighter(_BaseHighlighter):
    def __init__(self, parent):
        super().__init__(parent)
        self.add_rule(r'\b(?:return|if|else|for|while|do|break|continue|struct|class|namespace|using|typedef|template|typename|public|private|protected|virtual|const|static|inline|new|delete|this|auto|void|int|long|short|char|float|double|bool|unsigned|signed|size_t|string|vector|map|set|pair|stack|queue|deque|unordered_map|unordered_set|priority_queue|true|false|nullptr|constexpr|enum|switch|case|default|operator|friend|throw|try|catch)\b', _fmt("#0072bd", bold=True))
        self.add_rule(r'\b(?:cin|cout|endl|cerr|clog|printf|scanf|getline|sort|reverse|swap|min|max|abs|lower_bound|upper_bound|binary_search|accumulate|to_string|stoi|stoll|cbegin|cend|begin|end|push_back|push|pop|top|front|back|size|empty|clear|insert|erase|find|count|resize|reserve|emplace_back|make_pair|make_tuple|tie|iota|fill|copy|unique|next_permutation|gcd|lcm|pow|sqrt|log2|floor|ceil)\b', _fmt("#1a6e1d"))
        self.add_rule(r'//[^\n]*', _fmt("#8a8a8a", italic=True))
        self.add_rule(r'/\*.*?\*/', _fmt("#8a8a8a", italic=True), re.S)
        self.add_rule(r'"(?:[^"\\\n]|\\.)*"', _fmt("#b7561b"))
        self.add_rule(r"'\\?[^']'", _fmt("#b7561b"))
        self.add_rule(r'\b\d+(?:\.\d+)?[uUlLfF]*\b', _fmt("#a72247"))
        self.add_rule(r'#[a-zA-Z_]+', _fmt("#7d4fb6"))


# ---------------------------------------------------------------------------
# Code editor with line numbers
# ---------------------------------------------------------------------------
class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighter: _BaseHighlighter | None = None
        self._lang = "Python"
        self.setFont(EDITOR_FONT)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(' '))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setStyleSheet(
            "QPlainTextEdit { background: #1e1f24; color: #dfe1e8;"
            " border: 1px solid #3a3d46; border-radius: 4px; }")
        self.line_number_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self._highlight_cursor_line)
        self.update_line_number_area_width(0)

    def set_language(self, lang: str) -> None:
        self._lang = lang
        if lang == "C++":
            self.highlighter = CppHighlighter(self.document())
        else:
            self.highlighter = PythonHighlighter(self.document())

    def insert_from_template(self, text: str) -> None:
        cursor = self.textCursor()
        cursor.insertText(text if text.endswith("\n") else text + "\n")

    # -- line numbers -------------------------------------------------------
    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 12 + self.fontMetrics().horizontalAdvance('9') * digits

    def update_line_number_area_width(self, _=0) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def _paint_line_numbers(self, event) -> None:
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#25262c"))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#5c5f6d"))
                painter.drawText(0, top, self.line_number_area.width() - 6,
                                 self.fontMetrics().height(), 0x0002, str(block_number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
        painter.end()

    def _highlight_cursor_line(self) -> None:
        from PySide6.QtWidgets import QTextEdit
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor("#2a2c34"))
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel])


class _LineNumberArea(QWidget):
    def __init__(self, editor: CodeEditor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):  # noqa: N802
        self.editor._paint_line_numbers(event)


# ---------------------------------------------------------------------------
# Statement viewer (rich text for CF/LC HTML, markdown for Codewars, plain text)
# ---------------------------------------------------------------------------
_STYLE = """
<style>
body { font-family: 'Segoe UI', sans-serif; font-size: 12.5px; color: #dfe1e8; }
h1 { font-size: 17px; } h2 { font-size: 15px; } h3 { font-size: 13.5px; }
pre { background: #26272e; padding: 8px; border-radius: 4px; font-family: 'DejaVu Sans Mono', monospace; }
code { background: #26272e; padding: 1px 4px; border-radius: 3px; font-family: 'DejaVu Sans Mono', monospace; }
table.samples { border-collapse: collapse; } table.samples td { border: 1px solid #444; padding: 6px; vertical-align: top; }
</style>
"""


class StatementViewer(QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setStyleSheet(
            "QTextBrowser { background: #1e1f24; color: #dfe1e8;"
            " border: 1px solid #3a3d46; border-radius: 4px; }")

    def show_plain(self, text: str) -> None:
        html = _STYLE + "<body>" + _escape(text).replace("\n", "<br>") + "</body>"
        self.setHtml(html)

    def show_statement(self, statement: str | None, is_html: bool = False,
                       title: str = "", meta_lines: list[str] = None) -> None:
        head = f"<h1>{_escape(title)}</h1>" if title else ""
        if meta_lines:
            head += "<p style='color:#9aa0ad;'>" + "<br>".join(_escape(m) for m in meta_lines) + "</p>"
        if is_html:
            self.setHtml(_STYLE + head + (statement or "<i>No statement available.</i>"))
        else:
            self.show_plain(statement or "No statement available.", title=head)


def _escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))