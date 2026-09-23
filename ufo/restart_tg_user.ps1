# Relaunch Telegram Desktop as a NON-elevated (Basic User) process so the
# automation stack - which runs as the same user without elevation - can
# manipulate its window directly (UIPI no longer blocks SetWindowPos/input).
# Also inject the WebView2 remote-debugging arg for the child process.
$ErrorActionPreference = 'Continue'
$exe = "C:\Users\lnxzf\AppData\Roaming\Telegram Desktop\Telegram.exe"
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=9222"

Write-Output "Stopping existing Telegram..."
Get-Process Telegram -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3

Write-Output "Launching as Basic User (non-elevated)..."
# /trustlevel:0x20000 = Basic User, strips the admin token from the child
Start-Process -FilePath "runas.exe" -ArgumentList "/trustlevel:0x20000", "`"$exe`""
Start-Sleep -Seconds 10

$p = Get-Process Telegram -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if ($p) {
    Write-Output ("Telegram up: pid={0} title='{1}'" -f $p.Id, $p.MainWindowTitle)
    # Verify integrity level of the new process
    & C:\Users\lnxzf\Desktop\projects\ufo\ufo\.venv\Scripts\python.exe -X utf8 -c @"
import ctypes, psutil
from ctypes import wintypes
advapi = ctypes.windll.advapi32
k = ctypes.windll.kernel32
h = wintypes.HANDLE()
pid = $($p.Id)
ph = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
advapi.OpenProcessToken(ph, 0x0008, ctypes.byref(h))
buf = ctypes.create_string_buffer(1024); n = wintypes.DWORD()
advapi.GetTokenInformation(h, 25, buf, 1024, ctypes.byref(n))  # TokenIntegrityLevel
p = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
cnt = p[1]
s = f'S-{p[0]}-{p[2]}'
for i in range(cnt):
    s += '-' + str(int.from_bytes(bytes(p[8+i*4:12+i*4]), 'little'))
print('Telegram integrity:', s)
"@
} else {
    Write-Output "Telegram did not start"
}
Get-Process Telegram -ErrorAction SilentlyContinue | Select-Object Id, MainWindowTitle | Format-Table -AutoSize | Out-String -Width 120 | Write-Output