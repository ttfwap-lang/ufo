Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class WinSize {
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] static extern bool MoveWindow(IntPtr h, int x, int y, int w, int ht, bool repaint);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    delegate bool EnumProc(IntPtr h, IntPtr p);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
    public static string ResizeTelegram(int x, int y, int w, int ht) {
        var log = new List<string>();
        EnumWindows((h, p) => {
            uint pid; GetWindowThreadProcessId(h, out pid);
            string pn = "?";
            try { pn = System.Diagnostics.Process.GetProcessById((int)pid).ProcessName; } catch {}
            if (pn == "Telegram" && IsWindowVisible(h)) {
                ShowWindow(h, 9);
                MoveWindow(h, x, y, w, ht, true);
                RECT r; GetWindowRect(h, out r);
                log.Add(string.Format("Telegram moved to ({0},{1},{2},{3})", r.L, r.T, r.R, r.B));
            }
            return true;
        }, IntPtr.Zero);
        return string.Join("; ", log);
    }
    public static string FgInfo() {
        var h = GetForegroundWindow();
        var t = new StringBuilder(256); GetWindowTextW(h, t, 256);
        uint pid; GetWindowThreadProcessId(h, out pid);
        string pn = "?";
        try { pn = System.Diagnostics.Process.GetProcessById((int)pid).ProcessName; } catch {}
        return "fg=" + h + " proc=" + pn + " title='" + t.ToString() + "'";
    }
}
"@
# Screen is 1536x960. Fit Telegram with margin, above the taskbar (912).
Write-Output ([WinSize]::ResizeTelegram(60, 40, 1100, 820))
Start-Sleep -Milliseconds 700
Write-Output ([WinSize]::FgInfo())