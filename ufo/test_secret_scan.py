"""Self-test for review_repo.secret_scan: does it catch real secrets and ignore
fixtures? Written as a file because inline quoting of credential-shaped strings
is exactly where this keeps breaking.

Run: python test_secret_scan.py
"""
from __future__ import annotations

import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rr", os.path.join(HERE, "review_repo.py"))
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)

# Real credentials are BUILT at runtime so this file itself never contains a
# string that would trip the scanner it is testing.
CASES = {
    "real_openrouter.txt": "k = 'sk-or-v1-" + "a1b2c3d4" * 8 + "'",
    "real_google.txt": "k = 'AIza" + "SyD9xK2mQ7pL4vR8tB1nC6hJ3wE5gF0z" + "'",
    "real_qwen.txt": "k = 'AQ." + "Ab8RN6Ls" * 5 + "'",
    # Deliberately low-entropy after the colon: a real Telegram token can have
    # few distinct characters, and an entropy heuristic once swallowed this one.
    "real_telegram.txt": "k = '8937832147:AAH" + "x" * 32 + "'",
    "real_github.txt": "k = 'ghp_" + "a1b2c3d4" * 4 + "abcd" + "'",
    "real_aws.txt": "k = 'AKIAIOSFODNN7EXAMPLE'",
    "fixture1.txt": 'api_key="sk-real-cloud-key"',
    "fixture2.txt": 'api_key="sk-local"',
    "fixture3.txt": 'password = "hunter2placeholder"',
    "fixture4.txt": 'token="YOUR_TOKEN_HERE"',
    "fixture5.txt": 'secret="changeme-please-now"',
}


def main() -> int:
    d = tempfile.mkdtemp()
    paths = []
    for name, text in CASES.items():
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        paths.append(p)

    found = {os.path.basename(h["file"]) for h in rr.secret_scan(paths)}
    bad = 0
    for name in CASES:
        want = "ignored" if name.startswith("fixture") else "caught"
        actual = "caught" if name in found else "ignored"
        ok = actual == want
        bad += not ok
        print(f"  {'OK  ' if ok else 'BAD '} {name:22} want={want:8} got={actual}")

    # And confirm no snippet ever contains the secret itself.
    leaked = [h for h in rr.secret_scan(paths)
              if any(seg in h["snippet"] for seg in ("a1b2c3d4", "SyD9xK2mQ7", "Ab8RN6Ls"))]
    if leaked:
        print(f"  BAD  snippets leak the secret value: {leaked}")
        bad += 1
    else:
        print("  OK   snippets never contain the secret value")

    print("RESULT:", "all correct" if not bad else f"{bad} WRONG")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
