@echo off
:: ==============================================================================
:: BANKFIDELITY / UFO DESKTOP PROXY LAUNCHER
:: ==============================================================================
:: This proxy safely forwards execution to the canonical script in C:\Users\lnxzf\Desktop\projects\ufo\ufo.
:: It prevents %%~dp0 resolution bugs when run from the Desktop.

set "UFO_ROOT=C:\Users\lnxzf\Desktop\projects\ufo\ufo"
cd /d "%UFO_ROOT%"

if not exist "C:\Users\lnxzf\Desktop\projects\ufo\ufo\desktop_launchers\03_AI_Dream_Team_Launcher.bat" (
    echo [ERROR] Target script not found: C:\Users\lnxzf\Desktop\projects\ufo\ufo\desktop_launchers\03_AI_Dream_Team_Launcher.bat
    pause
    exit /b 1
)

:: Forward execution to the actual launcher
call "C:\Users\lnxzf\Desktop\projects\ufo\ufo\desktop_launchers\03_AI_Dream_Team_Launcher.bat"
exit /b %ERRORLEVEL%
