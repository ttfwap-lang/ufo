<#
    install_scan_task.ps1
    Register the Windows-side change detector to run every 2 minutes.

    Runs at the user's normal integrity and with a hidden window: it only
    reads state and writes a JSON snapshot plus a markdown changelog, so it
    must never steal focus from a UI automation run (which is subject to the
    mandatory countdown gate and the Telegram-foreground rule).
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = 'C:\Users\lnxzf\Desktop\projects\ufo\ufo'
$scan = Join-Path $root 'ufo_scan_win.ps1'
$name = 'UFO-Scan-Windows'

if (-not (Test-Path $scan)) { throw "missing $scan" }

# syntax gate: a broken scanner would fail silently every 2 minutes
$errs = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($scan, [ref]$null, [ref]$errs)
if ($errs -and $errs.Count) { throw "syntax error: $($errs[0].Message)" }
Write-Output '  ufo_scan_win.ps1 syntax OK'

# smoke test before scheduling it
& powershell -NoProfile -ExecutionPolicy Bypass -File $scan -Mode snapshot
& powershell -NoProfile -ExecutionPolicy Bypass -File $scan -Mode diff

Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue

$psExe = (Get-Command powershell.exe).Source
$action = New-ScheduledTaskAction -Execute $psExe `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scan`" -Mode diff" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 2)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

$t = Get-ScheduledTask -TaskName $name
$i = Get-ScheduledTaskInfo -TaskName $name
Write-Output ("task '{0}' state={1} lastResult={2}" -f $t.TaskName, $t.State, $i.LastTaskResult)
Write-Output ("next run: {0}" -f $i.NextRunTime)
Write-Output "changelog: $root\ufo_skill_state\evidence\scan\CHANGES.md"
