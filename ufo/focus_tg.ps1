Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr hWnd);
}
"@
$p = Get-Process Telegram -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if ($p) {
    [Win]::ShowWindow($p.MainWindowHandle, 9) | Out-Null   # SW_RESTORE
    [Win]::BringWindowToTop($p.MainWindowHandle) | Out-Null
    [Win]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
    Start-Sleep -Milliseconds 800
    $fg = [Win]::GetForegroundWindow()
    Write-Output "Telegram hwnd: $($p.MainWindowHandle)"
    Write-Output "Foreground == Telegram: $($fg -eq $p.MainWindowHandle)"
    Write-Output "Title: $($p.MainWindowTitle)"
} else {
    Write-Output "Telegram window not found"
}