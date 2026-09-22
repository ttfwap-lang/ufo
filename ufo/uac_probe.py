"""Trivial elevated probe used via the uac_run client to prove the chain."""
import json

with open(r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\uac_probe_result.json", "w") as f:
    json.dump({"from": "uac-daemon", "elevated": True, "ok": True}, f)
print("probe-ok")
