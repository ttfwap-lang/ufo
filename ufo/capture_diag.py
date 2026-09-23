"""Diagnose screen capture from the daemon (SYSTEM) context."""
import ctypes
from ctypes import wintypes
import os, sys, json

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# Window station / desktop of THIS process
h_ws = user32.GetProcessWindowStation()
h_desk = user32.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())

def obj_name(h):
    buf = ctypes.create_unicode_buffer(256)
    need = wintypes.DWORD(0)
    user32.GetUserObjectInformationW(h, 2, buf, 512, ctypes.byref(need))  # UOI_NAME
    return buf.value

print("window station:", obj_name(h_ws))
print("desktop:", obj_name(h_desk))

# Screen metrics
SM_CXSCREEN, SM_CYSCREEN = 0, 1
w = user32.GetSystemMetrics(SM_CXSCREEN)
h = user32.GetSystemMetrics(SM_CYSCREEN)
print(f"screen: {w}x{h}")

# Try BitBlt of the whole screen into a DC
user32.SetProcessDPIAware()
hdc_screen = user32.GetDC(0)
hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
hbm = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
old = gdi32.SelectObject(hdc_mem, hbm)
ok = gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, 0, 0, 0x00CC0020)  # SRCCOPY
print("BitBlt screen -> mem:", ok)

# Check if we got a non-black bitmap (sample a pixel)
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]

bi = BITMAPINFOHEADER()
bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
bi.biWidth = w
bi.biHeight = -h  # top-down
bi.biPlanes = 1
bi.biBitCount = 32
bi.biCompression = 0
buf = ctypes.create_string_buffer(w * h * 4)
lines = gdi32.GetDIBits(hdc_mem, hbm, 0, h, buf, ctypes.byref(bi), 0)
print("GetDIBits lines:", lines)
data = buf.raw
nonblack = sum(1 for i in range(0, len(data), 4 * 997) if data[i] or data[i+1] or data[i+2])
print("non-black sampled pixels:", nonblack)

# Telegram window rect now
def enum_cb(hwnd, lparam):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        import psutil
        pn = psutil.Process(pid.value).name()
    except Exception:
        pn = ""
    if pn.lower() == "telegram.exe":
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        ttl = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, ttl, 256)
        ex = ctypes.c_ulong()
        user32.GetWindowLongW(hwnd, -20, ctypes.byref(ex))
        print(f"TG hwnd={hwnd} class={cls.value} ex=0x{ex.value:08X} "
              f"rect=({r.left},{r.top},{r.right},{r.bottom}) "
              f"iconic={user32.IsIconic(hwnd)} visible={user32.IsWindowVisible(hwnd)} "
              f"title='{ttl.value}'")
    return True
user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(enum_cb), 0)
print("DONE")