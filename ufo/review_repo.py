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

# (pattern, kind, structured)
#   structured=True means the shape is specific enough that a match is itself
#   meaningful, so placeholder filtering must NOT be applied. A Telegram token
#   is <digits>:<35 base64url chars>; a real one can legitimately contain only a
#   few distinct characters, and an entropy heuristic silently swallowed one
#   during testing. Never second-guess a structured match.
SECRET_PATTERNS = [
    (r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b", "telegram bot token", True),
    # The next few were added AFTER GitHub push protection caught a real leak
    # this scanner had missed: an OpenRouter key and a Qwen/DashScope token in a
    # stray result.json. A scanner that only knows `sk-` is a weaker check that
    # gives false confidence, not a replacement for push protection.
    (r"\bsk-or-v1-[A-Za-z0-9]{20,}\b", "openrouter api key", True),
    (r"\bAIza[0-9A-Za-z_\-]{30,}\b", "google api key", True),
    (r"\bAQ\.[A-Za-z0-9_\-]{40,}\b", "qwen/dashscope api token", True),
    (r"\bghp_[A-Za-z0-9]{36}\b", "github token", True),
    (r"\bAKIA[0-9A-Z]{16}\b", "aws access key", True),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "private key", True),
    (r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b", "anthropic api key", True),
    (r"\bsk-[A-Za-z0-9]{32,}\b", "openai-style key", True),
    # Generic: matches any credential-shaped assignment, so it needs filtering.
    (r"(?i)\b(?:password|passwd|secret|api[_-]?key|token)\s*=\s*['\"][^'\"]{8,}['\"]",
     "hardcoded credential", False),
]

# Obvious test/dummy values that match a credential shape but are not secrets.
# Without this the report fills with noise from upstream test fixtures and the
# real findings stop being read.
CREDENTIAL_PLACEHOLDER = re.compile(
    r"(?i)^(?:x{3,}|\*{3,}|test|dummy|fake|example|placeholder|your[-_ ]?|"
    r"sk-local|sk-test|sk-fake|local|changeme|none|null|abc123|1234567890|"
    r"test[-_](?:key|token|secret|password)|"
    r"hf_[a-z]{4,}|token|secret|password|key)$"
)

# Dictionary words do not occur inside a genuine high-entropy key, so their
# presence marks a value as a readable fixture label rather than a credential.
DESCRIPTIVE = ("test", "dummy", "fake", "example", "sample", "mock",
               "placeholder", "changeme", "real-cloud", "your", "notreal",
               "redacted", "insert", "replace", "xxxx", "aaaa")


def is_placeholder(snippet: str, line_text: str = "") -> bool:
    """True if a generic (unstructured) match is obviously a fixture.

    `line_text` is the source line the match came from. A fixture almost always
    says so nearby - tests/unit/test_redact.py literally reads
    `TOKEN = "0123456789abcdef" * 3  # fake 48-hex token` - and the value alone
    gives no hint, because a fake hex string is indistinguishable from a real
    one by shape.
    """
    # The generic pattern captures a whole assignment, e.g. api_key="test-key".
    # Judge the quoted value, not the variable name.
    m = re.search(r"""['"]([^'"]{1,200})['"]\s*$""", snippet)
    body = m.group(1) if m else snippet
    body = body.strip("\"'")
    if CREDENTIAL_PLACEHOLDER.match(body):
        return True
    # Judge each hyphen/underscore/dot segment too, so "sk-real-cloud-key" is
    # recognised even when an earlier segment would have been trimmed.
    segments = re.split(r"[-_.:/ ]", body.lower())
    if any(seg in DESCRIPTIVE for seg in segments if seg):
        return True
    low = body.lower()
    if any(w in low for w in DESCRIPTIVE):
        return True
    # Surrounding context. Restrict to comments/docstrings so a real secret is
    # not excused merely because its file mentions "test" somewhere.
    if line_text:
        tail = line_text.strip()
        for marker in ("#", '"""', "'''"):
            idx = tail.find(marker)
            if idx != -1:
                comment = tail[idx:].lower()
                if any(w in comment for w in
                       ("fake", "dummy", "example", "sample", "mock",
                        "placeholder", "not a real", "notreal", "for test",
                        "unit test", "redacted")):
                    return True
    return False

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


# Reviewed false positives. Each is a benign shape that no amount of value
# inspection can distinguish from a credential, so they are allowlisted with a
# reason rather than handled by loosening the heuristics. Loosening is how a
# secret scanner starts missing real secrets: every extra exception is a hole.
# Keyed on (file suffix, stable code fragment) so line-number drift is harmless.
SECRET_ALLOWLIST = [
    ("client/client.py", "'token=' not in args.ws_server_url",
     "substring test that keeps a token out of the process list"),
    ("tests/unit/test_redact.py", "ws?token=",
     "redaction unit test asserting a literal fake token is masked"),
    ("tests/test_endpoint_dgx.py", 'api_key="',
     "upstream fixture using a descriptive non-secret label"),
]


def is_allowlisted(path: str, line_text: str) -> bool:
    for suffix, fragment, _reason in SECRET_ALLOWLIST:
        if path.replace("\\", "/").endswith(suffix) and fragment in line_text:
            return True
    return False


def secret_scan(paths: List[str]) -> List[Dict[str, Any]]:
    hits = []
    # This file and its self-test contain credential-shaped strings on purpose.
    # Scanning them guarantees noise and guarantees a finding nobody reads.
    self_names = {os.path.basename(__file__), "test_secret_scan.py"}
    for p in paths:
        if os.path.basename(p) in self_names:
            continue
        try:
            text = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:                             # noqa: BLE001
            continue
        lines = text.splitlines()
        for pat, kind, structured in SECRET_PATTERNS:
            for m in re.finditer(pat, text):
                value = m.group(0)
                # Only the generic assignment pattern needs fixture filtering.
                # A structured match (telegram token, sk-or-v1, AIza, AQ, ...)
                # is already specific enough to trust.
                if not structured:
                    line_no = text.count("\n", 0, m.start())
                    line_text = lines[line_no] if line_no < len(lines) else ""
                    if is_placeholder(value, line_text) or \
                            is_allowlisted(p, line_text):
                        continue
                line = text.count("\n", 0, m.start()) + 1
                # Never print the secret itself - only enough to locate it.
                snippet = value[:6] + "..." + value[-3:]
                hits.append({"file": rel(p), "line": line, "kind": kind,
                             "snippet": snippet})
    return hits


def hygiene() -> Dict[str, Any]:
    gitignore = os.path.join(ROOT, ".gitignore")
    ignored = io.open(gitignore, encoding="utf-8").read() if os.path.exists(gitignore) else ""
    tracked = os.popen(f'git -C "{ROOT}" ls-files').read().splitlines()
    suspicious = []
    # A file whose NAME contains "token" is usually a secret, but sometimes it
    # is the tool that hunts for secrets. Do not cry wolf on our own tooling.
    tooling = re.compile(r"(?i)(check|scan|purge|audit|review)_.*(token|secret|cred)")
    for f in tracked:
        base = os.path.basename(f)
        if re.search(r"(token|secret|\.env$|credential)", base, re.I) and \
                base not in ignored and not tooling.search(base):
            suspicious.append(f + "  (possible committed secret)")
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
