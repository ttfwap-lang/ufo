# Keeps the private SSH tunnel to the gx10 up for as long as the user is logged on.
#   Ports: 11434 (Ollama), 8000 (vLLM/qwen), 5001 (Galaxy device server),
#          7861 (OmniParser V2), 8002 (UI-Venus-2) - all to 127.0.0.1 on the gx10.
# Started at logon by the "UFO gx10 tunnel" scheduled task (scripts/gx10_tunnel_install.ps1),
# headless. Restarts ssh with backoff when it exits, and re-forwards any port that
# stops listening. Log: %LOCALAPPDATA%\ufo\gx10_tunnel.log
$ErrorActionPreference = "Continue"
$key = "$HOME\.ssh\id_ed25519_ufo_agent"
$needed = 11434, 8000, 5001, 7861, 8002
$logDir = Join-Path $env:LOCALAPPDATA "ufo"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "gx10_tunnel.log"

. (Join-Path $PSScriptRoot 'gx10_host.ps1')

function Write-Log([string]$msg) {
    try {
        if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) { Move-Item -Force $log "$log.1" }
        Add-Content -Path $log -Value ("{0:u} {1}" -f (Get-Date), $msg) -Encoding utf8
    } catch {}
}

. (Join-Path $PSScriptRoot 'fastwin.ps1')

function Get-MissingPorts {
    # .NET listener table, 10 ms per check vs 1.3 s each for Get-NetTCPConnection
    $needed | Where-Object { -not (Test-PortListening $_) }
}

# Single instance per user session.
$mutex = New-Object System.Threading.Mutex($false, "Local\ufo-gx10-tunnel")
if (-not $mutex.WaitOne(0)) { exit 0 }

Write-Log "keepalive started (pid $PID)"
$backoff = 5
$lastState = $null
try {
    while ($true) {
        $missing = @(Get-MissingPorts)
        if (-not $missing) { Start-Sleep -Seconds 30; continue }

        # Find an address whose sshd actually answers before launching ssh at it.
        # (gx10.local is not always resolvable, and ssh at a starved sshd only adds
        # more half-open connections to it.) Log on state change, not every loop.
        $target = Resolve-Gx10Target
        if (-not $target.Host) {
            if ($target.State -ne $lastState) { Write-Log "gx10 not reachable: $($target.State) [$($target.Detail)]"; $lastState = $target.State }
            Start-Sleep -Seconds $backoff
            $backoff = [Math]::Min($backoff * 2, 60)
            continue
        }
        if ($lastState -ne 'ok') { Write-Log "gx10 reachable via $($target.Host) [$($target.Detail)]"; $lastState = 'ok' }

        $sshArgs = @("-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                     "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4",
                     "-o", "ConnectTimeout=15", "-i", $key)
        foreach ($p in $missing) { $sshArgs += @("-L", "${p}:127.0.0.1:${p}") }
        $sshArgs += "flak3dd@$($target.Host)"
        Write-Log "starting ssh for ports $($missing -join ',')"
        $started = Get-Date
        $proc = Start-Process -FilePath "ssh.exe" -ArgumentList $sshArgs -NoNewWindow -PassThru
        $null = $proc.Handle  # keep the handle so ExitCode is available after exit

        # Watch: restart if ssh exits, or if a needed port stops listening
        # (e.g. another tunnel that held it went away) so it gets re-forwarded.
        while (-not $proc.WaitForExit(30000)) {
            if (@(Get-MissingPorts).Count -gt 0 -and ((Get-Date) - $started).TotalSeconds -gt 60) {
                Write-Log "ports missing while ssh (pid $($proc.Id)) runs; restarting it"
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            }
        }
        $ranFor = ((Get-Date) - $started).TotalSeconds
        Write-Log ("ssh exited (code {0}) after {1:N0}s" -f $proc.ExitCode, $ranFor)
        if ($ranFor -gt 120) { $backoff = 5 } else { $backoff = [Math]::Min($backoff * 2, 120) }
        Start-Sleep -Seconds $backoff
    }
} finally {
    $mutex.ReleaseMutex()
}
