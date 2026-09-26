# Fast replacements for the two cmdlets that dominate every recurring watcher.
#
# Measured on this machine (warm, one call each):
#   Get-NetTCPConnection -State Listen -LocalPort N     1,281 ms
#   Get-ScheduledTask + Get-ScheduledTaskInfo (x2)      6,205 ms
# versus the equivalents below:
#   .NET GetActiveTcpListeners                             30 ms   (43x)
#   netstat -ano (when the owning PID is needed)           26 ms   (49x)
#   schtasks /query /v                                    125 ms   (50x)
#
# Dot-source it:   . "$PSScriptRoot\scripts\fastwin.ps1"
# Return shapes deliberately mimic the cmdlets they replace, so callers barely
# change: .OwningProcess / .LocalAddress, and .State / .LastTaskResult.

function Test-PortListening([int]$Port) {
    # Boolean only. No PID; use Get-ListenerQuick when you need the owner.
    foreach ($l in [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()) {
        if ($l.Port -eq $Port) { return $true }
    }
    return $false
}

function Get-ListenerQuick([int]$Port) {
    # Like Get-NetTCPConnection -State Listen -LocalPort $Port | Select -First 1
    foreach ($line in (netstat -ano -p TCP)) {
        if ($line -match "^\s*TCP\s+(\S+):$Port\s+\S+\s+LISTENING\s+(\d+)") {
            return [pscustomobject]@{ LocalAddress = $Matches[1]; LocalPort = $Port
                                      OwningProcess = [int]$Matches[2] }
        }
    }
    return $null
}

function Get-TaskQuick([string]$Name) {
    # Like Get-ScheduledTask + Get-ScheduledTaskInfo. $null when the task is absent.
    # Positional CSV columns (not header names) so a non-English Windows still works:
    #   1 Host  2 TaskName  3 NextRun  4 Status  5 LogonMode  6 LastRun  7 LastResult
    $out = & schtasks.exe /query /tn $Name /fo csv /v /nh 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
    $r = @($out | ConvertFrom-Csv -Header (1..40 | ForEach-Object { "c$_" }))[0]
    $lr = 0L
    [void][int64]::TryParse($r.c7, [ref]$lr)
    $ran = $null
    try { $ran = [datetime]::Parse($r.c6) } catch { }
    [pscustomobject]@{
        Name = $Name; State = $r.c4
        LastTaskResult = [uint32]($lr -band 0xFFFFFFFFL)   # schtasks may print -1 for 0xFFFFFFFF
        LastRunTime = $ran
    }
}
