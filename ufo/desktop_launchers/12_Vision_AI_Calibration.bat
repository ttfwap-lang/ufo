@echo off
setlocal EnableDelayedExpansion
title BANKFIDELITY // VISION AI SUB-PIXEL CALIBRATION & CORRECTION
color 0D
chcp 65001 >nul

set "BF_DIR=C:\Users\lnxzf\Desktop\projects\bankfidelity\bankfidelity"
set "UFO_ROOT=C:\Users\lnxzf\Desktop\projects\ufo\ufo"
set "PYTHON_EXE=C:\Users\lnxzf\AppData\Local\Programs\Python\Python312\python.exe"
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
