"""Auto-harness for LeetCode-style function problems.

LeetCode problems ask you to implement a `Solution` method, but our local judge
feeds stdin and compares stdout. For Python we append a tiny harness that reads
`name = value` lines from stdin, calls `Solution().<method>(**kwargs)` and
prints the result back in LeetCode's compact notation.

When the sample input is raw (no `name =` lines) or the signature involves
custom nodes (ListNode/TreeNode), no harness is generated and the code runs as
a plain stdin/stdout program instead.
"""
from __future__ import annotations

import json
import re
from typing import Optional

_HARNESS = '''\
import sys as _sys
import ast as _ast
import re as _re

def _fmt(x, _top=True):
    if x is None:
        return "null"
    if x is True:
        return "true"
    if x is False:
        return "false"
    if isinstance(x, (int, float)):
        return str(x)
    if isinstance(x, str):
        return x if _top else json.dumps(x)
    if isinstance(x, (list, tuple)):
        return "[" + ",".join(_fmt(v, False) for v in x) + "]"
    if isinstance(x, dict):
        return "{" + ",".join(_fmt(k, False) + ":" + _fmt(v, False) for k, v in x.items()) + "}"
    return str(x)

def _parse_kwargs(text):
    kwargs = {}
    parts = _re.split(r"(?<![A-Za-z0-9_])([A-Za-z_]\\w*)\\s*=", text)
    lead = parts[0].strip()
    if lead and not lead.startswith("#") and "=" in text:
        pass
    i = 1
    while i + 1 < len(parts):
        key = parts[i].strip()
        val = parts[i + 1].strip().strip(",").strip()
        if key:
            kwargs[key] = _ast.literal_eval(val)
        i += 2
    return kwargs

def _solve():
    kwargs = {}
    for _line in _sys.stdin.read().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#"):
            continue
        _line = _re.sub(r"^(Input|Output|Explanation)\\s*:", "", _line)
        if "=" in _line:
            kwargs.update(_parse_kwargs(_line))
    _obj = Solution()
    _ans = _obj.__FN__(**kwargs)
    __VOID_LINE__
    _sys.stdout.write(_fmt(_ans))

_solve()
'''

_HARNESS_HEADER = "import json\n"


def parse_meta(meta: Optional[str]) -> Optional[dict]:
    if not meta:
        return None
    try:
        data = json.loads(meta)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def function_name_from_code(code: str) -> Optional[str]:
    m = re.search(r"\bdef\s+(\w+)\s*\(", code)
    return m.group(1) if m else None


def needs_harness(problem_meta: Optional[str], input_text: str) -> bool:
    """True if this LC problem should run through the auto-harness."""
    meta = parse_meta(problem_meta)
    if meta:
        param_types = " ".join(str(p.get("type", "")) for p in meta.get("params", []))
        if any(t in param_types for t in ("ListNode", "TreeNode", "Node")):
            return False
    return "=" in input_text


def build_python_harness(code: str, problem_meta: Optional[str]) -> Optional[str]:
    """Return code + harness, or None when a harness isn't applicable."""
    meta = parse_meta(problem_meta)
    fn = None
    if meta and isinstance(meta.get("name"), str):
        fn = meta["name"]
    else:
        fn = function_name_from_code(code)
    if not fn or not re.match(r"^[A-Za-z_]\w*$", fn):
        return None

    result_line = "pass"
    if meta:
        ret = meta.get("return") or {}
        if ret.get("type") == "void":
            params = meta.get("params") or []
            last_key = params[-1]["name"] if params else "s"
            result_line = f'_ans = kwargs.get("{last_key}", _ans)'
    harness = _HARNESS.replace("__FN__", fn).replace("__VOID_LINE__", result_line)
    if "import json" not in code:
        harness = _HARNESS_HEADER + harness
    return code.rstrip() + "\n\n" + harness


def problem_supported(problem: dict) -> bool:
    """Whether the LC harness applies to this problem (for UI hints)."""
    if problem.get("source") != "leetcode":
        return False
    samples = problem.get("samples") or []
    return any(needs_harness(problem.get("meta"), s.get("input", "")) for s in samples)