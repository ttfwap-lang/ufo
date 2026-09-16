from pathlib import Path
import os

ufo_root = Path(r"C:\Users\lnxzf\Desktop\projects\ufo")
bf_root = Path(r"C:\Users\lnxzf\Desktop\projects\bankfidelity")

print("=== UFO Root structure ===")
for p in sorted(ufo_root.iterdir()):
    kind = "DIR " if p.is_dir() else "FILE"
    print(f"  {kind} {p.name}")

print()
print("=== BankFidelity Root structure ===")
for p in sorted(bf_root.iterdir()):
    kind = "DIR " if p.is_dir() else "FILE"
    size = p.stat().st_size if p.is_file() else ""
    print(f"  {kind} {p.name} {size}")

print()
print("=== Key paths check ===")
for p in [
    ufo_root / "ufo" / "python_env" / "python.exe",
    ufo_root / "ufo" / "python_env",
    ufo_root / "bin" / "llama-server.exe",
    ufo_root / "models",
    bf_root / "BankFidelity_Stable.exe",
    bf_root / "target" / "release",
    bf_root / "target" / "debug",
    bf_root / ".env",
]:
    exists = p.exists()
    status = "EXISTS" if exists else "MISSING"
    print(f"  {status:7s} {p}")

# Check for models directory
for candidate in [ufo_root / "models", ufo_root / "ufo" / "models", bf_root / "models"]:
    if candidate.exists():
        print(f"\n  Models dir found: {candidate}")
        for f in candidate.iterdir():
            print(f"    {f.name}")

# Check for .env in bankfidelity
for candidate in [bf_root / ".env", bf_root / "bankfidelity.env"]:
    if candidate.exists():
        print(f"\n  Env file found: {candidate}")
