Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win5 { [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n); }
"@
$procs = Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and $_.ProcessName -notmatch "Telegram" }
$procs | Select-Object Id, ProcessName, MainWindowTitle | Format-Table -AutoSize | Out-String -Width 160 | Write-Output
foreach ($p in $procs) {
    if ($p.MainWindowTitle -match "OpenCode|Codebuddy" -or $p.ProcessName -match "opencode|codebuddy") {
        Write-Output "Minimizing: $($p.ProcessName) - '$($p.MainWindowTitle)'"
        [Win5]::ShowWindow($p.MainWindowHandle, 6) | Out-Null
    }
}
Start-Sleep -Milliseconds 500
Write-Output "done"