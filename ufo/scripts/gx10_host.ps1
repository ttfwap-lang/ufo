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
# Resolve-Gx10Target returns @{ Host; State; Detail } where State is
#   ok        Host is usable (SSH banner received)
#   wedged    TCP:22 accepts but sshd sends no banner  -> box is up but starved
#   down      nothing answers / cannot resolve
# Only `ok` carries a Host.

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

# 'ok' | 'wedged' | 'down' for one address. Bounded: never blocks longer than
# ConnectMs + BannerMs, and always closes the socket so it cannot pile up on sshd.
function Test-Gx10Ssh {
    param([string]$Address, [int]$ConnectMs = 3000, [int]$BannerMs = 5000)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $ar = $client.BeginConnect($Address, 22, $null, $null)
        if (-not $ar.AsyncWaitHandle.WaitOne($ConnectMs) -or -not $client.Connected) { return 'down' }
        $client.EndConnect($ar)
        $stream = $client.GetStream()
        $stream.ReadTimeout = $BannerMs
        $buf = New-Object byte[] 16
        try { $n = $stream.Read($buf, 0, $buf.Length) } catch { return 'wedged' }
        if ($n -ge 4 -and [Text.Encoding]::ASCII.GetString($buf, 0, 4) -eq 'SSH-') { return 'ok' }
        return 'wedged'
    } catch {
        return 'down'   # unresolvable, refused, unreachable
    } finally {
        $client.Close()
    }
}

function Resolve-Gx10Target {
    $states = @()
    foreach ($addr in (Get-Gx10Candidates)) {
        $s = Test-Gx10Ssh -Address $addr
        $states += "$addr=$s"
        if ($s -eq 'ok') { return @{ Host = $addr; State = 'ok'; Detail = ($states -join ' ') } }
    }
    $state = if ($states -match '=wedged') { 'wedged' } else { 'down' }
    return @{ Host = $null; State = $state; Detail = ($states -join ' ') }
}
