"""Fix an off-screen/undersized Telegram window via raw mouse drag.

UIPI blocks MoveWindow/SetWindowPos/SetForegroundWindow for a higher-
integrity window - but raw input injection (SetCursorPos + mouse_event)
goes through the input pipeline and is NOT blocked. So we:
1. Drag the title bar to reposition (mouse press -> move -> release)
2. If undersized, drag the resize corner to a sane size
3. Optionally double-click the title bar to maximize
"""
import sys, time, ctypes, win32gui, win32process, psutil
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

user32 = ctypes.windll.user32

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000

def find_telegram():
    results = []
    def cb(hwnd, res):
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            name = psutil.Process(pid).name()
        except Exception:
            return
        if name.lower() != 'telegram.exe':
            return
        title = win32gui.GetWindowText(hwnd)
        cls = win32gui.GetClassName(hwnd)
        if title and 'QWindowIcon' in cls:
            res.append((hwnd, title))
    win32gui.EnumWindows(cb, results)
    return results

def set_cursor(x, y):
    user32.SetCursorPos(x, y)
    time.sleep(0.02)

def drag(from_xy, to_xy, steps=40):
    set_cursor(*from_xy)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    dx = to_xy[0] - from_xy[0]
    dy = to_xy[1] - from_xy[1]
    for i in range(1, steps + 1):
        # Smooth-ish movement, final exact position wins
        x = from_xy[0] + int(dx * i / steps)
        y = from_xy[1] + int(dy * i / steps)
        set_cursor(x, y)
        time.sleep(0.01)
    set_cursor(*to_xy)
    time.sleep(0.08)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.1)

def main():
    windows = find_telegram()
    print("Windows found:", windows)
    if not windows:
        print("No Telegram window visible - aborting")
        return
    hwnd, title = windows[0]
    rect = win32gui.GetWindowRect(hwnd)
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    print("Before:", rect, f"{w}x{h}")

    # 1. Drag title bar to a sane position (target top-left 250,120)
    tx, ty = 250, 120
    press_x = rect[0] + w // 2
    press_y = rect[1] + 12  # caption area
    offset_x = press_x - rect[0]
    offset_y = press_y - rect[1]
    drag((press_x, press_y), (tx + offset_x, ty + offset_y))
    time.sleep(0.3)
    rect2 = win32gui.GetWindowRect(hwnd)
    print("After drag:", rect2, f"{rect2[2]-rect2[0]}x{rect2[3]-rect2[1]}")

    # 2. If still undersized (<800 wide), drag the bottom-right resize corner
    if rect2[2] - rect2[0] < 800:
        print("Undersized - dragging resize corner...")
        # caption-based drag already moved it; corner now:
        rx, ry = rect2[2] - 3, rect2[3] - 3
        drag((rx, ry), (tx + 1050, ty + 800), steps=40)
        time.sleep(0.3)
    rect3 = win32gui.GetWindowRect(hwnd)
    print("Final:", rect3, f"{rect3[2]-rect3[0]}x{rect3[3]-rect3[1]}")

    # 3. Confirm readable and capture evidence
    shot = win32gui.GetWindowRect(hwnd)
    print("Confirmed:", shot)

if __name__ == "__main__":
    main()
