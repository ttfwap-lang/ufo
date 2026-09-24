"""Repo-wide static review: compile, stub detection, secret scan, hygiene.

Run:  python review_repo.py            (human report)
      python review_repo.py --json     (machine readable)

This is intentionally dependency-free so it runs in the project venv without
touching the vendored open-source tree's test suite.
"""
from __future__ import annotations

import ast
import io
import json
import os
import re
import sys
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.abspath(__file__))

# Vendored upstream / non-ours: not reviewed line by line.
SKIP_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".idea", ".poolside", "logs", "data",
    "ufo_skill_state", ".claude",
}

SECRET_PATTERNS = [
    (r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b", "telegram bot token"),
    (r"sk-[A-Za-z0-9]{20,}", "openai-style key"),
    (r"ghp_[A-Za-z0-9]{36}", "github token"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "private key"),
    (r"\bAKIA[0-9A-Z]{16}\b", "aws access key"),
    (r"(?i)\b(?:password|passwd|secret|api[_-]?key)\s*=\s*['\"][^'\"]{8,}['\"]",
     "hardcoded credential"),
]

STUB_MARKERS = ("TO" + "DO", "FIX" + "ME", "X" + "XX", "HA" + "CK",
                "NotImplemented", "place" + "holder")
# This file contains the marker literals themselves; scanning it would report
# its own constant as a stub, so it is excluded from the marker sweep.
SELF = os.path.basename(__file__)


def py_files() -> List[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return out


def ps1_files() -> List[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".ps1"):
                out.append(os.path.join(dirpath, fn))
    return out


def rel(p: str) -> str:
    return os.path.relpath(p, ROOT).replace("\\", "/")


def compile_check(paths: List[str]) -> List[Dict[str, Any]]:
    bad = []
    for p in paths:
        try:
            src = io.open(p, encoding="utf-8", errors="replace").read()
            compile(src, p, "exec")
        except SyntaxError as e:
            bad.append({"file": rel(p), "line": e.lineno, "error": str(e)})
        except Exception as e:                       # noqa: BLE001
            bad.append({"file": rel(p), "line": 0, "error": f"{type(e).__name__}: {e}"})
    return bad


def ast_checks(paths: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    stubs, empties, bare_except, mutable_default = [], [], [], []
    for p in paths:
        try:
            tree = ast.parse(io.open(p, encoding="utf-8", errors="replace").read())
        except Exception:                             # already reported
            continue
        src = io.open(p, encoding="utf-8", errors="replace").read()
        if os.path.basename(p) == SELF:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            for marker in STUB_MARKERS:
                if marker in line:
                    stubs.append({"file": rel(p), "line": i, "marker": marker,
                                  "text": line.strip()[:120]})
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body = [n for n in node.body
                        if not (isinstance(n, ast.Expr) and
                                isinstance(n.value, ast.Constant))]
                if not body:
                    empties.append({"file": rel(p), "line": node.lineno,
                                    "name": node.name})
                elif len(body) == 1 and isinstance(body[0], ast.Pass):
                    # a function whose only statement is `pass`
                    if not any(isinstance(n, ast.Expr) and
                               isinstance(n.value, ast.Constant) and
                               isinstance(n.value.value, str)
                               for n in node.body):
                        empties.append({"file": rel(p), "line": node.lineno,
                                        "name": node.name + " (pass-only)"})
                defaults = list(node.args.defaults) + \
                    [d for d in node.args.kw_defaults if d is not None]
                for d in defaults:
                    if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                        mutable_default.append({"file": rel(p),
                                                "line": getattr(d, "lineno", node.lineno),
                                                "name": node.name})
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                bare_except.append({"file": rel(p),
                                    "line": node.lineno})
    return {"stub_markers": stubs, "empty_functions": empties,
            "bare_except": bare_except, "mutable_defaults": mutable_default}


def secret_scan(paths: List[str]) -> List[Dict[str, Any]]:
    hits = []
    for p in paths:
        try:
            text = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:                             # noqa: BLE001
            continue
        for pat, kind in SECRET_PATTERNS:
            for m in re.finditer(pat, text):
                line = text.count("\n", 0, m.start()) + 1
                snippet = m.group(0)[:12] + "..." + m.group(0)[-4:]
                hits.append({"file": rel(p), "line": line, "kind": kind,
                             "snippet": snippet})
    return hits


def hygiene() -> Dict[str, Any]:
    gitignore = os.path.join(ROOT, ".gitignore")
    ignored = io.open(gitignore, encoding="utf-8").read() if os.path.exists(gitignore) else ""
    tracked = os.popen(f'git -C "{ROOT}" ls-files').read().splitlines()
    suspicious = []
    for f in tracked:
        base = os.path.basename(f)
        if re.search(r"(token|secret|\.env$|credential)", base, re.I) and \
                base not in ignored:
            suspicious.append(f)
        if f.endswith((".png", ".jpg")) and ("astro_vshot_" in f or
                                             f.startswith("c_")):
            suspicious.append(f + "  (debug artifact)")
    return {
        "gitignore_present": bool(ignored),
        "tracked_count": len(tracked),
        "suspicious_tracked": suspicious,
    }


def main() -> None:
    as_json = "--json" in sys.argv
    paths = py_files()
    report = {
        "python_files": len(paths),
        "powershell_files": len(ps1_files()),
        "compile_errors": compile_check(paths),
        "ast": ast_checks(paths),
        "secrets": secret_scan(paths + ps1_files()),
        "hygiene": hygiene(),
    }
    if as_json:
        print(json.dumps(report, indent=2))
        return

    print(f"python files scanned : {report['python_files']}")
    print(f"powershell files     : {report['powershell_files']}")
    ce = report["compile_errors"]
    print(f"\nCOMPILE ERRORS: {len(ce)}")
    for e in ce:
        print(f"  {e['file']}:{e['line']}  {e['error']}")

    a = report["ast"]
    for key, label in (("stub_markers", "stub markers"),
                       ("empty_functions", "empty / pass-only functions"),
                       ("bare_except", "bare except"),
                       ("mutable_defaults", "mutable default args")):
        items = a[key]
        print(f"\n{label.upper()}: {len(items)}")
        for it in items[:40]:
            loc = f"{it.get('file')}:{it.get('line', '?')}"
            extra = it.get("marker") or it.get("name") or ""
            print(f"  {loc}  {extra}")

    s = report["secrets"]
    print(f"\nSECRET PATTERNS: {len(s)}")
    for it in s:
        print(f"  {it['file']}:{it['line']}  {it['kind']}  {it['snippet']}")

    h = report["hygiene"]
    print(f"\nHYGIENE: tracked={h['tracked_count']} "
          f"gitignore={'yes' if h['gitignore_present'] else 'NO'}")
    for f in h["suspicious_tracked"][:40]:
        print(f"  {f}")


if __name__ == "__main__":
    main()
