@echo off
:: ==============================================================================
:: BANKFIDELITY / UFO DESKTOP PROXY LAUNCHER
:: ==============================================================================
:: This proxy safely forwards execution to the canonical script in C:\ufo\ufo.
:: It prevents %%~dp0 resolution bugs when run from the Desktop.

set "UFO_ROOT=C:\ufo\ufo"
cd /d "%UFO_ROOT%"

if not exist "C:\ufo\ufo\desktop_launchers\02_UFO_Control_Panel.bat" (
    echo [ERROR] Target script not found: C:\ufo\ufo\desktop_launchers\02_UFO_Control_Panel.bat
    pause
    exit /b 1
)

:: Forward execution to the actual launcher
call "C:\ufo\ufo\desktop_launchers\02_UFO_Control_Panel.bat"
exit /b %ERRORLEVEL%
