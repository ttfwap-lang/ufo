from pathlib import Path

bf_env = Path(r"C:\Users\lnxzf\Desktop\projects\bankfidelity\.env")
root_env = Path(r"C:\Users\lnxzf\Desktop\projects\bankfidelity.env")

for p in [bf_env, root_env]:
    if p.exists():
        print(f"=== {p} ===")
        content = p.read_text(encoding="utf-8")
        for line in content.splitlines():
            clean = line.encode("ascii", "replace").decode("ascii")
            print(clean)
        print()
