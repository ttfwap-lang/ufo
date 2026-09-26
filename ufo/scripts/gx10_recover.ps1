# Waits for the gx10's userspace to come back, then stops OmniParser and
# records what actually happened. Started manually; safe to leave running.
#
#   powershell -File scripts/gx10_recover.ps1
#
# WHY A SEPARATE SCRIPT
# ---------------------
# gx10_tunnel_keepalive.ps1 already restores the SSH tunnel on its own, so
# nothing here is needed to get the ports back. The one thing still outstanding
# is the box itself: OmniParser was serving ~34s per screenshot on CPU and was
# the heaviest single thing on a GB10 whose unified memory was already
# oversubscribed by two LLM pools. It is disabled in config on our side (UFO
# will never call it again), but the service keeps running on gx10.
#
# The failure signature, measured 2026-09-26:
#   - ICMP to 192.168.4.103 answers in 1-2 ms        -> kernel and network fine
#   - TCP :22 accepts, sshd never sends a banner     -> userspace starved
#   - gx10.local does not resolve at all             -> mDNS responder gone
#   - tailscale reports "offline, tx 6240 rx 0"      -> tailscaled not scheduling
# i.e. the box is UP with a wedged userspace, which is memory/swap thrash.
# Nothing remote can free memory without userspace access, so this waits it out
# and acts the moment the banner appears.
#
# It reuses Resolve-Gx10Target from gx10_host.ps1 on purpose: that helper knows
# the MaxStartups hazard (each stalled banner attempt leaves an unauthenticated
# connection on sshd, and sshd drops new ones past 10 - so a few impatient
# watchers can lock the box out even after it recovers). Do not hand-roll a
# polling loop here; call the shared resolver.
$ErrorActionPreference = "Continue"
$key = "$HOME\.ssh\id_ed25519_ufo_agent"
$logDir = Join-Path $env:LOCALAPPDATA "ufo"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "gx10_recover.log"

. (Join-Path $PSScriptRoot 'gx10_host.ps1')

function Write-Log([string]$msg) {
    $line = "{0:u} {1}" -f (Get-Date), $msg
    Write-Host $line
    try {
        if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) { Move-Item -Force $log "$log.1" }
        Add-Content -Path $log -Value $line -Encoding utf8
    } catch {}
}

$mutex = New-Object System.Threading.Mutex($false, "Local\ufo-gx10-recover")
if (-not $mutex.WaitOne(0)) { exit 0 }

# Remote scripts go over STDIN (`bash -s`), never as the ssh command argument. As an argument
# the whole script text is the remote shell's command line, so `pkill -f` / `pgrep -f`
# omniparser match that shell itself (verified in WSL: even 'omniparse[r]' matches, because
# the word appears elsewhere in the text): pkill kills the session mid-script and pgrep can
# never come back clean. CRs are stripped because a CRLF here-string breaks bash.
# $LASTEXITCODE still reflects ssh's exit status after the pipeline.
function Invoke-Gx10Script($sshBase, [string]$script) {
    # Base64 over the command line: no BOM (Windows PowerShell 5.1 prepends one to text piped
    # to a native exe, corrupting the first remote line - verified), no quoting hazards, and the
    # remote shell's command line is just base64 so it can never contain the word omniparser.
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($script -replace "`r", "")))
    & (Get-Gx10SshExe) @sshBase "echo $b64 | base64 -d | bash" 2>&1 | Out-String
}

$DIAG = @'
echo '--- uptime / memory (before) ---'; uptime; free -m
echo '--- swap ---'; swapon --show 2>/dev/null || echo '(no swap)'
echo '--- top cpu ---'; ps -eo pid,pcpu,pmem,rss,comm --sort=-pcpu | head -n 12
echo '--- containers ---'; docker ps --format '{{.Names}}\t{{.Status}}' 2>/dev/null || echo '(no docker)'
'@

$STOP = @'
# Stop OmniParser three ways, because which one applies depends on how the box
# came back: a rebooted box has no user session, so `systemctl --user` is out
# and the container is the thing to stop.
systemctl --user stop omniparser 2>&1 || true
systemctl --user disable omniparser 2>&1 || true
sudo -n systemctl stop omniparser 2>&1 || true
docker stop omniparser 2>&1 || docker stop omniparser-v2 2>&1 || true
# Bracket pattern: 'omniparse[r]' does not match its own text, so this cannot match (and
# kill) the very shell running this command, whose command line contains the script.
pkill -f 'omniparse[r]' 2>&1 || true
echo 'omniparser stop attempted'
'@

# Proves the stop actually took effect. $STOP is a chain of best-effort
# attempts, so "it exited 0" says nothing - every one of those commands can
# no-op and still succeed. This is the only thing allowed to declare victory.
$VERIFY = @'
found=0
if pgrep -f -i 'omniparse[r]' >/dev/null 2>&1; then
    echo "STILL RUNNING (process):"; pgrep -af -i 'omniparse[r]'; found=1
