# Finds a working SSH address for the gx10. Dot-source it:  . "$PSScriptRoot\gx10_host.ps1"
#
# Why: everything used to hard-code `gx10.local`. mDNS names come and go (it was
# unresolvable for ~25 minutes of the last outage while the box answered on its LAN
# address the whole time), and blindly launching `ssh` at a starved box is harmful:
# every attempt that stalls in the banner exchange leaves an unauthenticated
# connection on sshd, and sshd drops new ones once MaxStartups (default 10) is
# reached - so a few impatient watchers can lock the box out even after it recovers.
#
# Candidates, in order (first that shows an SSH banner wins):
#   1. $env:UFO_GX10_HOST (comma/space separated, optional override)
#   2. gx10.local
#   3. HostName of `Host gx10-lan` / `Host gx10-tailscale` in ~/.ssh/config
# known_hosts already pins the box's key under each of these names, so trying a
# different address never weakens host-key verification.
#
# Resolve-Gx10Target returns @{ Host; State; Ms; Detail } where State is
#   ok        Host is usable (SSH banner received)
#   wedged    TCP:22 accepts but sshd sends no banner  -> box is up but starved
#   down      nothing answers / cannot resolve
# Only `ok` carries a Host. Ms is the measured connect+banner time of the
# address that was chosen.
#
# WHICH ADDRESS, NOT JUST WHETHER ONE ANSWERS
# ------------------------------------------
# The gx10 has two NICs on the same subnet: 192.168.4.103 is wired and
# measured at ~2 ms, 192.168.4.101 is its Wi-Fi radio at ~68 ms average /
# 127 ms worst. They both answer a banner, so "first one that responds" is
# not good enough - it can silently pin every forwarded port to the radio.
# The probe already opens the connection, so it can time it for free and
# prefer the fastest address that actually answers.
#
# Probing every candidate is NOT free on a sick box: each address that stalls
# in the banner exchange leaves an unauthenticated connection on sshd, and
# past MaxStartups sshd refuses new ones. So the default still short-circuits
# on the first `ok`, and -ProbeAll is only used by callers on a box that is
# already answering - which is exactly when the extra probes are harmless.

function Get-Gx10Candidates {
    $c = New-Object System.Collections.Generic.List[string]
    if ($env:UFO_GX10_HOST) {
        $env:UFO_GX10_HOST -split '[,;\s]+' | Where-Object { $_ } | ForEach-Object { $c.Add($_) }
    }
    $c.Add('gx10.local')
    $cfg = Join-Path $HOME '.ssh\config'
    if (Test-Path $cfg) {
        $cur = $null
        foreach ($line in (Get-Content $cfg -ErrorAction SilentlyContinue)) {
            if ($line -match '^\s*Host\s+(\S+)') { $cur = $Matches[1]; continue }
            if ($cur -in @('gx10-lan', 'gx10-tailscale') -and $line -match '^\s*HostName\s+(\S+)') { $c.Add($Matches[1]) }
        }
    }
    $c | Select-Object -Unique
}

