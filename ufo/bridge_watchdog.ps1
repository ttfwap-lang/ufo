<#
    bridge_watchdog.ps1 - keep the UFO bridge alive and prove it is alive.

    WHY
      The bridge is the only thing standing between the gx10 agent and the
      Windows desktop. It failed once with no log and no recovery: the
      scheduled task sat in "Ready" with LastTaskResult 4294967295, so the
      agent's tool calls just stopped resolving and nothing said why.

      This checks three different failure shapes, because they need different
      responses:
        DEAD    - nothing listening           -> start the task
        HUNG    - listening but not answering -> restart (it holds the port)
        CRASHED - heartbeat stale             -> restart with the log preserved

    Run every 2 minutes from the "UFO-Bridge-Watchdog" scheduled task.
#>
[CmdletBinding()]
param(
    [string]$HealthUrl   = 'http://127.0.0.1:9301/health',
    [string]$BridgeTask  = 'UFO-Bridge-9301',
    [int]   $TimeoutSec  = 10
)

$ErrorActionPreference = 'Continue'
$root = 'C:\Users\lnxzf\Desktop\projects\ufo\ufo'
$logDir = Join-Path $root 'ufo_skill_state\evidence\bridge'
$log  = Join-Path $logDir 'watchdog.log'
$hb   = Join-Path $logDir 'heartbeat.json'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

. (Join-Path $PSScriptRoot 'scripts\fastwin.ps1')   # fast port/task queries
if (-not (Get-Command Get-TaskQuick -ErrorAction SilentlyContinue)) {
    # A missing helper must be an error, not a silently wrong 'bridge is down'.
    throw 'scripts\fastwin.ps1 did not load (Get-TaskQuick missing)'
}

function Write-WLog([string]$Level, [string]$Message) {
    $line = '{0}  {1,-6} {2}' -f (Get-Date).ToUniversalTime().ToString('o'), $Level, $Message
    Add-Content -Path $log -Value $line
    if ((Test-Path $log) -and (Get-Item $log).Length -gt 4MB) {
        Move-Item $log "$log.1" -Force -ErrorAction SilentlyContinue
    }
}

function Test-BridgeHealthy {
    try {
        $r = Invoke-WebRequest -Uri $HealthUrl -TimeoutSec $TimeoutSec -UseBasicParsing
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Get-HeartbeatAgeSec {
    if (-not (Test-Path $hb)) { return -1 }
    try {
        $j = Get-Content $hb -Raw -Encoding UTF8 | ConvertFrom-Json
        $at = [datetime]::Parse($j.at).ToUniversalTime()
        return [int]((Get-Date).ToUniversalTime() - $at).TotalSeconds
    } catch { return -1 }
}

function Get-Listener {
    # netstat, not Get-NetTCPConnection (1,281 ms vs 39 ms; see scripts\fastwin.ps1)
    Get-ListenerQuick 9301
}

function Start-Bridge {
    Write-WLog ACTION "starting task $BridgeTask"
    Start-ScheduledTask -TaskName $BridgeTask -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        if (Test-BridgeHealthy) {
            Write-WLog INFO  "bridge healthy after $i s"
            return $true
        }
    }
    Write-WLog ERROR "bridge did NOT become healthy within 20 s"
    return $false
}

function Restart-Bridge([string]$Why) {
    Write-WLog ACTION "restarting bridge ($Why)"
    $log_ = Join-Path $logDir 'bridge.log'
    if (Test-Path $log_) {
        $tail = Get-Content $log_ -Tail 25 -ErrorAction SilentlyContinue
        if ($tail) {
            Write-WLog INFO ("last bridge output: " + (($tail -join ' | ') -replace '\s+', ' ').Substring(0, [Math]::Min(600, (($tail -join ' | ') -replace '\s+', ' ').Length)))
        }
    }
    Stop-ScheduledTask -TaskName $BridgeTask -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'ufo_bridge' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    Start-Bridge | Out-Null
}

# ---- OmniParser: catch a FROZEN service, not just a dead one -----------------
# UFO-OmniParser-Local re-fires every 2 min with IgnoreNew, which restarts a service
# that has DIED. A process that is alive but not answering still counts as "running"
# and is ignored indefinitely. One such stall was observed (health timed out for
# >60 s, then answered again after a debugger attach); the cause was not found -
# a trimmed working set and BelowNormal priority were both measured and ruled out.
# Whatever the cause, restarting is the safe answer.
$OmniHealthUrl = 'http://127.0.0.1:7871/api/health'
$OmniTask      = 'UFO-OmniParser-Local'

function Repair-OmniParser {
    $l = Get-ListenerQuick 7871
    if (-not $l) { return }                       # dead: the task's own repeat trigger starts it
    try { $age = ((Get-Date) - (Get-Process -Id $l.OwningProcess -ErrorAction Stop).StartTime).TotalSeconds }
    catch { return }
    if ($age -lt 120) { return }                  # still loading models / warming up
    foreach ($i in 1..2) {
        try {
            $r = Invoke-WebRequest -Uri $OmniHealthUrl -TimeoutSec 10 -UseBasicParsing
            if ($r.StatusCode -eq 200) { return }
        } catch { }
        if ($i -eq 1) { Start-Sleep -Seconds 5 }
    }
    Write-WLog ACTION ("omniparser pid $($l.OwningProcess) (up $([int]$age)s) is listening on 7871 " +
                       "but /api/health failed twice - restarting")
    Stop-ScheduledTask -TaskName $OmniTask -ErrorAction SilentlyContinue
    Stop-Process -Id $l.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName $OmniTask -ErrorAction SilentlyContinue
}
Repair-OmniParser

# ---- decide ----------------------------------------------------------------
$task = Get-TaskQuick $BridgeTask   # schtasks, not Get-ScheduledTask (125 ms vs ~3 s)
if (-not $task) {
    Write-WLog ERROR "scheduled task '$BridgeTask' does not exist - run install_bridge_task.ps1"
    exit 1
}

$healthy = Test-BridgeHealthy
$listener = Get-Listener
$hbAge = Get-HeartbeatAgeSec

if ($healthy -and $hbAge -ge 0 -and $hbAge -lt 300) {
    Write-WLog INFO "ok  listener=pid$($listener.OwningProcess)  heartbeat=${hbAge}s"
    exit 0
}

if ($healthy -and $hbAge -ge 300) {
    # Answers /health but the heartbeat is stale: the running process is not
    # the instrumented wrapper, so we cannot tell crash from hang.
    Write-WLog WARN "healthy but heartbeat is ${hbAge}s old - wrapper not in use; leaving alone"
    exit 0
}

if ($listener) {
    # Port held but not answering: a hang. A restart is the only way out, and
    # the port must be released first or the new instance cannot bind.
    Restart-Bridge "listening on 9301 but /health did not answer"
    exit 0
}

# Nothing listening at all.
$state = $task.State
$info  = $task
Write-WLog WARN "bridge down (task=$state lastResult=$($info.LastTaskResult))"
Start-Bridge | Out-Null
exit 0
