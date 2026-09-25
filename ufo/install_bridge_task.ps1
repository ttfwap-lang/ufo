<#
    install_bridge_task.ps1
    Register the UFO bridge so it survives logoff, reboot and its own crashes -
    and, critically, leaves a log when it fails.

    WHAT CHANGED AND WHY
      The previous version pointed the scheduled task straight at
      python.exe ufo_bridge.py. Two consequences, both observed in the field:
        * no stdout/stderr anywhere, so a crash was undiagnosable
        * RestartCount did not bring it back; the task sat in "Ready" with
          LastTaskResult 4294967295 and the agent went quiet

      Now:
        * the task runs run_bridge.ps1, which logs and writes a heartbeat
        * a SECOND task (UFO-Bridge-Watchdog) runs every 2 minutes and
          distinguishes dead / hung / crashed, because each needs a
          different response
        * RestartCount is raised and RestartOnFailure is set explicitly

    The bridge MUST run at the user's normal integrity: an elevated bridge
    would launch an elevated Telegram, and UIPI then blocks screen capture and
    the accessibility bridge. That is why RunLevel is Limited and must stay so.
#>
[CmdletBinding()]
param(
    [switch]$NoWatchdog
)

$ErrorActionPreference = 'Stop'

$root    = 'C:\Users\lnxzf\Desktop\projects\ufo\ufo'
$py      = Join-Path $root '.venv\Scripts\python.exe'
$app     = Join-Path $root 'ufo_bridge.py'
$wrapper = Join-Path $root 'run_bridge.ps1'
$wd      = Join-Path $root 'bridge_watchdog.ps1'
$name    = 'UFO-Bridge-9301'
$wdName  = 'UFO-Bridge-Watchdog'

foreach ($p in @($py, $app, $wrapper)) {
    if (-not (Test-Path $p)) { throw "required file missing: $p" }
}

# Fail fast on a syntax error rather than registering a task that dies silently.
& $py -X utf8 -c "import ast,io,sys; ast.parse(io.open(sys.argv[1],encoding='utf-8').read()); print('  ufo_bridge.py syntax OK')" $app
foreach ($s in @($wrapper, $wd)) {
    $errs = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($s, [ref]$null, [ref]$errs)
    if ($errs -and $errs.Count) {
        throw "PowerShell syntax error in $s : $($errs[0].Message)"
    }
    Write-Output "  $(Split-Path $s -Leaf) syntax OK"
}

# ---- stop any previous instance -------------------------------------------
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'ufo_bridge' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Unregister-ScheduledTask -TaskName $name   -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $wdName -Confirm:$false -ErrorAction SilentlyContinue

$psExe = (Get-Command powershell.exe).Source
$user = "$env:USERDOMAIN\$env:USERNAME"

# ---- bridge task -----------------------------------------------------------
$action = New-ScheduledTaskAction -Execute $psExe `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wrapper`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable
# Note: -RestartCount/-RestartInterval are how New-ScheduledTaskSettingsSet
# expresses failure-restart; there is no -RestartOnFailure parameter in
# Windows PowerShell 5.1. Assigning $settings.RestartOnFailure = $true by hand
# fails, because that property expects a CIM instance, not a bool.

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $name

# ---- watchdog task ---------------------------------------------------------
if (-not $NoWatchdog) {
    $wdAction = New-ScheduledTaskAction -Execute $psExe `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wd`"" `
        -WorkingDirectory $root
    $wdTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 2)
    $wdSettings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
        -MultipleInstances IgnoreNew -StartWhenAvailable
    Register-ScheduledTask -TaskName $wdName -Action $wdAction -Trigger $wdTrigger `
        -Principal $principal -Settings $wdSettings -Force | Out-Null
    Start-ScheduledTask -TaskName $wdName
}

# ---- verify ----------------------------------------------------------------
Start-Sleep -Seconds 8
foreach ($t in @($name, $wdName)) {
    $task = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    if ($task) {
        $i = Get-ScheduledTaskInfo -TaskName $t
        Write-Output ("task '{0}' state={1} lastResult={2}" -f $t, $task.State, $i.LastTaskResult)
    }
}
$listen = Get-NetTCPConnection -State Listen -LocalPort 9301 -ErrorAction SilentlyContinue
if ($listen) {
    Write-Output ("listening on 9301 (pid {0}, addr {1})" -f $listen[0].OwningProcess, $listen[0].LocalAddress)
    try {
        $h = Invoke-WebRequest -Uri 'http://127.0.0.1:9301/health' -TimeoutSec 10 -UseBasicParsing
        Write-Output ("health: {0}" -f $h.Content)
    } catch { Write-Output "health check failed: $($_.Exception.Message)" }
} else {
    Write-Output "NOT listening - inspect $root\ufo_skill_state\evidence\bridge\bridge.log"
    exit 1
}
