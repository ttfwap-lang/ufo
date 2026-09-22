"""ELEVATED window fix - run via JetBrains elevated.exe.

Fixes the Telegram window that is blocked by UIPI from the non-elevated
agent: MoveWindow to a sane size, bring to foreground, verify, and write
results to a file the non-elevated side can read.
"""
import sys, time, json, ctypes
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import win32gui, win32process, win32con, psutil

OUT = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\elev_fix_result.json"

def find_telegram():
    results = []
    def cb(hwnd, res):
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            name = psutil.Process(pid).name()
        except Exception:
            return
        if name.lower() != "telegram.exe":
            return
        title = win32gui.GetWindowText(hwnd)
        cls = win32gui.GetClassName(hwnd)
        if title and "QWindowIcon" in cls:
            res.append((hwnd, title, cls))
    win32gui.EnumWindows(cb, results)
    return results

def main():
    result = {"ok": False, "steps": []}
    try:
        windows = find_telegram()
        result["steps"].append(("found_windows", str(windows)))
        if not windows:
            result["error"] = "no telegram window"
            _write(result)
            return 1
        hwnd, title, cls = windows[0]
        result["hwnd"] = hwnd
        before = win32gui.GetWindowRect(hwnd)
        result["before"] = list(before)

        # 1. Restore if minimized
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            result["steps"].append(("restored", True))
        # 2. Move to sane size/position
        win32gui.MoveWindow(hwnd, 200, 100, 1050, 800, True)
        result["steps"].append(("moved", True))
        time.sleep(0.4)
        # 3. Foreground
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        result["steps"].append(("foreground", True))
        time.sleep(0.3)

        after = win32gui.GetWindowRect(hwnd)
        result["after"] = list(after)
        fg = ctypes.windll.user32.GetForegroundWindow()
        result["foreground_ok"] = bool(fg == hwnd)
        result["ok"] = True
    except Exception as e:
        result["error"] = repr(e)
        _write(result)
        return 1
    _write(result)
    return 0

def _write(result):
    try:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("write err", e)

if __name__ == "__main__":
    sys.exit(main())
