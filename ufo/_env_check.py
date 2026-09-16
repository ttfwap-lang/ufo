from pathlib import Path
import sys, os

print(f"sys.executable: {sys.executable}")
print(f"sys.prefix: {sys.prefix}")
print(f"PYTHONHOME env: {os.environ.get('PYTHONHOME', '(not set)')}")

# Check if python_env exists anywhere under the projects
for root in [Path(r"C:\Users\lnxzf\Desktop\projects\ufo"), Path(r"C:\Users\lnxzf\Desktop\projects\bankfidelity")]:
    for p in root.rglob("python_env"):
        print(f"  Found python_env: {p}")
        py = p / "python.exe"
        print(f"    python.exe exists: {py.exists()}")

# Check for venv cfg
for root in [Path(r"C:\Users\lnxzf\Desktop\projects")]:
    for p in root.rglob("pyvenv.cfg"):
        print(f"  Found venv cfg: {p} ({p.parent})")

# Check system Python
sys_python = Path(r"C:\Users\lnxzf\AppData\Local\Programs\Python\Python312\python.exe")
print(f"System Python: {sys_python} (exists={sys_python.exists()})")

# Check for llama-server
for p in [
    Path(r"C:\Users\lnxzf\Desktop\projects\ufo\bin\llama-server.exe"),
    Path(r"C:\Users\lnxzf\Desktop\projects\bankfidelity\bin\llama-server.exe"),
    Path(r"C:\llama-server.exe"),
    Path(r"C:\Users\lnxzf\Desktop\projects\bankfidelity\python"),
]:
    print(f"  {'EXISTS' if p.exists() else 'MISSING'}: {p}")

# Check for models dir under both roots
for p in [
    Path(r"C:\Users\lnxzf\Desktop\projects\ufo\models"),
    Path(r"C:\Users\lnxzf\Desktop\projects\bankfidelity\models"),
]:
    if p.exists():
        print(f"  Models dir: {p}")
        files = list(p.iterdir())
        print(f"    Contents ({len(files)} items):")
        for f in sorted(files)[:20]:
            print(f"      {f.name}")