# WHICH ssh.exe - the single biggest latency win on this machine.
#
# Measured 2026-09-26: a 1-byte TCP round trip through an -L forward to an echo
# server on the box. No HTTP, no model, no vLLM anywhere in the path - just
# loopback -> ssh -> wire -> ssh -> echo -> back:
#
#   C:\Program Files\Git\usr\bin\ssh.exe   OpenSSH 10.3p1 / OpenSSL 3.5.7    2.3 ms
#   C:\Windows\System32\OpenSSH\ssh.exe    OpenSSH  9.5p2 / LibreSSL 3.8.2  63.0 ms
#
# Same key, same options, same box, same wire. Every forwarded port pays it, so
# it lands on every LLM call and every grounding call: the real /v1/models
# endpoint measured 58.7 ms through the system client vs 4.1 ms through this
# one, twice, on 40 interleaved samples each.
#
# It is the OLD client's forwarding relay, not the network. On the same box at
# the same moment: PC loopback direct 0.03 ms, box loopback direct 0.01 ms, and
# box->itself through `ssh -L` 0.06 ms. Only the Windows client on the PC is
# slow. Not address-related (a tunnel forced to the wired IP is equally slow),
# not priority-related (a fresh Normal-priority tunnel is equally slow), not
# Nagle (0.43 ms with Nagle on vs 0.40 ms off, on the box).
#
# An `ssh <host> true` round trip does NOT expose this - 423 ms vs 455 ms, both
# swamped by connection setup - so do not try to auto-detect the slow client
# that way. Prefer the newer client, fall back to the system one, and allow an
# override for a machine where the order is different.
function Get-Gx10SshExe {
    if ($env:UFO_SSH_EXE) { return $env:UFO_SSH_EXE }
    $cands = New-Object System.Collections.Generic.List[string]
    if ($env:ProgramFiles) { $cands.Add((Join-Path $env:ProgramFiles 'Git\usr\bin\ssh.exe')) }
    $pf86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
    if ($pf86) { $cands.Add((Join-Path $pf86 'Git\usr\bin\ssh.exe')) }
    $cands.Add('C:\Program Files\Git\usr\bin\ssh.exe')
    if ($env:WINDIR) { $cands.Add((Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe')) }
    foreach ($c in ($cands | Select-Object -Unique)) {
        if (-not (Test-Path $c)) { continue }
        # Run the client, here, in whatever context is asking, and only use one
        # that survives. Do not select on Test-Path alone.
        #
        # Why this check exists: the keepalive used to launch `ssh.exe` by BARE
        # NAME. From an interactive shell that name resolves to the system
        # OpenSSH and everything worked, but the scheduled task's environment
        # resolved it to something that died instantly and every time with
        # 0xC0000142 STATUS_DLL_INIT_FAILED - exit -1073741502, 0s uptime - and
        # the tunnel stayed down across dozens of respawns. I initially blamed
        # Git's MSYS2 build being unable to start headless; that was WRONG, and
        # the log disproved it, because this same scheduled task now runs Git's
        # ssh.exe successfully and it is serving the live tunnel. Which binary
        # the bare name picked in the task's environment is still unexplained.
        #
        # So the durable part of the fix is not a guess about MSYS2 - it is to
        # resolve an absolute path and prove it runs here, instead of trusting a
        # name to mean the same thing in two different environments.
        try {
            $null = & $c -V 2>&1
            if ($LASTEXITCODE -eq 0) { return $c }
        } catch { }
    }
    return 'ssh.exe'   # last resort: whatever is on PATH
}

# scp must come from the same distribution as the ssh that negotiated the host
# key, so derive it from the chosen client rather than picking it separately.
function Get-Gx10ScpExe {
    $ssh = Get-Gx10SshExe
    if ($ssh -like '*\ssh.exe') {
        $scp = Join-Path (Split-Path $ssh) 'scp.exe'
        if (Test-Path $scp) { return $scp }
    }
    return 'scp.exe'
}

# 'ok' | 'wedged' | 'down' for one address, plus the measured connect+banner
# time in Ms. Bounded: never blocks longer than ConnectMs + BannerMs, and
# always closes the socket so it cannot pile up on sshd.
function Test-Gx10Ssh {
    param([string]$Address, [int]$ConnectMs = 3000, [int]$BannerMs = 5000)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $ar = $client.BeginConnect($Address, 22, $null, $null)
        if (-not $ar.AsyncWaitHandle.WaitOne($ConnectMs) -or -not $client.Connected) {
            return @{ State = 'down'; Ms = $sw.ElapsedMilliseconds }
        }
        $client.EndConnect($ar)
        $stream = $client.GetStream()
        $stream.ReadTimeout = $BannerMs
        $buf = New-Object byte[] 16
        try { $n = $stream.Read($buf, 0, $buf.Length) } catch {
            return @{ State = 'wedged'; Ms = $sw.ElapsedMilliseconds }
        }
        if ($n -ge 4 -and [Text.Encoding]::ASCII.GetString($buf, 0, 4) -eq 'SSH-') {
            return @{ State = 'ok'; Ms = $sw.ElapsedMilliseconds }
        }
        return @{ State = 'wedged'; Ms = $sw.ElapsedMilliseconds }
    } catch {
        return @{ State = 'down'; Ms = $sw.ElapsedMilliseconds }   # unresolvable, refused, unreachable
    } finally {
        $client.Close()
    }
}

function Resolve-Gx10Target {
    param([switch]$ProbeAll)
    $states = @()
    $best = $null
    foreach ($addr in (Get-Gx10Candidates)) {
        $r = Test-Gx10Ssh -Address $addr
        $states += "$addr=$($r.State)/$($r.Ms)ms"
        if ($r.State -eq 'ok') {
            if (-not $best -or $r.Ms -lt $best.Ms) { $best = @{ Host = $addr; Ms = $r.Ms } }
            if (-not $ProbeAll) { break }   # fastest-address search is opt-in
        }
    }
    if ($best) {
        return @{ Host = $best.Host; State = 'ok'; Ms = $best.Ms; Detail = ($states -join ' ') }
    }
    $state = if ($states -match '=wedged') { 'wedged' } else { 'down' }
    return @{ Host = $null; State = $state; Ms = $null; Detail = ($states -join ' ') }
}
