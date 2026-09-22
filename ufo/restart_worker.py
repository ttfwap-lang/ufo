"""Collapse duplicate daemons: kill all pythonw uac_workers, respawn ONE.

Executed by an existing worker (as SYSTEM). Spawns a DETACHED PowerShell
that: kills every uac_worker pythonw, waits, then starts exactly one fresh
worker (picks up the single-executor mutex patch). The detached PowerShell
survives the parent's death.
"""
import json
import os
import subprocess

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
PYTHONW = os.path.join(BASE, ".venv", "Scripts", "pythonw.exe")
WORKER = os.path.join(BASE, "uac_worker.py")
OUT = os.path.join(BASE, "restart_result.json")

ps_cmd = (
    "taskkill /F /IM pythonw.exe; "
    "Start-Sleep -Seconds 2; "
    f"Start-Process -FilePath '{PYTHONW}' -ArgumentList '{WORKER}' -WindowStyle Hidden"
)
CREATE_NO_WINDOW = 0x08000000
subprocess.Popen(
    ["powershell", "-NoProfile", "-Command", ps_cmd],
    creationflags=CREATE_NO_WINDOW,
)

with open(OUT, "w") as f:
    json.dump({"ok": True, "spawned_detached": True}, f)
print("restart orchestrated")
