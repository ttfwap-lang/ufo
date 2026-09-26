# Brings up the private SSH tunnel to the gx10 and optionally runs a request.
#   Ports: 11434 (Ollama/gemma4-ufo), 8000 (vLLM/qwen), 5001 (UFO Galaxy device server),
#          7861 (OmniParser V2 vision control detection), 8002 (UI-Venus-2 grounding)
# Usage:
#   powershell -File scripts/gx10_up.ps1                      # tunnel only
#   powershell -File scripts/gx10_up.ps1 -Ufo "open notepad"  # single-PC UFO task (drives this desktop)
#   powershell -File scripts/gx10_up.ps1 -Galaxy "report DGX disk usage"  # Galaxy task (DGX device)
param([string]$Ufo, [string]$Galaxy)
$ErrorActionPreference = "Stop"
$key = "$HOME\.ssh\id_ed25519_ufo_agent"
$needed = 11434, 8000, 5001, 7861, 8002
function Get-MissingPorts { $needed | Where-Object { -not (Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue) } }
$missing = Get-MissingPorts
$task = Get-ScheduledTask -TaskName "UFO gx10 tunnel" -ErrorAction SilentlyContinue
if ($missing -and $task) {
    # The logon task (scripts/gx10_tunnel_install.ps1) owns the tunnel; make sure it runs and wait for it.
    if ($task.State -ne "Running") { Start-ScheduledTask -TaskName "UFO gx10 tunnel" }
    for ($i = 0; $i -lt 30 -and ($missing = Get-MissingPorts); $i++) { Start-Sleep -Seconds 1 }
    if ($missing) { Write-Warning "Tunnel task running but ports $($missing -join ',') are not up yet; see $env:LOCALAPPDATA\ufo\gx10_tunnel.log" }
} elseif ($missing) {
    # Forward only the ports not already tunnelled; re-binding a busy port would abort the whole tunnel.
    $forwards = $missing | ForEach-Object { "-L"; "${_}:127.0.0.1:${_}" }
    ssh -f -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -i $key @forwards flak3dd@gx10.local
}
$env:UFO_DGX_HOST = "127.0.0.1"
$env:UFO_DGX_WS_TOKEN = [Environment]::GetEnvironmentVariable("UFO_DGX_WS_TOKEN", "User")
$env:PYTHONIOENCODING = "utf-8"
$ufoPkg = Split-Path $PSScriptRoot -Parent
$env:PYTHONPATH = Split-Path $ufoPkg -Parent
$py = Join-Path $ufoPkg ".venv\Scripts\python.exe"
# Python logs warnings to stderr; under "Stop", Windows PowerShell 5.1 turns that into a terminating error.
$ErrorActionPreference = "Continue"
if ($Ufo) {
    Set-Location (Split-Path $ufoPkg -Parent)
    & $py -m ufo -r $Ufo --skip-preflight
} elseif ($Galaxy) {
    Set-Location $ufoPkg
    & $py -m ufo.galaxy --request $Galaxy
} else {
    Write-Host "Tunnel up on 11434/8000/5001/7861/8002. DGX services are systemd user units (ufo-galaxy.target);"
    Write-Host "restart with ~/ufo-galaxy/start_galaxy_device.sh or ~/OmniParser/start_omniparser.sh."
}
