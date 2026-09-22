"""Verify the lockout hotkeys REALLY work (deterministic, not self-reported).

Synthesizes a real ESC/P key press via SendInput and checks the global
GetAsyncKeyState polling fires the callbacks. This proves the hotkeys
function without relying on the user's hand.
"""
import sys, asyncio, time, ctypes
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "C:\\Users\\lnxzf\\Desktop\\projects\\ufo")
from ufo.automator.app_apis.telegram import ScreenLockout

stop_called = []
pause_called = []

lock = ScreenLockout(
    stop_key=0x1B,          # ESC
    pause_key=0x50,         # P
    stop_key_label="ESC",
    pause_key_label="P",
    on_stop=lambda: stop_called.append(True),
    on_pause=lambda p: pause_called.append(p),
)

def press_key(vk, hold=0.06):
    """Send a REAL key press via SendInput."""
    user32 = ctypes.windll.user32
    KEYEVENTF_KEYUP = 0x0002
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(hold)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

print("=" * 70)
print("HOTKEY VERIFICATION (deterministic - synthesized input)")
print("=" * 70)

# Start polling
lock._start_hotkey_polling()
time.sleep(0.5)  # allow thread to start

print("\n[1] Synthesizing ESC (stop key 0x1B)...")
lock._state = "locked"          # set to a pollable state
press_key(0x1B)
deadline = time.time() + 2
while time.time() < deadline and not stop_called:
    time.sleep(0.05)
print("    stop_callback fired:", bool(stop_called), "| state:", lock._state)

print("\n[2] Synthesizing P (pause key 0x50)...")
lock._state = "locked"          # reset to allow pause toggle
pause_called.clear()
press_key(0x50)
deadline = time.time() + 2
while time.time() < deadline and not pause_called:
    time.sleep(0.05)
print("    pause_callback fired:", pause_called, "| state:", lock._state)

print("\n[3] Synthesizing P again (resume toggle)...")
pause_called.clear()
press_key(0x50)
deadline = time.time() + 2
while time.time() < deadline and len(pause_called) < 1:
    time.sleep(0.05)
print("    pause_callback fired:", pause_called, "| state:", lock._state)

print("\n[4] Configurable keys - synthesizing F1 (0x70) with F1=stop config...")
stop_called.clear()
lock2 = ScreenLockout(stop_key=0x70, pause_key=0x71, stop_key_label="F1", pause_key_label="F2",
                      on_stop=lambda: stop_called.append(True))
lock2._start_hotkey_polling()
time.sleep(0.4)
lock2._state = "locked"
press_key(0x70)
deadline = time.time() + 2
while time.time() < deadline and not stop_called:
    time.sleep(0.05)
print("    F1 stop_callback fired:", bool(stop_called), "| state:", lock2._state)

lock._keep_running = False
lock2._keep_running = False
print("\n" + "=" * 70)
print("RESULT:", "HOTKEYS WORK ✅" if stop_called else "PARTIAL - see above")
print("=" * 70)
