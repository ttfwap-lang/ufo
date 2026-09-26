"""Scan everything about to be committed for credentials, of ANY file type.

review_repo.py's whole-tree scan only walks .py/.ps1, but the credentials that
actually leaked lived in a stray result.json. This runs the same patterns
(review_repo.SECRET_PATTERNS) over every staged file - json, yaml, sh, md, env,
whatever - so the check matches what a push will publish.

    python scan_staged.py            # exit 1 and list file:line:kind on a hit
    python scan_staged.py --install  # install it as .git/hooks/pre-commit

Secret values are never printed, only file, line and kind.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Files bigger than this are not text worth scanning line by line, but they are
# still refused outright if they look like data dumps (see BINARY_REFUSE).
MAX_BYTES = 5_000_000
# Extensions that have no business in a public repo of this kind.
BINARY_REFUSE = (".pem", ".key", ".pfx", ".p12", ".sqlite", ".db", ".pkl")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def staged_files() -> list[str]:
    top = _git("rev-parse", "--show-toplevel").strip()
    names = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [os.path.join(top, n) for n in names.split("\0") if n]


def install_hook() -> None:
    hooks = _git("rev-parse", "--git-path", "hooks").strip()
    hooks = hooks if os.path.isabs(hooks) else os.path.join(HERE, hooks)
    path = os.path.join(hooks, "pre-commit")
    # Pin the interpreter that installed it; a bare `python` may resolve to a
    # different one (or none) inside git's shell.
    exe = sys.executable.replace("\\", "/")
    target = os.path.join(HERE, "scan_staged.py").replace("\\", "/")
    script = ("#!/bin/sh\n# installed by scan_staged.py --install\n"
              f'exec "{exe}" "{target}"\n')
    with open(path, "w", newline="\n") as fh:
        fh.write(script)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    print(f"installed {path}")


def main() -> int:
    if "--install" in sys.argv:
        install_hook()
        return 0
    from review_repo import secret_scan

    paths = staged_files()
    bad_ext = [p for p in paths if p.lower().endswith(BINARY_REFUSE)]
    scannable = [p for p in paths
                 if os.path.isfile(p) and os.path.getsize(p) <= MAX_BYTES]
    hits = secret_scan(scannable)
    for h in hits:
        print(f"SECRET  {h['file']}:{h['line']}  {h['kind']}  {h['snippet']}")
    for p in bad_ext:
        print(f"REFUSED {os.path.relpath(p)}  (key/db material must not be committed)")
    print(f"scanned {len(scannable)} staged file(s): "
          f"{len(hits)} secret hit(s), {len(bad_ext)} refused")
    return 1 if hits or bad_ext else 0


if __name__ == "__main__":
    sys.exit(main())
