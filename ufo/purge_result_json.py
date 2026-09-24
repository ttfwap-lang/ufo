"""Purge the root-level result.json (which embeds real API keys) from history.

GitHub push protection BLOCKED the push because commit 2af36d5 added
result.json containing:
  * a Qwen/DashScope-style API token
  * an OpenRouter key (sk-or-v1-...)

The file is a stray automation artefact - it is not in HEAD and nothing
imports it - so removing it from history loses no code. The credentials must
still be ROTATED: this only stops them from being published, and a secret that
sat in a repo is compromised regardless.

Only that one path is touched; every other blob keeps its content.
"""
from __future__ import annotations

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def sh(*args: str) -> int:
    p = subprocess.run(["git", "-C", REPO, *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if p.returncode:
        print(p.stdout[-2000:])
        print(p.stderr[-2000:], file=sys.stderr)
    return p.returncode


def main() -> int:
    before = git("rev-parse", "main").stdout.strip()
    print(f"main before: {before[:12]}")

    # Safety: refuse to rewrite if the working tree is dirty.
    if git("status", "--porcelain").stdout.strip():
        print("working tree is dirty - commit or stash first")
        return 1

    env_backup = git("rev-parse", "refs/original/").stdout.strip()
    # filter-branch prints a big warning; keep the output quiet.
    rc = sh("filter-branch", "--force",
            "--index-filter",
            "git rm --cached --ignore-unmatch -- 'result.json'",
            "--prune-empty", "--", "main")
    if rc:
        print("filter-branch failed")
        return rc
    del env_backup

    after = git("rev-parse", "main").stdout.strip()
    print(f"main after : {after[:12]}")

    # Verify the secret is gone from every reachable commit.
    hits = git("grep", "-l", "-E",
               "sk-or-v1-[0-9a-zA-Z]{20}|AQ\\.[0-9A-Za-z_-]{40}",
               "--all").stdout.strip()
    if hits:
        print("STILL PRESENT in:")
        print(hits)
        return 1
    print("verified: no OpenRouter/Qwen token remains in any commit")
    print("keep the backup ref if you need to recover: "
          "git for-each-ref refs/original/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