fi
if command -v docker >/dev/null 2>&1; then
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qi omniparser; then
        echo "STILL RUNNING (container):"; docker ps --format '{{.Names}}\t{{.Status}}' | grep -i omniparser; found=1
    fi
fi
for unit in omniparser omniparser-v2; do
    if systemctl is-active --quiet "$unit" 2>/dev/null; then
        echo "STILL RUNNING (systemd $unit)"; found=1
    fi
    if systemctl --user is-active --quiet "$unit" 2>/dev/null; then
        echo "STILL RUNNING (systemd --user $unit)"; found=1
    fi
done
if [ "$found" -eq 0 ]; then echo OMNIPARSER_ABSENT; else echo OMNIPARSER_STILL_PRESENT; fi
'@

Write-Log "waiting for gx10 to become usable (pid $PID)"
$backoff = 15
$lastState = $null
$startedAt = Get-Date
$lastBeat = $startedAt
$cycles = 0
try {
    while ($true) {
        $cycles++
        $t = Resolve-Gx10Target
        if ($t.State -ne $lastState) {
            Write-Log "state: $($t.State) [$($t.Detail)]"
            $lastState = $t.State
        }
        # Heartbeat. A watcher that only logs on CHANGE is indistinguishable
        # from a dead one: on 2026-09-26 this script went silent and there was
        # no way to tell "still waiting" from "killed". Beat unconditionally so
        # that a stale log is itself the alarm.
        if (((Get-Date) - $lastBeat).TotalSeconds -ge 120) {
            $up = [int]((Get-Date) - $startedAt).TotalSeconds
            Write-Log "still waiting: state=$($t.State) up=${up}s cycles=$cycles"
            $lastBeat = Get-Date
        }
        if ($t.State -ne 'ok') {
            Start-Sleep -Seconds $backoff
            $backoff = [Math]::Min($backoff * 2, 300)
            continue
        }

        $host_ = $t.Host
        $backoff = 15
        $sshBase = @("-o", "BatchMode=yes", "-o", "ConnectTimeout=25",
                     "-o", "ServerAliveInterval=10", "-i", $key, "flak3dd@$host_")

        # A banner from Resolve-Gx10Target is NOT proof the box is usable. It is
        # a single probe, and a thrashing host can service one connection and
        # then get buried again - observed 2026-09-26: state went ok at 16:30:10
        # and the very next ssh timed out during banner exchange, three times
        # running. So the work has to be attempted, and its exit code believed.
        Write-Log "state ok via $host_ - attempting the work"

        $before = Invoke-Gx10Script $sshBase $DIAG
        $beforeRc = $LASTEXITCODE
        Write-Log "--- diagnostics BEFORE (rc=$beforeRc) ---"
        Write-Log $before
        if ($beforeRc -ne 0) {
            Write-Log "connection did not hold (rc=$beforeRc) - still waiting"
            Start-Sleep -Seconds 30
            $lastState = $null      # force the next transition to be logged
            continue
        }

        $stopOut = Invoke-Gx10Script $sshBase $STOP
        $stopRc = $LASTEXITCODE
        Write-Log "--- stop OmniParser (rc=$stopRc) ---"
        Write-Log $stopOut
        if ($stopRc -ne 0) {
            Write-Log "stop command failed (rc=$stopRc) - retrying next cycle"
            Start-Sleep -Seconds 30
            continue
        }

        Start-Sleep -Seconds 20
        $after = Invoke-Gx10Script $sshBase $DIAG
        $afterRc = $LASTEXITCODE
        Write-Log "--- diagnostics AFTER (rc=$afterRc) ---"
        Write-Log $after

        # Only believe success if omniparser is demonstrably gone. "the stop
        # command exited 0" is not proof - it is a chain of systemctl/docker/
        # pkill attempts, any of which can no-op. Reporting done on a command
        # that silently did nothing is how this ended up claiming victory while
        # OmniParser was still eating the box.
        $verify = Invoke-Gx10Script $sshBase $VERIFY
        $verifyRc = $LASTEXITCODE
        Write-Log "--- verify omniparser gone (rc=$verifyRc) ---"
        Write-Log $verify
        $gone = ($verifyRc -eq 0) -and ($verify -match 'OMNIPARSER_ABSENT')

        if ($gone) {
            Write-Log "=== CONFIRMED: OmniParser is stopped and no longer running ==="
            break
        }
        Write-Log "OmniParser still present - will keep trying"
        Start-Sleep -Seconds 30
    }
} catch {
    Write-Log "ERROR: $($_.Exception.Message)"
} finally {
    $mutex.ReleaseMutex()
}
