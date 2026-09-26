# Register the local OmniParser service to start at logon, headless.
#
# Runs pythonw.exe (no console window, ever) as the CURRENT user - no UAC, no
# SYSTEM. The service redirects its own stdout to local_omniparser\omniparser_local.log.
#
# Self-healing: the task also re-fires every 2 minutes with MultipleInstances
# IgnoreNew - ignored while the service lives, a fresh start if it is dead.
# Task Scheduler's "restart on failure" was tried first and does NOT work here:
# a killed process leaves the task "Ready" (result 0xFFFFFFFF) with no restart,
# the same silent death that hit the bridge.
#
#   powershell -File local_omniparser\install_task.ps1            # install + start
#   powershell -File local_omniparser\install_task.ps1 -Remove    # uninstall
[CmdletBinding()]
param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$name = 'UFO-OmniParser-Local'
$root = Split-Path -Parent $PSScriptRoot
$pyw  = Join-Path $root '.venv_omniparser\Scripts\pythonw.exe'
$svc  = Join-Path $PSScriptRoot 'service.py'

if ($Remove) {
    Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "removed $name"
    return
}
if (-not (Test-Path $pyw)) { throw "missing $pyw - create .venv_omniparser first (see requirements.txt)" }

$action   = New-ScheduledTaskAction -Execute $pyw -Argument ('"{0}"' -f $svc) -WorkingDirectory $root
$logon    = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$repeat   = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 2) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName $name -Action $action -Trigger @($logon, $repeat) -Settings $settings `
    -Description 'Local OmniParser V2 screen parser on 127.0.0.1:7871 (GPU).' -Force | Out-Null
Start-ScheduledTask -TaskName $name
Write-Output "installed and started $name  ($pyw)"
