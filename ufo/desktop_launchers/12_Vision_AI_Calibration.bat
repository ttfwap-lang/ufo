@echo off
setlocal EnableDelayedExpansion
title BANKFIDELITY // VISION AI SUB-PIXEL CALIBRATION & CORRECTION
color 0D
chcp 65001 >nul

for %%I in ("%~dp0..") do set "UFO_ROOT=%%~fI"
if not defined BF_DIR (for %%I in ("%UFO_ROOT%\..\..\bankfidelity\bankfidelity") do set "BF_DIR=%%~fI")
if not defined PYTHON_EXE set "PYTHON_EXE=python"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%UFO_ROOT%;%BF_DIR%"

cls
echo ==============================================================================
echo               VISION AI SUB-PIXEL CALIBRATION and CORRECTION LOOP
echo ==============================================================================
echo Executes closed-loop visual verification across real bank statements:
echo   1. 300+ DPI High-Resolution Dual-Page Rasterization
echo   2. Structural and Perceptual Diffing (SSIM, PSNR, Pixel MSE)
echo   3. Optical Kerning and Bounding Box Sub-Pixel Calibration
echo   4. Closed-Loop Iterative Layout Correction until SSIM >= 0.998
echo   5. Heatmap Visual Artifact Generation in audit-evidence/vision-calibration/
echo.
echo ==============================================================================
echo.
pause

cd /d "%BF_DIR%"
"%PYTHON_EXE%" "%BF_DIR%\scripts\vision_ai_calibration.py"

echo.
echo ==============================================================================
echo Calibration and Verification Loop Complete. Evidence saved to audit-evidence/
echo ==============================================================================
pause
