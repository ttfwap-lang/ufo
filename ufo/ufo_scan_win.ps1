<#
    ufo_scan_win.ps1 - change detector for the Windows side of the UFO stack.

    WHY
      Another agent is editing this repository and the gx10 deployment at the
      same time. One-off "check it all again" passes kept producing stale or
      wrong answers, because the state moved between commands. This records a
      snapshot and reports ONLY the delta, so the answer to "what changed while
      I was working?" is always available and never guessed.

    CONTRACT
      * Read-only. It observes; bridge_watchdog.ps1 repairs.
      * Never prints secret VALUES. File contents are hashed; only .env KEY
        names are listed, and their values are hashed.
      * Silent (one line) when nothing changed.

    Usage:
      ufo_scan_win.ps1 snapshot | diff | show
#>
[CmdletBinding()]
param(
    [ValidateSet('snapshot', 'diff', 'show')]
    [string]$Mode = 'diff'
)

$ErrorActionPreference = 'Continue'
$root = 'C:\Users\lnxzf\Desktop\projects\ufo\ufo'
$dir  = Join-Path $root 'ufo_skill_state\evidence\scan'
$snap = Join-Path $dir 'scan.json'
$prev = Join-Path $dir 'scan.prev.json'
$log  = Join-Path $dir 'changes.log'
$latest = Join-Path $dir 'CHANGES.md'
New-Item -ItemType Directory -Force -Path $dir | Out-Null

function Get-Sha([string]$p, [int]$n = 12) {
    try { return (Get-FileHash -Path $p -Algorithm SHA256).Hash.Substring(0, $n).ToLower() }
    catch { return $null }
}
function Get-PortState([int]$port) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
         Select-Object -First 1
    if (-not $c) { return @{ listening = $false } }
    return @{ listening = $true; pid = $c.OwningProcess; addr = $c.LocalAddress }
}
function Get-Health([string]$url) {
    try {
        $r = Invoke-WebRequest -Uri $url -TimeoutSec 8 -UseBasicParsing
        return @{ code = $r.StatusCode; body = $r.Content }
    } catch { return @{ code = 0; body = '' } }
}

