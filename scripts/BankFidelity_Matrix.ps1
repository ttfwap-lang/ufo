# ==============================================================================
# BANKFIDELITY / UFO DESKTOP PROXY LAUNCHER (PowerShell)
# ==============================================================================
$ErrorActionPreference = 'Stop'
$TargetScript = "C:\ufo\ufo\desktop_launchers\BankFidelity_Matrix.ps1"

if (-not (Test-Path $TargetScript)) {
    Write-Error "Target script not found: $TargetScript"
    exit 1
}

Set-Location "C:\ufo\ufo"
& $TargetScript
