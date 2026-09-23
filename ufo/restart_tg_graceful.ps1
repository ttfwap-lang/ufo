# Gracefully restart Telegram (WM_CLOSE, wait, then relaunch via Explorer).
# Force-killing Telegram repeatedly can leave its webview/tdata state broken,
# which silently breaks Mini App launches.
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class Grace {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr wp, IntPtr lp);
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
    public static string CloseMain() {
        var log = new System.Collections.Generic.List<string>();
        EnumWindows((h, p) => {
            if (!IsWindowVisible(h)) return true;
            uint pid; GetWindowThreadProcessId(h, out pid);
            string pn = "?";
            try { pn = System.Diagnostics.Process.GetProcessById((int)pid).ProcessName; } catch {}
            if (pn == "Telegram") {
                var t = new StringBuilder(128); GetWindowTextW(h, t, 128);
                if (t.Length > 0) {
                    RECT r; GetWindowRect(h, out r);
                    if (r.R - r.L > 400) {   // the real main window
                        SendMessage(h, 0x0010, IntPtr.Zero, IntPtr.Zero); // WM_CLOSE
                        log.Add("WM_CLOSE -> '" + t + "'");
                    }
                }
            }
            return true;
        }, IntPtr.Zero);
        return string.Join("; ", log);
    }
}
"@
Write-Output ("close: " + [Grace]::CloseMain())
Start-Sleep -Seconds 6
$left = Get-Process Telegram -ErrorAction SilentlyContinue
if ($left) {
    Write-Output "still running, stopping leftovers"
    $left | Stop-Process -Force
    Start-Sleep -Seconds 2
}
Start-Process explorer.exe "C:\Users\lnxzf\AppData\Roaming\Telegram Desktop\Telegram.exe"
Start-Sleep -Seconds 12
$p = Get-Process Telegram -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if ($p) { Write-Output ("relaunched: pid={0} title='{1}'" -f $p.Id, $p.MainWindowTitle) }
else { Write-Output "Telegram not up yet" }