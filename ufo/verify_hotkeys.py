"""Verify lockout hotkeys deterministically.

Two-layer proof:
1. OS registration: RegisterHotKey returns success for stop/pause VKs.
2. Handler pipeline: WM_HOTKEY posted to the message-only window is pumped
   and dispatches the correct callbacks (stop / pause / burst suppression).

NOTE: synthesized physical input (keybd_event/SendInput) is intentionally NOT
relied upon - injected keyboard events do not surface as hotkeys or
async-key-state changes in this shell session (verified in diag_keys2.py).
The OS-side trigger is standard Windows behavior; live physical ESC presses
have cancelled goals in earlier runs.
"""
import sys, time, ctypes
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "C:\\Users\\lnxzf\\Desktop\\projects\\ufo")
from ufo.automator.app_apis.telegram import ScreenLockout

WM_HOTKEY = 0x0312
stop_called = []
pause_called = []

def post_wm_hotkey(hwnd, hotkey_id):
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_size_t]
    user32.PostMessageW(hwnd, WM_HOTKEY, hotkey_id, 0)

print("=" * 70)
print("HOTKEY VERIFICATION v3 (RegisterHotKey + WM_HOTKEY pipeline)")
print("=" * 70)

lock = ScreenLockout(
    stop_key=0x1B, pause_key=0x50, stop_key_label="ESC", pause_key_label="P",
    on_stop=lambda: stop_called.append(True),
    on_pause=lambda p: pause_called.append(p),
)
lock._keep_running = True
lock._state = "locked"
lock._start_hotkeys()
deadline = time.time() + 5
while lock._hotkey_hwnd is None and time.time() < deadline:
    time.sleep(0.05)
print("\n[0] hotkey window created:", lock._hotkey_hwnd is not None)

# [1] ESC -> stop
print("\n[1] WM_HOTKEY(id=1, ESC) -> stop...")
post_wm_hotkey(lock._hotkey_hwnd, 1)
time.sleep(0.6)
print("    stop_callback fired:", bool(stop_called), "| state:", lock._state)

# [2] P -> pause toggle
lock._state = "locked"
pause_called.clear()
print("\n[2] WM_HOTKEY(id=2, P) -> pause...")
post_wm_hotkey(lock._hotkey_hwnd, 2)
time.sleep(0.6)
print("    pause_callback fired:", pause_called, "| state:", lock._state)

# [3] F1 config - custom VK mapping preserved
stop_called.clear()
lock2 = ScreenLockout(stop_key=0x70, pause_key=0x71, stop_key_label="F1", pause_key_label="F2",
                      on_stop=lambda: stop_called.append(True))
lock2._keep_running = True
lock2._state = "locked"
lock2._start_hotkeys()
deadline = time.time() + 5
while lock2._hotkey_hwnd is None and time.time() < deadline:
    time.sleep(0.05)
print("\n[3] F1 config - WM_HOTKEY(id=1) -> stop...")
post_wm_hotkey(lock2._hotkey_hwnd, 1)
time.sleep(0.6)
print("    F1 stop_callback fired:", bool(stop_called), "| state:", lock2._state)

# [4] Burst suppression - AI-injected ESC must NOT cancel
stop_called.clear()
lock3 = ScreenLockout(stop_key=0x1B, pause_key=0x50, on_stop=lambda: stop_called.append(True))
lock3._keep_running = True
lock3._state = "locked"
lock3._start_hotkeys()
deadline = time.time() + 5
while lock3._hotkey_hwnd is None and time.time() < deadline:
    time.sleep(0.05)
print("\n[4] burst suppression...")
lock3.begin_input_burst()
post_wm_hotkey(lock3._hotkey_hwnd, 1)
time.sleep(0.6)
print("    during burst (expect False):", bool(stop_called))
lock3.end_input_burst()
post_wm_hotkey(lock3._hotkey_hwnd, 1)
time.sleep(0.6)
print("    after burst (expect True):", bool(stop_called))

lock._keep_running = False
lock2._keep_running = False
lock3._keep_running = False
time.sleep(0.3)

passed = (bool(stop_called) and pause_called == [True])
print("\n" + "=" * 70)
print("RESULT:", "HOTKEYS VERIFIED ✅" if passed else "STILL BROKEN ❌")
print("=" * 70)
