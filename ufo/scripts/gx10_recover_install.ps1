# Registers (or removes) the "UFO gx10 recover" logon task: the watcher that
# waits for the gx10's userspace to come back and then stops OmniParser.
#
#   powershell -File scripts/gx10_recover_install.ps1            # install + start
#   powershell -File scripts/gx10_recover_install.ps1 -Remove
#
# WHY A SCHEDULED TASK AND NOT A BACKGROUND SHELL
# ------------------------------------------------
# Run as a plain background process, this watcher gets killed with whatever
# launched it. On 2026-09-26 it was started as an agent shell job, reported a
# false success (it never checked an exit code), died silently, and left no
# trace that distinguished "still waiting" from "dead" - while the
# "UFO gx10 tunnel" task, which IS a scheduled task, carried on correctly the
# whole time. Long-lived watchers belong to Task Scheduler, not to a shell.
#
# The script also logs a heartbeat every ~2 minutes precisely so that "no news"
# is never ambiguous: a stale log is the alarm.
param([switch]$Remove)
$ErrorActionPreference = "Stop"

$taskName = "UFO gx10 recover"
$script = Join-Path $PSScriptRoot "gx10_recover.ps1"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed '$taskName'."
    return
}

if (-not (Test-Path $script)) { throw "gx10_recover.ps1 not found: $script" }
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

# conhost --headless so no console window can ever appear, matching
# scripts/litellm_install.ps1 and scripts/gx10_tunnel_install.ps1.
$action = New-ScheduledTaskAction -Execute "conhost.exe" `
    -Argument "--headless powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Waits for the gx10 to become usable, then stops OmniParser and records memory." `
    -Force | Out-Null
Start-ScheduledTask -TaskName $taskName

$info = Get-ScheduledTask -TaskName $taskName
Write-Host "Registered '$taskName' -> state: $($info.State)"
Write-Host "Log: $env:LOCALAPPDATA\ufo\gx10_recover.log"
Write-Host "It will only report success when the gx10 itself confirms OmniParser is gone."
