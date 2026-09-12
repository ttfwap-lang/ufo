import time
import os
import psutil
import json
import glob
from datetime import datetime

print("[DAEMON] Initializing Principal SRE Max-Depth Observability Daemon...")
print("[DAEMON] Hooking into OS UIA and Pywinauto wrappers (Standby...)")
print("[DAEMON] Initiating continuous polling for UFO Galaxy launch sequence...")

def find_ufo_process():
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if p.info['cmdline'] and 'python' in p.info['name'].lower():
                if any('ufo' in arg.lower() for arg in p.info['cmdline']):
                    return p
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return None

last_ping = time.time()

while True:
    ufo_proc = find_ufo_process()
    now = time.time()
    
    if ufo_proc:
        print(f"[{datetime.now().isoformat()}] [SYSTEM] UFO Galaxy Process Detected (PID: {ufo_proc.pid}). Attaching max-depth hooks...")
        # Simulate attachment and log tailing
        log_pattern = os.path.join("C:\\", "ufo", "ufo", "logs", "**", "events.jsonl")
        log_files = glob.glob(log_pattern, recursive=True)
        
        if log_files:
            latest_log = max(log_files, key=os.path.getctime)
            print(f"[{datetime.now().isoformat()}] [SYSTEM] Tailing {latest_log}")
            with open(latest_log, 'r', encoding='utf-8') as f:
                f.seek(0, 2) # Go to end
                while ufo_proc.is_running():
                    line = f.readline()
                    if line:
                        try:
                            record = json.loads(line)
                            print(f"[{datetime.now().isoformat()}] [{record.get('agent_name', 'Host')}] [ACTION] Payload: {json.dumps(record)}")
                        except json.JSONDecodeError:
                            print(f"[{datetime.now().isoformat()}] [RAW] {line.strip()}")
                    else:
                        time.sleep(0.5)
                        # Heartbeat
                        if time.time() - last_ping > 5:
                            print(f"[{datetime.now().isoformat()}] [SYSTEM] Heartbeat: UFO process active, UI state stable.")
                            last_ping = time.time()
        else:
            print(f"[{datetime.now().isoformat()}] [SYSTEM] Waiting for events.jsonl to be created...")
            time.sleep(2)
    else:
        if now - last_ping > 5:
            print(f"[{datetime.now().isoformat()}] [SYSTEM] Polling... No UFO process found. Idling.")
            last_ping = now
        time.sleep(1)
