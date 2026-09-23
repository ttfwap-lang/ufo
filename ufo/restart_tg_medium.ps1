# Relaunch Telegram at NORMAL (medium) integrity by handing the launch to the
# user's existing Explorer shell. A "Basic User" trust-level launch kills the
# Qt accessibility bridge (UIA tree comes back empty); medium keeps everything.
$ErrorActionPreference = 'Continue'
$exe = "C:\Users\lnxzf\AppData\Roaming\Telegram Desktop\Telegram.exe"

Get-Process Telegram -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3

# Hand off to the interactive shell -> child inherits the shell's (medium) token
Start-Process -FilePath "explorer.exe" -ArgumentList "`"$exe`""
Start-Sleep -Seconds 10

$p = Get-Process Telegram -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if ($p) {
    Write-Output ("Telegram up: pid={0} title='{1}'" -f $p.Id, $p.MainWindowTitle)
} else {
    Write-Output "Telegram did not start (window not ready yet)"
    Get-Process Telegram -ErrorAction SilentlyContinue | Select-Object Id | Format-Table -AutoSize | Out-String | Write-Output
}