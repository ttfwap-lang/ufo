@echo off
title BANKFIDELITY // OMNIPOTENT 1000% STRESS TEST GAUNTLET
chcp 65001 >nul
color 0A

for %%I in ("%~dp0..") do set "UFO_ROOT=%%~fI"
if not defined BF_DIR (for %%I in ("%UFO_ROOT%\..\..\bankfidelity\bankfidelity") do set "BF_DIR=%%~fI")
if not defined PYTHON_EXE set "PYTHON_EXE=python"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%UFO_ROOT%;%BF_DIR%"

echo ==================================================================================
echo               BANKFIDELITY OMNIPOTENT 1000%% STRESS TEST GAUNTLET
echo                    36-Pair Permutation Cross-Bank Transfer Matrix
echo ==================================================================================
echo.
echo This test executes the full 36-combination cross-bank transfer matrix across:
echo   - Commonwealth Bank (SmartAccess)
echo   - Bankwest (Classic Qantas)
echo   - ING (Orange Everyday)
echo   - Macquarie Bank (Transaction)
echo   - Westpac (Choice Basic)
echo   - ANZ Plus (Everyday)
echo.
echo Key Engine Features:
echo   1. Real Cloud API Calls (Reducto, Gemini, PyMuPDF Pro, Typst, Document AI)
echo   2. 300+ DPI Dual-Page Rasterization and Pure-NumPy SSIM / PSNR / MSE Heatmaps
echo   3. 100%% Mathematical Running Balance Reconciliation
echo   4. Continuous Self-Healing (Continues past any edge anomaly without halting)
echo   5. Dual Delivery: Generates OMNIPOTENT_STRESS_TEST_REPORT.md on your Desktop
echo.
echo Press ANY KEY to begin the full 1000%% automated stress test run...
echo ==================================================================================
pause

cd /d "%BF_DIR%"
"%PYTHON_EXE%" "%BF_DIR%\scripts\omnipotent_stress_test.py"

echo.
echo ==================================================================================
echo Stress Test Gauntlet Complete! Review OMNIPOTENT_STRESS_TEST_REPORT.md on Desktop.
echo ==================================================================================
pause
