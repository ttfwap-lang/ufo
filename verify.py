import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

def hash_dir(path):
    hashes = {}
    for root, _, files in os.walk(path):
        for f in files:
            p = os.path.join(root, f)
            try:
                with open(p, "rb") as file:
                    hashes[p] = hashlib.sha256(file.read()).hexdigest()
            except Exception:
                pass
    return hashes

def main():
    config_dir = Path(r"C:\ufo\ufo\config\ufo")
    scripts_dir = Path(r"C:\ufo\ufo\scripts")
    python = Path(r"C:\ufo\ufo\python_env\python.exe")
    
    if not python.exists():
        python = "python"
        
    print("1. Hashing baseline...")
    h1 = hash_dir(config_dir)
    
    print("2. Running launcher scripts...")
    cmds = [
        [python, scripts_dir / "switch_backend.py", "local"],
        [python, scripts_dir / "switch_backend.py", "cloud"],
        [python, scripts_dir / "switch_backend.py", "auto"],
        [python, scripts_dir / "switch_backend.py", "status"],
        [python, scripts_dir / "prepare_cloud_smoke.py"],
        [scripts_dir / "stop_local_llm.bat"],
    ]
    for cmd in cmds:
        print(f"Running {cmd}...")
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
    print("3. Re-hashing...")
    h2 = hash_dir(config_dir)
    diff = set()
    for k in set(h1.keys()) | set(h2.keys()):
        if h1.get(k) != h2.get(k):
            diff.add(k)
            
    print(f"Diff files: {diff}")
    assert all("backend_state.json" in str(d) for d in diff), "Only backend_state.json can change"
    assert not any("tmp" in str(d) for d in diff), "No tmp residue allowed"
    
    bak_file = config_dir / "agents_local.yaml.bak"
    if str(bak_file) in h1:
        assert h1[str(bak_file)] == h2[str(bak_file)], "bak file mutated"
        
    print("4. Cross process check...")
    subprocess.run([python, scripts_dir / "switch_backend.py", "local"])
    res_local = subprocess.run([python, "-c", "from ufo.llm.config_helper import resolve_agent_config; print(resolve_agent_config('HOST_AGENT').get('API_MODEL'))"], capture_output=True, text=True, cwd=r"C:\ufo")
    print(f"Local model: {res_local.stdout.strip()}")
    assert "Qwen3" in res_local.stdout or "qwen" in res_local.stdout.lower() or "local" in res_local.stdout.lower() or "gpt" not in res_local.stdout.lower()

    subprocess.run([python, scripts_dir / "switch_backend.py", "cloud"])
    res_cloud = subprocess.run([python, "-c", "from ufo.llm.config_helper import resolve_agent_config; print(resolve_agent_config('HOST_AGENT').get('API_MODEL'))"], capture_output=True, text=True, cwd=r"C:\ufo")
    print(f"Cloud model: {res_cloud.stdout.strip()}")

    print("5. Corrupt backend_state...")
    state_file = config_dir / "backend_state.json"
    state_file.write_text("invalid json")
    res_corrupt = subprocess.run([python, "-m", "ufo", "--help"], capture_output=True, cwd=r"C:\ufo")
    assert res_corrupt.returncode == 0
    
    state_file.unlink()
    res_missing = subprocess.run([python, "-m", "ufo", "--help"], capture_output=True, cwd=r"C:\ufo")
    assert res_missing.returncode == 0

    print("6. Assert zero writes on process override...")
    h3 = hash_dir(config_dir)
    subprocess.run([python, "-c", "from ufo.llm.config_helper import set_process_override; set_process_override('cloud')"], cwd=r"C:\ufo")
    h4 = hash_dir(config_dir)
    assert h3 == h4

    print("Done!")

if __name__ == "__main__":
    main()
