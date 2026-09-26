"""Verify the SIMPLER hotkeys (Scroll Lock / F12 / ESC / P) really work.

Chosen cancel keys: Scroll Lock (0x91, dead key, single press), F12 (0x7B)
backup, ESC silent backup. Pause: P. Verification: registration + WM_HOTKEY
pipeline + burst suppression + foreign-id immunity.
"""
import sys, time, ctypes
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "C:\\Users\\lnxzf\\Desktop\\projects\\ufo")
from ufo.automator.app_apis.telegram import ScreenLockout

WM_HOTKEY = 0x0312
stop_called, pause_called = [], []

def post_wm_hotkey(hwnd, hotkey_id):
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_size_t]
    user32.PostMessageW(hwnd, WM_HOTKEY, hotkey_id, 0)

def wait_for(predicate, timeout=1.5):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False

lock = ScreenLockout(on_stop=lambda: stop_called.append(True),
                     on_pause=lambda p: pause_called.append(p))
lock._keep_running = True
lock._state = "locked"
lock._start_hotkeys()
deadline = time.time() + 5
while lock._hotkey_hwnd is None and time.time() < deadline:
    time.sleep(0.05)

# Hotkey ids are 1..N in the order of lock._cancel_hotkeys (see _start_hotkeys).
# Derived from the live preset, not hard-coded: when Ctrl+Shift+Q was added as
# id1 the old fixed 1/2/3 labels silently tested the wrong keys and skipped ESC.
_NAMES = {(0x0006, 0x51): "ctrl+shift+q", (0, 0x91): "scrolllock", (0, 0x7B): "f12", (0, 0x1B): "esc"}
print("=" * 70)
print("CANCEL HOTKEYS (id: key):", {i: _NAMES.get(tuple(k), str(k)) for i, k in enumerate(lock._cancel_hotkeys, start=1)}, "+ P(id100)")
print("=" * 70)

cancel_checks = {}
for i, key in enumerate(lock._cancel_hotkeys, start=1):
    name = _NAMES.get(tuple(key), str(key))
    print(f"\n[cancel] id{i} {name} -> CANCEL...")
    stop_called.clear(); lock._state = "locked"
    post_wm_hotkey(lock._hotkey_hwnd, i)
    cancel_checks[name] = wait_for(lambda: bool(stop_called))
    print("    cancel fired:", cancel_checks[name], "| state:", lock._state)
for required in ("ctrl+shift+q", "esc"):   # AGENTS.md RULE 1: primary + silent backup
    cancel_checks.setdefault(required, False)

print("\n[4] id100 P -> PAUSE...")
pause_called.clear(); lock._state = "locked"
post_wm_hotkey(lock._hotkey_hwnd, 100)
ok4 = wait_for(lambda: bool(pause_called))
print("    pause fired:", pause_called, "| state:", lock._state)

print("\n[5] burst suppression...")
pause_called.clear(); lock._state = "locked"
lock.begin_input_burst()
post_wm_hotkey(lock._hotkey_hwnd, 100)
ok5a = not wait_for(lambda: bool(pause_called), timeout=0.7)
lock.end_input_burst()
post_wm_hotkey(lock._hotkey_hwnd, 100)
ok5b = wait_for(lambda: bool(pause_called))
print("    during burst ignored:", ok5a, "| after burst fired:", ok5b)

print("\n[6] foreign id ignored...")
stop_called.clear(); lock._state = "locked"
post_wm_hotkey(lock._hotkey_hwnd, 7)
ok6 = not wait_for(lambda: bool(stop_called), timeout=0.7)
print("    foreign id ignored:", ok6)

lock._keep_running = False
checks = {**cancel_checks, "pause": ok4,
          "burst": ok5a and ok5b, "foreign": ok6}
print("\n" + "=" * 70)
print("RESULT:", "CANCEL/PAUSE HOTKEYS VERIFIED" if all(checks.values()) else "FAIL " + str(checks))
print("=" * 70)
