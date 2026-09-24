"""Check whether a real Telegram bot token is present in git HISTORY.

Compiling the working tree is not enough: a token committed months ago stays
in every clone forever. This walks the commits that the checkpoint flagged and
tests any token-shaped string it finds against the Telegram API, so we know
whether pushing is safe or whether the token must be rotated first.

NEVER prints a full token - only the bot id prefix and a validity verdict.
"""
import re
import subprocess
import sys
import urllib.request

TOKEN_RE = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")
COMMITS = ["4d81b67", "560777f", "db169f5", "2c5f57e", "HEAD"]


def git(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def probe(tok: str) -> str:
    try:
        with urllib.request.urlopen(
                f"https://api.telegram.org/bot{tok}/getMe", timeout=20) as r:
            import json
            d = json.loads(r.read().decode())
        if d.get("ok"):
            return f"STILL VALID -> @{d['result']['username']}"
        return "rejected by Telegram"
    except Exception as e:                            # noqa: BLE001
        return f"error: {type(e).__name__}"


def main() -> int:
    found_any = False
    for rev in COMMITS:
        # search the whole tree at that revision, not just the diff
        files = git("ls-tree", "-r", "--name-only", rev).splitlines()
        for f in files:
            if not f.endswith((".py", ".json", ".env", ".txt", ".ps1", ".yml")):
                continue
            blob = git("show", f"{rev}:{f}")
            for m in TOKEN_RE.finditer(blob):
                found_any = True
                tok = m.group(0)
                verdict = probe(tok)
                bot_id = tok.split(":")[0]
                print(f"  {rev}  {f}  bot_id={bot_id}...  {verdict}")
    if not found_any:
        print("  no token-shaped string found in the scanned revisions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
