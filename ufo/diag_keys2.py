"""Deep instrumentation: does injected input reach this session at all?"""
import sys, time, ctypes, threading
from ctypes import wintypes
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# --- 1. Can we read the async key state around a keybd_event press? ---
print("=== Test A: GetAsyncKeyState around keybd_event ===")

def press(vk, hold=0.2):
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(hold)
    user32.keybd_event(vk, 0, 0x0002, 0)

hits = []
def sampler():
    end = time.time() + 2.0
    while time.time() < end:
        s = user32.GetAsyncKeyState(0x1B)
        if s & 0x8000:
            hits.append(True)
        time.sleep(0.002)

th = threading.Thread(target=sampler, daemon=True)
th.start()
time.sleep(0.2)
press(0x1B)
th.join(timeout=3)
print("  async-state hits while held:", len(hits))

# --- 2. RegisterHotKey correctness ---
print("\n=== Test B: RegisterHotKey ===")
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint,
                             wintypes.WPARAM, wintypes.LPARAM)

class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL

wm_hot = []
def wnd_proc(hwnd, msg, wparam, lparam):
    if msg == 0x0312:
        wm_hot.append(wparam & 0xFFFF)
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

proc_ref = WNDPROC(wnd_proc)
wc = WNDCLASS()
wc.lpfnWndProc = proc_ref
wc.hInstance = kernel32.GetModuleHandleW(None)
wc.lpszClassName = "TestHotkeyCls"
atom = user32.RegisterClassW(ctypes.byref(wc))
print("  RegisterClassW atom:", atom)

hwnd = user32.CreateWindowExW(0, "TestHotkeyCls", "x", 0, 0, 0, 0, 0, -3, None, wc.hInstance, None)
print("  CreateWindowExW hwnd:", hwnd)
ok = user32.RegisterHotKey(hwnd, 1, 0, 0x1B)
print("  RegisterHotKey(ESC) result:", ok)

def pump(seconds):
    msg = wintypes.MSG()
    end = time.time() + seconds
    while time.time() < end:
        r = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0x0001)
        if r:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        else:
            time.sleep(0.005)

print("\n  pressing ESC (injected)...")
press(0x1B, 0.2)
pump(1.0)
print("  WM_HOTKEY received:", wm_hot)
print("  foreground window:", user32.GetForegroundWindow())