# ---------------------------------------------------------------- snapshot
function New-Snapshot {
    $s = [ordered]@{
        at = (Get-Date).ToUniversalTime().ToString('o')
        git = @{}
        files = @{}
        env_keys = @{}
        tasks = @{}
        ports = @{}
        procs = 0
    }

    # git
    Push-Location $root
    try {
        $s.git.head   = (& git rev-parse --short HEAD 2>$null)
        $s.git.branch = (& git rev-parse --abbrev-ref HEAD 2>$null)
        $porcelain = @(& git status --porcelain 2>$null)
        $s.git.dirty = $porcelain.Count
        $s.git.staged = @($porcelain | Where-Object { $_ -match '^[MADRC]' }).Count
        $s.git.untracked = @($porcelain | Where-Object { $_ -match '^\?\?' }).Count
        # file-level view: this is what actually tells you what the other agent did
        $s.git.changed = @($porcelain | ForEach-Object {
            [ordered]@{ st = $_.Substring(0, 2); path = $_.Substring(3) }
        })
        $s.git.unpushed = [int](& git rev-list --count '@{u}..HEAD' 2>$null)
    } catch { $s.git.error = $_.Exception.Message }
    finally { Pop-Location }

    # key source files (content hash -> catches edits + swaps)
    $watch = @(
        'ufo_bridge.py', 'venus_client.py', 'astro_collect.py', 'run_collect.py',
        'e2e_test.py', 'check_integrity.py', 'test_bridge_store.py',
        'install_bridge_task.ps1', 'run_bridge.ps1', 'bridge_watchdog.ps1',
        'ufo_scan_win.ps1',
        'gx10_runner\agent_runner.py', 'gx10_runner\omniparser_api.py',
        'gx10_runner\rebalance_models.sh', 'gx10_runner\venus_run.sh',
        'automator\app_apis\telegram\telegram_gui.py'
    )
    foreach ($f in $watch) {
        $p = Join-Path $root $f
        if (Test-Path $p) {
            $i = Get-Item $p
            $s.files[$f] = [ordered]@{ sha = Get-Sha $p; size = $i.Length; mtime = $i.LastWriteTimeUtc.ToString('o') }
        }
    }

    # .env / token files: KEYS ONLY, values hashed. Never emit a secret.
    foreach ($ef in @('gx10_runner\.env', 'ufo_bridge_token.txt')) {
        $p = Join-Path $root $ef
        if (Test-Path $p) {
            $keys = @{}
            foreach ($line in (Get-Content $p -ErrorAction SilentlyContinue)) {
                $l = $line.Trim()
                if ($l -and -not $l.StartsWith('#') -and $l.Contains('=')) {
                    $kv = $l.Split('=', 2)
                    $bytes = [Text.Encoding]::UTF8.GetBytes($kv[1])
                    $h = [BitConverter]::ToString(
                        [Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
                    ).Replace('-', '').Substring(0, 8).ToLower()
                    $keys[$kv[0].Trim()] = $h
                }
            }
            $s.env_keys[$ef] = $keys
        }
    }

    # scheduled tasks we own
    foreach ($t in @('UFO-Bridge-9301', 'UFO-Bridge-Watchdog')) {
        $task = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
        if ($task) {
            $i = Get-ScheduledTaskInfo -TaskName $t
            $s.tasks[$t] = [ordered]@{ state = [string]$task.State; last = $i.LastTaskResult
                                       ran = $i.LastRunTime.ToString('o') }
        }
    }

    $s.ports['9301'] = Get-PortState 9301
    $s.health = Get-Health 'http://127.0.0.1:9301/health'
    $s.procs = @(Get-Process python, pythonw -ErrorAction SilentlyContinue).Count

    $s | ConvertTo-Json -Depth 8 | Set-Content -Path $snap -Encoding UTF8
    Write-Output ("snapshot -> {0} (git {1} dirty={2}, {3} files, {4} tasks)" -f `
        $snap, $s.git.head, $s.git.dirty, $s.files.PSObject.Properties.Count, $s.tasks.PSObject.Properties.Count)
}

# ---------------------------------------------------------------- diff
function Compare-Snapshot {
    if (-not (Test-Path $snap)) { Write-Output 'no snapshot yet'; return }
    if (-not (Test-Path $prev)) {
        "baseline captured $((Get-Content $snap -Raw | ConvertFrom-Json).at); nothing to compare" |
            Set-Content $latest
        Copy-Item $snap $prev -Force
        Write-Output 'baseline captured'
        return
    }
    $n = Get-Content $snap  -Raw | ConvertFrom-Json
    $o = Get-Content $prev -Raw | ConvertFrom-Json
    $L = [System.Collections.Generic.List[string]]::new()

    # git
    if ($o.git.head -ne $n.git.head) { $L.Add("~ git HEAD        $($o.git.head) -> $($n.git.head)") }
    if ($o.git.branch -ne $n.git.branch) { $L.Add("~ git BRANCH      $($o.git.branch) -> $($n.git.branch)") }
    if ($o.git.dirty -ne $n.git.dirty) { $L.Add("~ git DIRTY COUNT $($o.git.dirty) -> $($n.git.dirty)") }
    if ($o.git.unpushed -ne $n.git.unpushed) { $L.Add("~ git UNPUSHED    $($o.git.unpushed) -> $($n.git.unpushed)") }
    $oc = @{}; foreach ($c in $o.git.changed) { $oc[$c.path] = $c.st }
    $nc = @{}; foreach ($c in $n.git.changed) { $nc[$c.path] = $c.st }
    foreach ($p in ($nc.Keys | Sort-Object)) {
        if (-not $oc.ContainsKey($p)) { $L.Add("+ file APPEARED   $($nc[$p])  $p") }
    }
    foreach ($p in ($oc.Keys | Sort-Object)) {
        if (-not $nc.ContainsKey($p)) { $L.Add("- file GONE       $($oc[$p])  $p") }
        elseif ($oc[$p] -ne $nc[$p]) { $L.Add("~ file STATUS     $p  $($oc[$p]) -> $($nc[$p])") }
    }

    # watched source files
    $of = $o.files.PSObject.Properties; $nf = $n.files.PSObject.Properties
    $onames = $of.Name; $nnames = $nf.Name
    foreach ($f in ($nnames | Where-Object { $onames -notcontains $_ })) { $L.Add("+ source ADDED    $f") }
    foreach ($f in ($onames | Where-Object { $nnames -notcontains $_ })) { $L.Add("- source REMOVED  $f") }
    foreach ($p in $nf) {
        $op = $of | Where-Object { $_.Name -eq $p.Name }
        if ($op -and $op.Value.sha -ne $p.Value.sha) { $L.Add("~ source EDITED   $($p.Name)  sha $($op.Value.sha) -> $($p.Value.sha)") }
    }

    # env keys (values never shown)
    foreach ($ef in $n.env_keys.PSObject.Properties) {
        $of2 = $o.env_keys.PSObject.Properties | Where-Object { $_.Name -eq $ef.Name }
        if (-not $of2) { $L.Add("+ env FILE ADDED  $ $($ef.Name)"); continue }
        $a = $of2.Value.PSObject.Properties.Name
        $b = $ef.Value.PSObject.Properties.Name
        foreach ($k in ($b | Where-Object { $a -notcontains $_ })) { $L.Add("+ env KEY   $k  (in $($ef.Name))") }
        foreach ($k in ($a | Where-Object { $b -notcontains $_ })) { $L.Add("- env KEY   $k  (in $($ef.Name))") }
        foreach ($p in $ef.Value.PSObject.Properties) {
            $op2 = $of2.Value.PSObject.Properties | Where-Object { $_.Name -eq $p.Name }
            # Report that a value changed, never what it is.
            if ($op2 -and $op2.Value -ne $p.Value) {
                $L.Add("~ env VALUE $($p.Name) changed in $($ef.Name) (value not shown)")
            }
        }
    }

    # tasks / ports / health
    foreach ($t in $n.tasks.PSObject.Properties) {
        $ot = $o.tasks.PSObject.Properties | Where-Object { $_.Name -eq $t.Name }
        if (-not $ot) { $L.Add("+ task ADDED      $($t.Name) $($t.Value.state)"); continue }
        if ($ot.Value.state -ne $t.Value.state) { $L.Add("~ task STATE      $($t.Name)  $($ot.Value.state) -> $($t.Value.state)") }
        if ($ot.Value.last -ne $t.Value.last) { $L.Add("~ task LASTRESULT $($t.Name)  $($ot.Value.last) -> $($t.Value.last)") }
    }
    if ($o.health.code -ne $n.health.code) { $L.Add("~ bridge /health  HTTP $($o.health.code) -> $($n.health.code)") }
    $op2 = $o.ports.'9301'; $np2 = $n.ports.'9301'
    if ($op2.listening -ne $np2.listening) { $L.Add("~ port 9301       listening $($op2.listening) -> $($np2.listening)") }
    if ($op2.pid -ne $np2.pid) { $L.Add("~ port 9301 pid   $($op2.pid) -> $($np2.pid)") }
    if ($o.procs -ne $n.procs) { $L.Add("~ python procs    $($o.procs) -> $($n.procs)") }

    $stamp = $n.at
    if ($L.Count -eq 0) {
        "# Change log`n`n$stamp  no changes`n" | Set-Content $latest
        Write-Output "$stamp  no changes"
    } else {
        $body = "`n## $stamp  ($($L.Count) change(s))`n`n" + (($L | ForEach-Object { "- $_" }) -join "`n") + "`n"
        Add-Content $log $body
        "# Change log`n" | Set-Content $latest
        Add-Content $latest $body
        Write-Output "$stamp  $($L.Count) change(s)"
        $L | ForEach-Object { Write-Output "   $_" }
    }
    Copy-Item $snap $prev -Force
}

switch ($Mode) {
    'snapshot' { New-Snapshot }
    'diff'     { New-Snapshot | Out-Null; Compare-Snapshot }
    'show'     { Get-Content $snap -Raw }
}
