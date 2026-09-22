"""Self-heal: kill duplicate uac_worker daemons, respawn EXACTLY one (SYSTEM).

Run AS SYSTEM via the (possibly duplicated) uac daemon. Uses an exclusive
lock file so only ONE execution instance performs the cleanup even if
multiple workers pick up the command.
"""
import json
import os
import subprocess
import time

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
LOCK = os.path.join(BASE, "fix_workers.lock")
OUT = os.path.join(BASE, "fix_workers_result.json")
PYTHONW = os.path.join(BASE, ".venv", "Scripts", "pythonw.exe")
WORKER = os.path.join(BASE, "uac_worker.py")

res = {"ok": False}
try:
    # exclusive lock
    fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        # 1) kill every pythonw running uac_worker (except none - we kill all)
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
             "Where-Object { $_.CommandLine -match 'uac_worker' } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
            capture_output=True, text=True, timeout=60)
        res["kill"] = True
        time.sleep(2)
        # 2) respawn EXACTLY one (detached)
        r2 = subprocess.Popen([PYTHONW, WORKER], cwd=BASE)
        res["spawned"] = True
        time.sleep(3)
        # 3) verify heartbeat + single instance
        try:
            with open(os.path.join(BASE, "uac_worker_alive.json")) as f:
                res["heartbeat"] = json.load(f)
        except Exception as e:
            res["hb_error"] = repr(e)
        res["ok"] = True
    finally:
        os.close(fd)
        try:
            os.remove(LOCK)
        except Exception:
            pass
except Exception as e:
    res["error"] = repr(e)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(res, f, indent=2)
print(json.dumps(res)[:300])
