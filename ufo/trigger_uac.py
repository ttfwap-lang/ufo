"""Elevated: re-trigger UFO_ELEVATED and wait for it to actually RUN."""
import json
import subprocess
import time

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
OUT = BASE + r"\uac_trigger.json"

report = {}
r = subprocess.run(["schtasks", "/run", "/tn", "UFO_ELEVATED"], capture_output=True, text=True)
report["run1"] = (r.stdout + r.stderr)[:300]

# wait & poll status
for i in range(8):
    time.sleep(2)
    q = subprocess.run(["schtasks", "/query", "/tn", "UFO_ELEVATED", "/v", "/fo", "LIST"],
                       capture_output=True, text=True)
    status = next((l.strip() for l in (q.stdout or "").splitlines() if "Status:" in l), "")
    result = next((l.strip() for l in (q.stdout or "").splitlines() if "Last Result:" in l), "")
    report[f"poll{i}"] = f"{status} | {result}"
    if "Running" in status:
        break

alive = False
try:
    with open(BASE + r"\uac_worker_alive.json") as f:
        report["heartbeat"] = json.load(f)
        alive = True
except Exception as e:
    report["heartbeat"] = f"missing: {e}"

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)
print(json.dumps(report, indent=2)[:900])
