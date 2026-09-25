# Run the UFO bridge with durable logging.
#
# WHY THIS EXISTS
#   The bridge died at least once and left no trace: the scheduled task showed
#   LastTaskResult 4294967295 and went back to "Ready", and because the task
#   ran python.exe directly there was no stdout/stderr anywhere. Diagnosing
#   "the agent stopped responding" therefore started from zero every time.
#
#   This wrapper gives the bridge a rotating log and a heartbeat file, so:
#     * a crash is diagnosable after the fact
#     * a HANG is distinguishable from a CRASH (heartbeat goes stale)
#
# Scheduled Task -> this script -> python ufo_bridge.py
[CmdletBinding()]
param(
    [int]$RotateMb = 8
)

$ErrorActionPreference = 'Continue'
$root = 'C:\Users\lnxzf\Desktop\projects\ufo\ufo'
$py   = Join-Path $root '.venv\Scripts\python.exe'
$app  = Join-Path $root 'ufo_bridge.py'
$logDir = Join-Path $root 'ufo_skill_state\evidence\bridge'
$log  = Join-Path $logDir 'bridge.log'
$err  = Join-Path $logDir 'bridge.err.log'
$hb   = Join-Path $logDir 'heartbeat.json'

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# ---- rotate by size (keep 3 generations) ----------------------------------
foreach ($f in @($log, $err)) {
    if ((Test-Path $f) -and ((Get-Item $f).Length -gt ($RotateMb * 1MB))) {
        for ($i = 2; $i -ge 1; $i--) {
            $old = "$f.$i"
            if (Test-Path $old) {
                if ($i -ge 3) { Remove-Item $old -Force -ErrorAction SilentlyContinue }
                else { Move-Item $old "$f.$($i + 1)" -Force -ErrorAction SilentlyContinue }
            }
        }
        Move-Item $f "$f.1" -Force -ErrorAction SilentlyContinue
    }
}

function Write-Heartbeat([string]$State, [string]$Detail) {
    # Atomic replace: a watchdog reading this never sees a half-written file.
    $tmp = "$hb.tmp"
    @{ state = $State; detail = $Detail; pid = $PID
       at = (Get-Date).ToUniversalTime().ToString('o') } |
        ConvertTo-Json -Compress | Set-Content -Path $tmp -Encoding utf8
    Move-Item -Path $tmp -Destination $hb -Force
}

Write-Heartbeat 'starting' "wrapper=$PID"
Add-Content -Path $log -Value ("=== bridge start {0} wrapper={1} ===" -f (Get-Date -Format o), $PID)

# Pin the gx10 model endpoints explicitly. A scheduled task does NOT inherit
# the interactive shell's environment, so relying on a variable that happens
# to be set in a terminal produces a bridge that silently cannot see Venus.
# These point at ufo-tunnel.service on gx10 (18000/18002/18061), which
# republishes models that are themselves bound to loopback.
$env:VENUS_URL       = 'http://100.67.13.78:18002/v1'
$env:VENUS_MODEL     = 'ui-venus'
$env:OMNIPARSER_URL  = 'http://100.67.13.78:18061'
$env:VLLM_URL        = 'http://100.67.13.78:18000/v1'
Add-Content -Path $log -Value ("    VENUS_URL=$env:VENUS_URL OMNIPARSER_URL=$env:OMNIPARSER_URL")

# Launch the bridge as a child process and poll it, so the heartbeat is a REAL
# liveness signal. The first version wrote the heartbeat only at start and exit,
# which meant a healthy bridge's heartbeat went permanently stale - and a stale
# heartbeat is indistinguishable from a hung one, so the watchdog could never
# trust it. Refreshing it while the child lives makes "heartbeat old" mean
# exactly one thing: the bridge is wedged.
$proc = Start-Process -FilePath $py `
    -ArgumentList @('-X', 'utf8', $app) `
    -WorkingDirectory $root `
    -RedirectStandardOutput $log `
    -RedirectStandardError  $err `
    -WindowStyle Hidden `
    -PassThru
Add-Content -Path $log -Value ("    child bridge pid={0}" -f $proc.Id)

$lastBeat = Get-Date
while (-not $proc.HasExited) {
    Start-Sleep -Seconds 10
    if ($proc.HasExited) { break }
    # Refresh at most every 30s to avoid churning the file needlessly.
    if (((Get-Date) - $lastBeat).TotalSeconds -ge 30) {
        $lastBeat = Get-Date
        Write-Heartbeat 'running' "bridge=$($proc.Id) uptime=$([int]((Get-Date) - $proc.StartTime).TotalSeconds)s"
    }
}
$code = $proc.ExitCode
Write-Heartbeat 'exited' "code=$code"
Add-Content -Path $log -Value ("=== bridge exit {0} code={1} ===" -f (Get-Date -Format o), $code)
exit $code
