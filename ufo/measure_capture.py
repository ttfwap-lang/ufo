"""Measure the exact capture->screen mapping for the Telegram window."""
import ctypes, sys
from ctypes import wintypes
import win32gui, win32process, win32con

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    print("dpi: per-monitor aware")
except Exception:
    print("dpi: (not set)")

import psutil
target = None
def cb(h, _):
    global target
    try:
        _, pid = win32process.GetWindowThreadProcessId(h)
        if psutil.Process(pid).name().lower() == "telegram.exe" and \
           "QWindowIcon" in win32gui.GetClassName(h):
            target = h
    except Exception:
        pass
win32gui.EnumWindows(cb, None)
print("hwnd:", target)
if not target:
    sys.exit(1)

user32 = ctypes.windll.user32
wr = win32gui.GetWindowRect(target)
cr = win32gui.GetClientRect(target)
pt = wintypes.POINT(0, 0)
user32.ClientToScreen(target, ctypes.byref(pt))
print(f"window rect : {wr}  size={wr[2]-wr[0]}x{wr[3]-wr[1]}")
print(f"client rect : {cr}  size={cr[2]-cr[0]}x{cr[3]-cr[1]}")
print(f"client origin on screen: ({pt.x},{pt.y})")
print(f"frame offset: ({pt.x-wr[0]},{pt.y-wr[1]})")
try:
    import win32ui
    print("screen metrics:", user32.GetSystemMetrics(0), "x", user32.GetSystemMetrics(1))
except Exception:
    pass

from PIL import Image
im = Image.open(r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\astro_state.png")
print("capture size:", im.size)
cw, ch = im.size
clw, clh = cr[2] - cr[0], cr[3] - cr[1]
ww, wh = wr[2] - wr[0], wr[3] - wr[1]
if (cw, ch) == (clw, clh):
    print("=> capture == CLIENT area: physical = bitmap + client_origin")
elif (cw, ch) == (ww, wh):
    print("=> capture == WINDOW incl. frame: physical = bitmap + window_origin")
else:
    sx = cw / (clw or ww)
    sy = ch / (clh or wh)
    print(f"=> capture is SCALED: sx={sx:.4f} sy={sy:.4f}")