"""Small shared helpers: HTML/markdown conversion, formatting, atomic files."""
from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser

_WS_RE = re.compile(r"[ \t\r\f\v]+")


class _TextExtractor(HTMLParser):
    """Strip tags turning block elements into newlines (for statements/preview)."""

    BLOCK_TAGS = {
        "p", "div", "br", "h1", "h2", "h3", "h4", "pre", "ul", "ol", "li",
        "table", "tr", "section", "span class=", "blockquote", "hr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._in_pre = 0
        self._last_block = False

    def handle_starttag(self, tag: str, attrs: list) -> None:  # noqa: N802
        tag = tag.lower()
        if tag == "pre":
            self._in_pre += 1
            self._newline()
        elif tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "blockquote"):
            self._newline()

    def handle_endtag(self, tag: str) -> None:  # noqa: N802
        tag = tag.lower()
        if tag == "pre":
            self._in_pre = max(0, self._in_pre - 1)
            self._newline()
        elif tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "blockquote"):
            self._newline()

    def handle_data(self, data: str) -> None:  # noqa: N802
        if self._in_pre:
            self.parts.append(data)
        else:
            text = _WS_RE.sub(" ", data)
            if text.strip():
                if self.parts and not self.parts[-1].endswith("\n"):
                    self.parts.append(" ")
                self.parts.append(text)

    def _newline(self) -> None:
        if self.parts and not self.parts[-1].rstrip().endswith("\n"):
            self.parts.append("\n")

    def text(self) -> str:
        out = "".join(self.parts)
        # collapse 3+ blank lines
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out.strip()


def html_to_text(html_text: str, max_len: int = 0) -> str:
    p = _TextExtractor()
    try:
        p.feed(html_text or "")
        p.close()
    except Exception:
        pass
    out = p.text() or ""
    if max_len and len(out) > max_len:
        out = out[:max_len] + "…"
    return out


# ---------------------------------------------------------------------------
# Minimal markdown -> HTML (used for Codewars descriptions / notes / cheatsheet)
# ---------------------------------------------------------------------------
_MD_CODE = re.compile(r"```(\w+)?\n(.*?)```", re.S)
_MD_INLINE = re.compile(r"`([^`\n]+)`")


def _md_codeblock(m: re.Match) -> str:
    lang = m.group(1) or ""
    code = _html.escape(m.group(2))
    cls = f' class="lang-{lang}"' if lang else ""
    return f"<pre{cls}>{code}</pre>"


def _md_inline(m: re.Match) -> str:
    return f"<code>{_html.escape(m.group(1))}</code>"


def md_to_html(md: str) -> str:
    if not md:
        return ""
    md = _MD_CODE.sub(_md_codeblock, md)
    md = _MD_INLINE.sub(_md_inline, md)
    html_parts: list[str] = []
    in_list: str | None = None
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            if in_list:
                html_parts.append(f"</{in_list}>")
                in_list = None
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            if in_list:
                html_parts.append(f"</{in_list}>")
                in_list = None
            level = len(heading.group(1))
            html_parts.append(f"<h{level}>{heading.group(2)}</h{level}>")
            continue
        ul = re.match(r"^\s*[-*]\s+(.*)$", line)
        if ul:
            if in_list != "ul":
                if in_list:
                    html_parts.append(f"</{in_list}>")
                html_parts.append("<ul>")
                in_list = "ul"
            html_parts.append(f"<li>{ul.group(1)}</li>")
            continue
        ol = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if ol:
            if in_list != "ol":
                if in_list:
                    html_parts.append(f"</{in_list}>")
                html_parts.append("<ol>")
                in_list = "ol"
            html_parts.append(f"<li>{ol.group(1)}</li>")
            continue
        if in_list:
            html_parts.append(f"</{in_list}>")
            in_list = None
        if line.startswith("<") and "</" in line[-12:]:
            html_parts.append(line)          # already html
        else:
            html_parts.append(f"<p>{line}</p>")
    if in_list:
        html_parts.append(f"</{in_list}>")
    return "\n".join(html_parts)


# ---------------------------------------------------------------------------
# Numbers / time formatting / utf-8 files
# ---------------------------------------------------------------------------
def fmt_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def fmt_countdown(seconds: int) -> str:
    """Countdown like 2d 03:12:45; negative -> 0d 00:00:00."""
    seconds = max(0, int(seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h:02d}:{m:02d}:{s:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_dt(unix: Optional[int]) -> str:
    if not unix:
        return "—"
    return time_str(unix)


def time_str(unix: int) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(unix).strftime("%Y-%m-%d %H:%M")


def atomic_write_text(path, text: str) -> None:
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)