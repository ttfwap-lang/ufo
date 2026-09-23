Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win2 {
    [DllImport("user32.dll")] public static extern void SwitchToThisWindow(IntPtr hWnd, bool fAltTab);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, IntPtr pid);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
}
"@
$p = Get-Process Telegram -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
$h = $p.MainWindowHandle

[Win2]::ShowWindow($h, 9) | Out-Null
Start-Sleep -Milliseconds 300

# Force-attach input to the foreground thread, then set foreground
$fg = [Win2]::GetForegroundWindow()
$fgThread = [Win2]::GetWindowThreadProcessId($fg, [IntPtr]::Zero)
$myThread = [Win2]::GetCurrentThreadId()
[Win2]::AttachThreadInput($myThread, $fgThread, $true) | Out-Null
[Win2]::SetForegroundWindow($h) | Out-Null
[Win2]::AttachThreadInput($myThread, $fgThread, $false) | Out-Null
Start-Sleep -Milliseconds 400

# Nuclear option
[Win2]::SwitchToThisWindow($h, $true)
Start-Sleep -Milliseconds 800

$nowFg = [Win2]::GetForegroundWindow()
Write-Output "Telegram hwnd: $h"
Write-Output "Foreground now: $nowFg  (match: $($nowFg -eq $h))"
Write-Output "Title: $($p.MainWindowTitle)"