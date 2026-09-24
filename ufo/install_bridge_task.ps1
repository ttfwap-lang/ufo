# Register the UFO bridge as a logon-started scheduled task so it survives
# shell/session restarts (it was previously only a background shell process).
$ErrorActionPreference = 'Stop'

$py  = "C:\Users\lnxzf\Desktop\projects\ufo\ufo\.venv\Scripts\python.exe"
$br  = "C:\Users\lnxzf\Desktop\projects\ufo\ufo\ufo_bridge.py"
$work = "C:\Users\lnxzf\Desktop\projects\ufo\ufo"
$name = "UFO-Bridge-9301"

if (-not (Test-Path $py))  { throw "python not found: $py" }
if (-not (Test-Path $br))  { throw "bridge not found: $br" }

# stop any previous instance
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'ufo_bridge' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute $py -Argument "`"$br`"" -WorkingDirectory $work
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
# Run at the user's normal integrity: an ELEVATED bridge launching Telegram
# would give it a high-integrity token and break the UIA/capture path.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Start-ScheduledTask -TaskName $name
Start-Sleep -Seconds 6

$task = Get-ScheduledTask -TaskName $name
$info = Get-ScheduledTaskInfo -TaskName $name
Write-Output ("task '{0}' state={1} lastResult={2}" -f $task.TaskName, $task.State, $info.LastTaskResult)

$listen = Get-NetTCPConnection -State Listen -LocalPort 9301 -ErrorAction SilentlyContinue
if ($listen) {
    Write-Output ("listening on 9301 (pid {0})" -f $listen[0].OwningProcess)
} else {
    Write-Output "NOT listening yet - check the task"
}
