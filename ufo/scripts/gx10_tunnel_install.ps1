# Registers (or removes) the "UFO gx10 tunnel" logon task for the current user.
# No admin rights needed; the task runs headless (conhost --headless), so no window appears.
#   powershell -File scripts/gx10_tunnel_install.ps1            # install + start now
#   powershell -File scripts/gx10_tunnel_install.ps1 -Remove    # unregister
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$taskName = "UFO gx10 tunnel"
if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed '$taskName'."
    return
}
$script = Join-Path $PSScriptRoot "gx10_tunnel_keepalive.ps1"
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute "conhost.exe" `
    -Argument "--headless powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Keeps the SSH tunnel to the gx10 (UFO models and Galaxy device) up." -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host "Registered and started '$taskName' (log: $env:LOCALAPPDATA\ufo\gx10_tunnel.log)."
