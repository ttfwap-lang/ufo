# ==============================================================================
# BANKFIDELITY / UFO DESKTOP PROXY LAUNCHER (PowerShell)
# ==============================================================================
$ErrorActionPreference = 'Stop'
$TargetScript = "C:\Users\lnxzf\Desktop\projects\ufo\ufo\desktop_launchers\BankFidelity_Matrix.ps1"

if (-not (Test-Path $TargetScript)) {
    Write-Error "Target script not found: $TargetScript"
    exit 1
}

Set-Location "C:\Users\lnxzf\Desktop\projects\ufo\ufo"
& $TargetScript
