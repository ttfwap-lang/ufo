# Applies scripts/dgx to the gx10 once its sshd is usable, then follows the result.
#
#   powershell -File scripts\gx10_apply.ps1            wait for the box, apply, follow
#   powershell -File scripts\gx10_apply.ps1 -DryRun    build + show what would be sent, no ssh
#
# What it does on the box (scripts/dgx/gx10_apply.sh): retire the llama.cpp Qwen 27B so one Qwen
# serves :8000, install the budget + 5%/10% memory guard, recreate the vLLM Qwen / Venus ONLY if
# their running flags differ from gx10_budget.env, and enable OOM protection.
#
# Design for a box that may be wedged again at any moment:
#  - waits with Resolve-Gx10Target (banner check) instead of ssh-ing blindly;
#  - the apply runs DETACHED on the box (setsid nohup) and writes ~/ufo-galaxy/logs/apply.log, so a
#    dropped ssh session cannot kill a model launch half-way;
#  - progress is followed with short ssh calls and every failed poll is just retried;
#  - a failed apply STEP is reported and stops - it does not loop restarting models.
param([switch]$DryRun)
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$key = "$HOME\.ssh\id_ed25519_ufo_agent"
$logDir = Join-Path $env:LOCALAPPDATA "ufo"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "gx10_apply.log"
. (Join-Path $PSScriptRoot 'gx10_host.ps1')

function Write-Log([string]$msg) {
    $line = "{0:u} {1}" -f (Get-Date), $msg
    Write-Host $line
    try { Add-Content -Path $log -Value $line -Encoding utf8 } catch {}
}

# Remote scripts travel base64-encoded on the command line: no BOM (PowerShell 5.1 adds one to text
# piped to a native exe), no quoting hazards, and no `pgrep -f` self-match on the remote shell.
function Invoke-Gx10Script($sshBase, [string]$script) {
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($script -replace "`r", "")))
    & ssh.exe @sshBase "echo $b64 | base64 -d | bash" 2>&1 | Out-String
}

$START = @'
mkdir -p ~/ufo-galaxy/logs ~/ufo-galaxy/dgx-new
tar xzf /tmp/gx10-dgx.tgz -C ~/ufo-galaxy/dgx-new || { echo UNPACK_FAILED; exit 1; }
chmod +x ~/ufo-galaxy/dgx-new/dgx/*.sh
: > ~/ufo-galaxy/logs/apply.log
setsid nohup bash ~/ufo-galaxy/dgx-new/dgx/gx10_apply.sh > ~/ufo-galaxy/logs/apply.log 2>&1 < /dev/null &
echo STARTED
'@
$POLL = @'
tail -n 12 ~/ufo-galaxy/logs/apply.log 2>/dev/null
'@

# --- bundle scripts/dgx (LF, pinned by .gitattributes)
$bundle = Join-Path $env:TEMP "gx10-dgx.tgz"
& tar.exe -czf $bundle -C (Join-Path $repo "scripts") dgx
if ($LASTEXITCODE -ne 0) { Write-Log "ERROR: tar failed ($LASTEXITCODE)"; exit 1 }
$members = & tar.exe -tzf $bundle
Write-Log "bundle: $($members.Count) entries, $([int]((Get-Item $bundle).Length / 1KB)) KB"
if ($DryRun) { $members | ForEach-Object { Write-Host "  $_" }; Write-Log "dry run: nothing sent"; exit 0 }

$mutex = New-Object System.Threading.Mutex($false, "Local\ufo-gx10-apply")
if (-not $mutex.WaitOne(0)) { Write-Log "another apply is running"; exit 0 }
$exit = 1
try {
    $backoff = 15; $lastState = $null; $started = $false
    $deadline = (Get-Date).AddHours(12)
    while ((Get-Date) -lt $deadline) {
        $t = Resolve-Gx10Target
        if ($t.State -ne $lastState) { Write-Log "state: $($t.State) [$($t.Detail)]"; $lastState = $t.State }
        if ($t.State -ne 'ok') { Start-Sleep -Seconds $backoff; $backoff = [Math]::Min($backoff * 2, 300); continue }

        $sshBase = @("-o", "BatchMode=yes", "-o", "ConnectTimeout=25", "-o", "ServerAliveInterval=10",
                     "-i", $key, "flak3dd@$($t.Host)")
        if (-not $started) {
            # A banner is not proof the box can run a command; the upload has to work first.
            & scp.exe -o BatchMode=yes -o ConnectTimeout=25 -i $key $bundle "flak3dd@$($t.Host):/tmp/gx10-dgx.tgz" 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Log "upload failed (rc=$LASTEXITCODE); box answered a banner but not the copy - retrying"; Start-Sleep -Seconds $backoff; continue }
            $out = Invoke-Gx10Script $sshBase $START
            if ($LASTEXITCODE -ne 0 -or $out -notmatch 'STARTED') { Write-Log "start failed (rc=$LASTEXITCODE): $($out.Trim())"; Start-Sleep -Seconds $backoff; continue }
            Write-Log "apply started on $($t.Host); following ~/ufo-galaxy/logs/apply.log"
            $started = $true; $backoff = 15
        }
        Start-Sleep -Seconds 30
        $tail = Invoke-Gx10Script $sshBase $POLL
        if ($LASTEXITCODE -ne 0) { Write-Log "poll failed (rc=$LASTEXITCODE), retrying"; continue }
        if ($tail -match 'APPLY_DONE') { Write-Log "APPLIED:`n$tail"; $exit = 0; break }
        if ($tail -match 'APPLY_FAILED (\S+)') { Write-Log "APPLY FAILED at step '$($Matches[1])':`n$tail"; break }
    }
    if ($exit -ne 0 -and $lastState) { Write-Log "stopped without a completed apply (last state: $lastState)" }
} finally {
    $mutex.ReleaseMutex()
}
exit $exit
