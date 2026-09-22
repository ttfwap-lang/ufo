"""Elevated verification of the UFO_ELEVATED task + worker. Writes to file."""
import json
import subprocess

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
OUT = BASE + r"\uac_verify.json"

report = {}
r = subprocess.run(["schtasks", "/query", "/tn", "UFO_ELEVATED", "/v", "/fo", "LIST"],
                   capture_output=True, text=True)
report["query_rc"] = r.returncode
report["query_out"] = r.stdout[:2000]
report["query_err"] = r.stderr[:500]
r2 = subprocess.run(["cmd", "/c", "whoami"], capture_output=True, text=True)
report["whoami"] = r2.stdout.strip()
r3 = subprocess.run(["cmd", "/c", "net session"], capture_output=True, text=True)
report["elevated"] = r3.returncode == 0
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)
print(report.get("whoami"), "elevated:", report.get("elevated"))
