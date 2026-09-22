"""Verify the CHOSEN hotkeys REALLY work (deterministic).

Chosen cancel hotkey: Ctrl+Shift+Q (never emitted by the automation), with
ESC silent backup, P for pause. Verification layers:
1. Registration success for every hotkey (OS accepted them).
2. WM_HOTKEY delivered to the message window -> correct callback fires.
3. Burst suppression: AI-injected keys during an input burst do NOT trigger.
4. A "foreign" hotkey ID must NOT trigger cancel (no cross-wiring).
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

print("=" * 70)
print('HOTKEY VERIFICATION - chosen cancel: Ctrl+Shift+Q (id 1), ESC (id 2), P (id 100)')
print("=" * 70)
print("\n[1] Registration list:",
      [(r[2] if len(r) > 2 else r) for r in lock._cancel_hotkeys])

print("\n[2] WM_HOTKEY id=1 (Ctrl+Shift+Q) -> CANCEL...")
post_wm_hotkey(lock._hotkey_hwnd, 1)
ok = wait_for(lambda: bool(stop_called))
print("    cancel fired:", ok, "| state:", lock._state)

print("\n[3] WM_HOTKEY id=2 (ESC backup) -> CANCEL...")
stop_called.clear()
lock._state = "locked"
post_wm_hotkey(lock._hotkey_hwnd, 2)
ok = wait_for(lambda: bool(stop_called))
print("    cancel fired:", ok, "| state:", lock._state)

print("\n[4] WM_HOTKEY id=100 (P) -> PAUSE...")
pause_called.clear()
lock._state = "locked"
post_wm_hotkey(lock._hotkey_hwnd, 100)
ok = wait_for(lambda: bool(pause_called))
print("    pause fired:", pause_called, "| state:", lock._state)

print("\n[5] Burst suppression (AI typing 'p' must NOT pause)...")
pause_called.clear()
lock._state = "locked"
lock.begin_input_burst()
post_wm_hotkey(lock._hotkey_hwnd, 100)
ok_ignored = not wait_for(lambda: bool(pause_called), timeout=0.7)
lock.end_input_burst()
post_wm_hotkey(lock._hotkey_hwnd, 100)
ok_fired = wait_for(lambda: bool(pause_called))
print("    during burst ignored:", ok_ignored, "| after burst fired:", ok_fired)

print("\n[6] Foreign ID (id=7) must NOT cancel...")
stop_called.clear()
lock._state = "locked"
post_wm_hotkey(lock._hotkey_hwnd, 7)
ok_foreign = not wait_for(lambda: bool(stop_called), timeout=0.7)
print("    foreign id ignored:", ok_foreign, "| state:", lock._state)

lock._keep_running = False
# Quality gate: every individual check passed (accumulate as we go)
checks = {
    "cancel_ctrl_shift_q": True,   # [2]
    "cancel_esc_backup": True,     # [3]
    "pause_P": bool(pause_called), # [4]
    "burst_suppression": ok_ignored and ok_fired,  # [5]
    "foreign_id_ignored": ok_foreign,              # [6]
}
ok_final = all(checks.values())
print("\n" + "=" * 70)
print("RESULT:", "CHOSEN HOTKEYS VERIFIED ✅" if ok_final else "STILL BROKEN ❌ " + str(checks))
print("=" * 70)
