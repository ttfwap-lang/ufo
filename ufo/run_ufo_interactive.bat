@echo off
setlocal EnableDelayedExpansion
title UFO Dream Team Interactive Launcher
color 0B

:: Check for Administrator privileges (Ensures Foreground/Screenshot UI Rights)
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrative privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c cd /d ""%~dp0"" & ""%~nx0"" %*' -Verb RunAs"
    exit /b
)


echo =======================================================================
echo.
echo                       UFO DREAM TEAM LAUNCHER
echo.
echo =======================================================================
echo Ensure you have already started the Dream Team models:
echo (scripts\setup_dream_team.bat)
echo.

:PROMPT_LOOP
set "USER_TASK="
set /p "USER_TASK=Enter your UFO task (or type 'exit' to quit): "

if /i "!USER_TASK!"=="exit" goto END
if "!USER_TASK!"=="" goto PROMPT_LOOP

echo.
echo -----------------------------------------------------------------------
echo Executing Task: "!USER_TASK!"
echo -----------------------------------------------------------------------
echo.

cd /d "C:\ufo\ufo"

set "PYTHON_EXE=C:\ufo\ufo\python_env\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [FATAL] python_env not found at %PYTHON_EXE%
    echo UFO requires the virtual environment to run. Cannot proceed.
    pause
    exit /b 1
)

"%PYTHON_EXE%" -m ufo --task "!USER_TASK!"

echo.
echo -----------------------------------------------------------------------
echo Task Completed.
echo.
goto PROMPT_LOOP

:END
exit /b 0
