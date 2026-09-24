"""Run the collector directly (bypassing the bridge) and show the full log.

The bridge buffers subprocess output until the job ends, so when a run fails
there is no clue why. This runs the same command the bridge runs and streams
the log, which is what you want when the vision fallback or any verification
step misbehaves.
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(os.path.dirname(BASE), ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable

signs = sys.argv[1:] or ["aries", "leo"]
cmd = [PY, "-X", "utf8", os.path.join(BASE, "uac_run.py"),
       os.path.join(BASE, "astro_collect.py")] + signs
print("running:", " ".join(cmd), flush=True)
p = subprocess.run(cmd, cwd=BASE, capture_output=True, timeout=5400)
out = (p.stdout or b"").decode("utf-8", "replace")
err = (p.stderr or b"").decode("utf-8", "replace")
print(out)
if err.strip():
    print("--- stderr ---")
    print(err[-2000:])
print("rc:", p.returncode)
