"""Elevated deep-check of the UFO_ELEVATED task state."""
import json
import subprocess
import time

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
OUT = BASE + r"\uac_verify2.json"

report = {}
r = subprocess.run(["schtasks", "/query", "/tn", "UFO_ELEVATED", "/v", "/fo", "LIST"],
                   capture_output=True, text=True)
report["query_rc"] = r.returncode
lines = [l for l in (r.stdout or "").splitlines() if any(
    k in l for k in ("Status:", "Last Run Time:", "Last Result:", "Run As User:", "Task To Run:"))]
report["selected"] = lines
report["stderr"] = (r.stderr or "")[:500]

# also check if the worker script can be imported/run by itself quickly
r2 = subprocess.run(
    ["C:\\Users\\lnxzf\\Desktop\\projects\\ufo\\ufo\\.venv\\Scripts\\python.exe",
     "-c", "import sys; sys.path.insert(0,r'C:\\Users\\lnxzf\\Desktop\\projects\\ufo\\ufo'); import uac_worker; print('import ok')"],
    capture_output=True, text=True, timeout=30)
report["worker_import"] = (r2.stdout + r2.stderr)[:500]

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)
print(json.dumps(report, indent=2)[:1500])
