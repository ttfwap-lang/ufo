"""Runs the tests/dgx/*_scenarios.sh drivers (fake /proc, docker, curl; real bash/awk/flock) against
scripts/dgx: guard + memguard, retire-qwen27b, apply. Needs a Linux userland: native, or WSL."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
DRIVERS = {"guard": 30, "retire": 12, "apply": 6}   # driver -> minimum PASS lines expected
DGX = HERE.parent.parent / "scripts" / "dgx"


def _wsl_path(p: Path) -> str:
    s = str(p).replace("\\", "/")
    return re.sub(r"^([A-Za-z]):", lambda m: f"/mnt/{m.group(1).lower()}", s)


def _command(script):
    if sys.platform != "win32" and shutil.which("bash") and shutil.which("flock"):
        return ["bash", str(script), str(DGX)]
    if sys.platform == "win32" and shutil.which("wsl.exe"):
        r = subprocess.run(["wsl.exe", "-l", "-q"], capture_output=True, timeout=30)
        distros = [d.strip("\x00 \r") for d in r.stdout.decode("utf-16-le", "ignore").splitlines() if d.strip("\x00 \r")]
        distros = [d for d in distros if not d.startswith("docker-desktop")]
        if distros:
            return ["wsl.exe", "-d", distros[0], "--", "bash", _wsl_path(script), _wsl_path(DGX)]
    return None


@pytest.mark.parametrize("driver,minimum", sorted(DRIVERS.items()))
def test_scenarios(driver, minimum):
    script = HERE / f"{driver}_scenarios.sh"
    cmd = _command(script)
    if cmd is None:
        pytest.skip("no Linux userland (bash+flock or WSL) available")
    p = subprocess.run(cmd, capture_output=True, timeout=240)
    out = p.stdout.decode("utf-8", "replace").replace("\x00", "")
    lines = [l for l in out.splitlines() if l.startswith(("PASS", "FAIL"))]
    assert len([l for l in lines if l.startswith("PASS")]) >= minimum, out
    failed = [l for l in lines if l.startswith("FAIL")]
    assert not failed, "\n".join(failed)
