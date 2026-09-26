"""Permanent hidden UAC worker - runs elevated (SYSTEM) via scheduled task.

Started by scheduled task UFO_ELEVATED (pythonw.exe - NO console window, invisible).
Loops reading uac_command.json and executes the requested script elevated,
writing the result to uac_result.json. The client (uac_run.py) triggers it
with `schtasks /run` - no UAC prompt, ever, after one-time registration.
"""
import json
import os
import subprocess
import sys
import time

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
CMD = os.path.join(BASE, "uac_command.json")
RESULT = os.path.join(BASE, "uac_result.json")

HEARTBEAT = os.path.join(BASE, "uac_worker_alive.json")


def acquire_exec_lock(timeout_ms=12000):
    """Global mutex: only ONE worker executes a given command at a time.

    Prevents duplicate execution when multiple daemon instances are alive
    (e.g. one auto-started at logon plus one started manually).
    """
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    h = kernel32.CreateMutexW(None, 0, "Global\\UFO_EXEC_LOCK")
    if h:
        kernel32.WaitForSingleObject(h, timeout_ms)
    return h


def release_exec_lock(h) -> None:
    if h:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        try:
            kernel32.ReleaseMutex(h)
            kernel32.CloseHandle(h)
        except Exception:
            pass


def main() -> int:
    # Signal readiness (proves it runs elevated / hidden).
    #
    # This is a HEARTBEAT, so it must be refreshed on a timer, not written
    # once: uac_run.py decides whether the daemon is alive by the file's age.
    # Writing it only at startup made a daemon that died at any later point
    # look alive forever, and the client would then burn its full timeout
    # waiting on a command nobody was ever going to run.
    last_beat = 0.0

    def beat() -> None:
        nonlocal last_beat
        try:
            tmp = HEARTBEAT + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"alive": True, "time": time.time(), "user": "SYSTEM"}, f)
            # Atomic: a client polling the heartbeat never reads a torn file.
            os.replace(tmp, HEARTBEAT)
            last_beat = time.time()
        except Exception:
            pass

    beat()

    while True:
        if time.time() - last_beat > 5.0:
            beat()
        try:
            if os.path.exists(CMD):
                lock = None
                try:
                    lock = acquire_exec_lock()
                    # Re-check after taking the lock (another worker may have run it)
                    if not os.path.exists(CMD):
                        continue
                    with open(CMD, "r", encoding="utf-8") as f:
                        cmd = json.load(f)
                    result = {"id": cmd.get("id", 0), "ok": False}
                    try:
                        pr = subprocess.run(
                            [sys.executable, cmd["script"]] + list(cmd.get("args", [])),
                            capture_output=True, text=True,
                            timeout=cmd.get("timeout", 600),
                        )
                        result = {
                            "id": cmd.get("id", 0),
                            "ok": pr.returncode == 0,
                            "stdout": pr.stdout[-4000:],
                            "stderr": pr.stderr[-4000:],
                        }
                    except Exception as e:  # noqa: BLE001 - report any worker error
                        result = {"id": cmd.get("id", 0), "ok": False, "error": repr(e)}
                    with open(RESULT, "w", encoding="utf-8") as f:
                        json.dump(result, f, ensure_ascii=False)
                    if os.path.exists(CMD):
                        os.remove(CMD)
                finally:
                    release_exec_lock(lock)
        except Exception:
            pass
        time.sleep(0.25)


if __name__ == "__main__":
    sys.exit(main())
