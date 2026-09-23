# Fit Telegram to a sane, fully-on-screen size for this 125% DPI display,
# then report the logical rect, the physical rect and the expected capture size.
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class WinFit {
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] static extern bool MoveWindow(IntPtr h, int x, int y, int w, int ht, bool repaint);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] static extern int GetSystemMetrics(int i);
    delegate bool EnumProc(IntPtr h, IntPtr p);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
    public static string Fit(int x, int y, int w, int ht) {
        var log = new List<string>();
        int sw = GetSystemMetrics(0), sh = GetSystemMetrics(1);
        log.Add("logical screen: " + sw + "x" + sh);
        EnumWindows((h, p) => {
            uint pid; GetWindowThreadProcessId(h, out pid);
            string pn = "?";
            try { pn = System.Diagnostics.Process.GetProcessById((int)pid).ProcessName; } catch {}
            if (pn == "Telegram" && IsWindowVisible(h)) {
                ShowWindow(h, 9);
                MoveWindow(h, x, y, w, ht, true);
                SetForegroundWindow(h);
                RECT r; GetWindowRect(h, out r);
                log.Add(string.Format("logical rect=({0},{1},{2},{3}) size={4}x{5}", r.L, r.T, r.R, r.B, r.R - r.L, r.B - r.T));
            }
            return true;
        }, IntPtr.Zero);
        return string.Join(" | ", log);
    }
}
"@
Write-Output ([WinFit]::Fit(50, 40, 1150, 800))