@echo off
title BankFidelity + UFO Master Configuration
for %%I in ("%~dp0..") do set "UFO_ROOT=%%~fI"
if not defined BF_DIR (for %%I in ("%UFO_ROOT%\..\..\bankfidelity\bankfidelity") do set "BF_DIR=%%~fI")
echo Opening master configuration files...
start notepad.exe "%BF_DIR%\.env"
start notepad.exe "%UFO_ROOT%\config\ufo\agents.yaml"
start notepad.exe "%UFO_ROOT%\config\ufo\system.yaml"
echo Done!
pause
exit /b 0
