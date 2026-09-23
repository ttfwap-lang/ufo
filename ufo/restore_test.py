"""Can the daemon (SYSTEM) restore the minimized Telegram window?"""
import ctypes, time
from ctypes import wintypes
import win32gui, win32con, win32process
import psutil

target = None
best = None
def cb(hwnd, _):
    global target, best
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if psutil.Process(pid).name().lower() != "telegram.exe":
            return
    except Exception:
        return
    cls = win32gui.GetClassName(hwnd)
    if "QWindowIcon" not in cls:
        return
    if best is None:
        best = hwnd
    if not win32gui.IsIconic(hwnd):
        target = hwnd
    return

win32gui.EnumWindows(cb, None)
hwnd = target or best
print("using hwnd:", hwnd, "iconic:", win32gui.IsIconic(hwnd),
      "visible:", win32gui.IsWindowVisible(hwnd),
      "rect:", win32gui.GetWindowRect(hwnd))

print("--- attempt 1: SW_RESTORE ---")
win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
time.sleep(0.5)
print("iconic now:", win32gui.IsIconic(hwnd), "rect:", win32gui.GetWindowRect(hwnd))

if win32gui.IsIconic(hwnd):
    print("--- attempt 2: SW_SHOW + SetWindowPos ---")
    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, 60, 40, 1100, 820,
                          win32con.SWP_SHOWWINDOW)
    time.sleep(0.5)
    print("iconic now:", win32gui.IsIconic(hwnd), "rect:", win32gui.GetWindowRect(hwnd))

if win32gui.IsIconic(hwnd):
    print("--- attempt 3: SwitchToThisWindow ---")
    ctypes.windll.user32.SwitchToThisWindow(hwnd, True)
    time.sleep(0.6)
    print("iconic now:", win32gui.IsIconic(hwnd), "rect:", win32gui.GetWindowRect(hwnd))

print("FINAL iconic:", win32gui.IsIconic(hwnd),
      "visible:", win32gui.IsWindowVisible(hwnd),
      "rect:", win32gui.GetWindowRect(hwnd),
      "fg:", ctypes.windll.user32.GetForegroundWindow())