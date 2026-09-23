# Allow the DGX (tailnet) to reach the UFO bridge on 9301.
# Scoped to private/tailnet ranges - not "Any".
$name = "UFO Bridge 9301 (tailnet)"
if (-not (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort 9301 -Profile Any | Out-Null
}
# Scope the remote addresses to the tailnet + the LAN used for the gx10 link
foreach ($net in @("100.64.0.0/10", "192.168.0.0/16", "10.0.0.0/8")) {
    $rname = "$name [$net]"
    if (-not (Get-NetFirewallRule -DisplayName $rname -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $rname -Direction Inbound -Action Allow `
            -Protocol TCP -LocalPort 9301 -RemoteAddress $net -Profile Any | Out-Null
    }
}
Get-NetFirewallRule -DisplayName "$name*" | Select-Object DisplayName, Enabled, Direction, Action |
    Format-Table -AutoSize | Out-String -Width 120 | Write-Output
Write-Output "listening:"
Get-NetTCPConnection -State Listen -LocalPort 9301 -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize |
    Out-String | Write-Output
Write-Output "tailnet ips:"
Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" } |
    Select-Object InterfaceAlias, IPAddress | Format-Table -AutoSize |
    Out-String | Write-Output