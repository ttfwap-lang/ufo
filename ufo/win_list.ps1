Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class WinEnum {
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    delegate bool EnumProc(IntPtr h, IntPtr p);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }

    public static List<string> List() {
        var res = new List<string>();
        EnumWindows((h, p) => {
            if (!IsWindowVisible(h)) return true;
            var t = new StringBuilder(256); GetWindowTextW(h, t, 256);
            var c = new StringBuilder(256); GetClassNameW(h, c, 256);
            uint pid; GetWindowThreadProcessId(h, out pid);
            RECT r; GetWindowRect(h, out r);
            string pn = "?";
            try { pn = System.Diagnostics.Process.GetProcessById((int)pid).ProcessName; } catch {}
            res.Add(string.Format("hwnd={0} pid={1} proc={2} class={3} rect=({4},{5},{6},{7}) title='{8}'",
                h, pid, pn, c.ToString(), r.L, r.T, r.R, r.B, t.ToString()));
            return true;
        }, IntPtr.Zero);
        return res;
    }
    public static string MinimizeMatching(string pattern) {
        var log = new List<string>();
        EnumWindows((h, p) => {
            if (!IsWindowVisible(h)) return true;
            var t = new StringBuilder(256); GetWindowTextW(h, t, 256);
            string pn = "?";
            uint pid; GetWindowThreadProcessId(h, out pid);
            try { pn = System.Diagnostics.Process.GetProcessById((int)pid).ProcessName; } catch {}
            if (System.Text.RegularExpressions.Regex.IsMatch(pn + " " + t.ToString(), pattern, System.Text.RegularExpressions.RegexOptions.IgnoreCase)) {
                ShowWindow(h, 6);
                log.Add("minimized " + pn + " '" + t.ToString() + "'");
            }
            return true;
        }, IntPtr.Zero);
        return string.Join("; ", log);
    }
    public static IntPtr Fg() { return GetForegroundWindow(); }
}
"@
Write-Output "=== Visible windows ==="
[WinEnum]::List() | ForEach-Object { Write-Output $_ }
Write-Output ""
Write-Output "=== Foreground hwnd ==="
[WinEnum]::Fg()