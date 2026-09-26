"""The recurring PowerShell watchers must load their helper and stay parseable.

A patch once turned `'scripts\\fastwin.ps1'` into `scripts<FORM FEED>astwin.ps1`
(`\\f` read as an escape). The dot-source failed, and because the scripts run with
$ErrorActionPreference='Continue' the scan carried on and reported "bridge not
listening" - a confident wrong answer. Three cheap static checks make that
class of bug impossible to reintroduce unnoticed.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RECURRING = [
    "bridge_watchdog.ps1",
    "ufo_scan_win.ps1",
    "scripts/gx10_tunnel_keepalive.ps1",
    "scripts/litellm_keepalive.ps1",
    "scripts/fastwin.ps1",
]
DOT_SOURCE = re.compile(r"^\s*\.\s+\(Join-Path\s+\$PSScriptRoot\s+'([^']+)'\)", re.M)


@pytest.mark.parametrize("rel", RECURRING)
def test_no_stray_control_characters(rel):
    text = (ROOT / rel).read_text(encoding="utf-8", errors="strict")
    bad = sorted({hex(ord(c)) for c in text if ord(c) < 32 and c not in "\t\r\n"})
    assert not bad, f"{rel} contains control characters {bad} (an escape gone wrong?)"


@pytest.mark.parametrize("rel", RECURRING)
def test_every_dot_sourced_helper_exists(rel):
    src = ROOT / rel
    for target in DOT_SOURCE.findall(src.read_text(encoding="utf-8")):
        assert (src.parent / target).is_file(), f"{rel} dot-sources missing {target!r}"


@pytest.mark.skipif(sys.platform != "win32", reason="uses Windows PowerShell's parser")
@pytest.mark.parametrize("rel", RECURRING)
def test_script_parses(rel):
    ps = (
        "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{ROOT / rel}',[ref]$null,[ref]$e); if($e){{ $e[0].Message; exit 1 }}"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"{rel}: {r.stdout.strip()}"
