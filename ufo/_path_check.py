import os
from pathlib import Path

paths_to_check = [
    (r"C:\bankfidelity\bankfidelity", "bf_dir"),
    (r"C:\ufo\ufo", "ufo_dir"),
    (r"C:\ufo", "ufo_root"),
    (r"C:\ufo\models", "models_dir"),
    (r"C:\ufo\bin\llama-server.exe", "llama_server"),
    (r"C:\ufo\ufo\python_env\python.exe", "python_exe"),
]

print("=== Hardcoded paths in terminal_config.py ===")
for p, label in paths_to_check:
    exists = Path(p).exists()
    status = "EXISTS" if exists else "MISSING"
    print(f"  {status:7s} {label:15s} {p}")

cwd = os.getcwd()
print(f"\nCurrent working dir: {cwd}")

print("\n=== What exists under C:\\ ===")
for parent in [Path("C:/"), Path(r"C:\Users\lnxzf\Desktop\projects")]:
    if parent.exists():
        relevant = [d for d in parent.iterdir() if "bank" in d.name.lower() or "ufo" in d.name.lower()]
        for d in relevant:
            kind = "DIR " if d.is_dir() else "FILE"
            print(f"  {kind}  {d}")

print("\n=== What exists under C:\\Users\\lnxzf ===")
for d in Path(r"C:\Users\lnxzf").iterdir():
    if d.is_dir() and ("bank" in d.name.lower() or "ufo" in d.name.lower() or "desktop" in d.name.lower()):
        print(f"  DIR  {d}")
        if d.name.lower() == "desktop" and d.exists():
            for sub in d.iterdir():
                if sub.is_dir() and ("bank" in sub.name.lower() or "ufo" in sub.name.lower()):
                    print(f"    DIR  {sub}")

print("\n=== Desktop projects contents ===")
dp = Path(r"C:\Users\lnxzf\Desktop\projects")
if dp.exists():
    for sub in dp.iterdir():
        print(f"  {'DIR ' if sub.is_dir() else 'FILE'}  {sub}")
