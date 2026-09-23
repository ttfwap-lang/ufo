# Restart Telegram Desktop with WebView2 remote debugging enabled.
# Same user (LENOVO\lnxzf, session 1) => same profile, no re-login.
$ErrorActionPreference = 'Continue'
$exe = "C:\Users\lnxzf\AppData\Roaming\Telegram Desktop\Telegram.exe"

# 1) Set the WebView2 debug arg for the child process
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=9222"

# 2) Kill existing Telegram (same user, allowed - we are elevated as that user)
Get-Process Telegram -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3

# 3) Relaunch with the env var inherited
Start-Process -FilePath $exe
Write-Output "launched, waiting for window..."

# 4) Wait for the main window to appear (up to 30s)
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 2
    $p = Get-Process Telegram -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -ne "" }
    if ($p) {
        Write-Output ("Telegram up: pid={0} title='{1}'" -f $p.Id, $p.MainWindowTitle)
        break
    }
}
Get-Process Telegram -ErrorAction SilentlyContinue | Select-Object Id, SessionId, MainWindowTitle | Format-Table -AutoSize | Out-String -Width 160 | Write-Output