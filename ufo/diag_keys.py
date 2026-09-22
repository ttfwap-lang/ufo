"""Diagnose GetAsyncKeyState polling against synthesized input."""
import sys, time, ctypes, threading
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

USER32 = ctypes.windll.user32
KEYEVENTF_KEYUP = 0x0002
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

VK_ESC = 0x1B

# --- 1. keybd_event + tight GetAsyncKeyState polling ---
def press_keybd_event(vk, hold=0.1):
    USER32.keybd_event(vk, 0, 0, 0)
    time.sleep(hold)
    USER32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

def poll_async(vk, duration=1.0):
    hits = []
    end = time.time() + duration
    while time.time() < end:
        state = USER32.GetAsyncKeyState(vk)
        if state & 0x8000:
            hits.append(time.time())
        time.sleep(0.01)
    return hits

t = threading.Thread(target=poll_async, args=(VK_ESC, 2.0), daemon=True)
t.start()
time.sleep(0.3)
press_keybd_event(VK_ESC, hold=0.3)
t.join()
print("[keybd_event] getasync hits while held:", len([h for h in []]))

# Better: sample in same thread around the press
hits = []
def sampler():
    end = time.time() + 2.2
    last = 0
    while time.time() < end:
        s = USER32.GetAsyncKeyState(VK_ESC)
        if s & 0x8000:
            hits.append(time.time())
        time.sleep(0.005)
th = threading.Thread(target=sampler, daemon=True)
th.start()
time.sleep(0.3)
press_keybd_event(VK_ESC, hold=0.4)
th.join()
print("[keybd_event] async-state 0x8000 samples while held:", len(hits))

# --- 2. SendInput + polling ---
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", ctypes.c_byte * 28)]
    _anonymous_ = ("i",)
    _fields_ = [("type", ctypes.c_ulong), ("i", _I)]

def send_input_vk(vk, up=False):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    USER32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

hits2 = []
def sampler2():
    end = time.time() + 2.2
    while time.time() < end:
        if USER32.GetAsyncKeyState(VK_ESC) & 0x8000:
            hits2.append(time.time())
        time.sleep(0.005)
th = threading.Thread(target=sampler2, daemon=True)
th.start()
time.sleep(0.3)
send_input_vk(VK_ESC)
time.sleep(0.4)
send_input_vk(VK_ESC, up=True)
th.join()
print("[SendInput]   async-state 0x8000 samples while held:", len(hits2))

# --- 3. Foreground check - what window has focus now? ---
fg = USER32.GetForegroundWindow()
import win32gui
print("[context] foreground window:", repr(win32gui.GetWindowText(fg)) if fg else None)
