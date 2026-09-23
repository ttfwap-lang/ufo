Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class WinMin {
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    delegate bool EnumProc(IntPtr h, IntPtr p);
    public static string MinimizeMatching(string pattern) {
        var log = new List<string>();
        EnumWindows((h, p) => {
            if (!IsWindowVisible(h)) return true;
            var t = new StringBuilder(256); GetWindowTextW(h, t, 256);
            uint pid; GetWindowThreadProcessId(h, out pid);
            string pn = "?";
            try { pn = System.Diagnostics.Process.GetProcessById((int)pid).ProcessName; } catch {}
            if (System.Text.RegularExpressions.Regex.IsMatch(pn, pattern, System.Text.RegularExpressions.RegexOptions.IgnoreCase)) {
                ShowWindow(h, 6);
                log.Add(pn + " '" + t.ToString() + "'");
            }
            return true;
        }, IntPtr.Zero);
        return string.Join("; ", log);
    }
    public static string RaiseTelegram() {
        var log = new List<string>();
        EnumWindows((h, p) => {
            if (!IsWindowVisible(h)) return true;
            var t = new StringBuilder(256); GetWindowTextW(h, t, 256);
            uint pid; GetWindowThreadProcessId(h, out pid);
            string pn = "?";
            try { pn = System.Diagnostics.Process.GetProcessById((int)pid).ProcessName; } catch {}
            if (pn == "Telegram") {
                ShowWindow(h, 9);
                SetWindowPos(h, new IntPtr(-1), 120, 80, 1100, 850, 0x0040); // HWND_TOPMOST, SWP_SHOWWINDOW
                log.Add("raised " + pn + " '" + t.ToString() + "'");
            }
            return true;
        }, IntPtr.Zero);
        return string.Join("; ", log);
    }
    public static string UntopTelegram() {
        var log = new List<string>();
        EnumWindows((h, p) => {
            if (!IsWindowVisible(h)) return true;
            uint pid; GetWindowThreadProcessId(h, out pid);
            string pn = "?";
            try { pn = System.Diagnostics.Process.GetProcessById((int)pid).ProcessName; } catch {}
            if (pn == "Telegram") { SetWindowPos(h, new IntPtr(-2), 0, 0, 0, 0, 0x0003); log.Add("untop"); } // HWND_NOTOPMOST
            return true;
        }, IntPtr.Zero);
        return string.Join("; ", log);
    }
}
"@
Write-Output ("Minimized: " + [WinMin]::MinimizeMatching("idea64|Antigravity|chrome|Monitor|NVIDIA|SmartConnect|SystemSettings|ApplicationFrameHost|TextInputHost|ClickToDo|Microsoft.Notes|opencode|codebuddy"))
Start-Sleep -Milliseconds 400
Write-Output ("Raised: " + [WinMin]::RaiseTelegram())
Start-Sleep -Milliseconds 600
Write-Output "done"