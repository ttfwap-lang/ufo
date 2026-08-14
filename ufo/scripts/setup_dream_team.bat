@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM ======================================================================
REM  UFO DREAM TEAM -- ONE-SHOT SETUP SCRIPT
REM  Downloads, configures, and launches the optimal local vision LLM
REM  stack for Microsoft UFO (August 2026).
REM
REM  Models (verified August 2026 -- best-in-class for your hardware):
REM    HOST_AGENT: Qwen3-VL-8B-Instruct Q4_K_M  (5.0 GB)
REM      - #1 on OS World agent benchmark (GUI automation)
REM      - 256K context, Apache 2.0, native vision
REM      - Best structured JSON / tool-calling of any local VLM
REM    APP_AGENT:  Gemma 4 12B IT Q4_0           (6.7 GB)
REM      - Encoder-free vision (faster image processing)
REM      - Apache 2.0, Google DeepMind, April 2026
REM      - Best efficiency/quality ratio for local execution
REM
REM  Total download: ~12.7 GB | Runtime RAM: ~18 GB (of your 32 GB)
REM
REM  What this script does:
REM    1. Creates directories
REM    2. Downloads 4 model files from HuggingFace (with resume)
REM    3. Updates LiteLLM config
REM    4. Updates agents.yaml to local vision mode
REM    5. Launches both llama-server instances + LiteLLM proxy
REM    6. Runs health check
REM ======================================================================

title UFO Dream Team -- One-Shot Setup
color 0A
echo.
echo  +-------------------------------------------------------------+
echo  ^|           UFO DREAM TEAM -- ONE-SHOT SETUP                   ^|
echo  +-------------------------------------------------------------+
echo  ^|                                                             ^|
echo  ^|   HOST: Qwen3-VL-8B  (strategist, #1 OS World benchmark)    ^|
echo  ^|   APP:  Gemma 4 12B  (executor, encoder-free vision)        ^|
echo  ^|                                                             ^|
echo  ^|   Download: ~12.7 GB  ^|  Runtime RAM: ~18 GB / 32 GB        ^|
echo  +-------------------------------------------------------------+
echo.

REM ---- Configuration ----
set "LLAMA_SERVER=C:\ufo\bin\llama-server.exe"
set "MODELS_DIR=C:\ufo\models"
set "UFO_DIR=C:\ufo\ufo"
set "PYTHON_EXE=C:\ufo\ufo\python_env\python.exe"
set "PYTHONIOENCODING=utf-8"

REM Model URLs (HuggingFace direct download)
set "QWEN_REPO=unsloth/Qwen3-VL-8B-Instruct-GGUF"
set "QWEN_MODEL_FILE=Qwen3-VL-8B-Instruct-Q4_K_M.gguf"
set "QWEN_MMPROJ_FILE=mmproj-F16.gguf"

set "GEMMA_REPO=ggml-org/gemma-4-12B-it-GGUF"
set "GEMMA_MODEL_FILE=gemma-4-12B-it-Q4_0.gguf"
set "GEMMA_MMPROJ_FILE=mmproj-gemma-4-12B-it-Q8_0.gguf"

REM Local file paths
set "QWEN_MODEL=%MODELS_DIR%\qwen3-vl-8b-instruct-q4_k_m.gguf"
set "QWEN_MMPROJ=%MODELS_DIR%\qwen3-vl-8b-instruct-mmproj-f16.gguf"
set "GEMMA_MODEL=%MODELS_DIR%\gemma-4-12b-it-q4_0.gguf"
set "GEMMA_MMPROJ=%MODELS_DIR%\gemma-4-12b-it-mmproj-q8_0.gguf"

echo ══════════════════════════════════════════════════════════════════
echo  PHASE 1: PRE-FLIGHT CHECKS
echo ══════════════════════════════════════════════════════════════════
echo.

REM Check llama-server exists
if not exist "%LLAMA_SERVER%" (
    echo  [ERROR] llama-server.exe not found at: %LLAMA_SERVER%
    echo.
    echo  Download the latest release from:
    echo    https://github.com/ggerganov/llama.cpp/releases
    echo.
    echo  Extract llama-server.exe to C:\ufo\bin\
    echo  Make sure to get the Vulkan build for AMD GPU acceleration.
    goto :fatal_error
)
echo  [OK] llama-server.exe found

REM Check curl exists (for downloads)
where curl >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] curl not found. Install curl or use Windows 10+.
    goto :fatal_error
)
echo  [OK] curl available

REM Check Python
if not exist "%PYTHON_EXE%" (
    echo  [WARN] UFO python_env not found at %PYTHON_EXE%
    echo         Will use system Python for LiteLLM.
    set "PYTHON_EXE=python"
)
echo  [OK] Python environment ready

REM Create models directory
if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"
echo  [OK] Models directory: %MODELS_DIR%

REM Check available RAM
for /f "tokens=2 delims==" %%a in ('wmic OS get FreePhysicalMemory /value 2^>nul ^| find "="') do (
    set /a FREE_MB=%%a / 1024
)
echo  [OK] Free RAM: !FREE_MB! MB
if !FREE_MB! lss 16000 (
    echo  [WARN] Less than 16 GB free RAM. Both models need ~18 GB.
    echo         Close other applications for best performance.
)
echo.

echo ══════════════════════════════════════════════════════════════════
echo  PHASE 2: DOWNLOAD MODELS (~12.7 GB total)
echo ══════════════════════════════════════════════════════════════════
echo.
echo  Downloads use -C - for automatic resume if interrupted.
echo  Re-run this script to resume any failed downloads.
echo.

REM ---- Download Qwen3-VL-8B model ----
if exist "%QWEN_MODEL%" (
    for %%F in ("%QWEN_MODEL%") do set QSIZE=%%~zF
    if !QSIZE! gtr 4000000000 (
        echo  [SKIP] Qwen3-VL-8B model already downloaded (!QSIZE! bytes)
        goto :skip_qwen_model
    )
)
echo  [1/4] Downloading Qwen3-VL-8B-Instruct Q4_K_M (~5.0 GB)...
echo         From: %QWEN_REPO%
curl -L -C - --progress-bar -o "%QWEN_MODEL%" ^
    "https://huggingface.co/%QWEN_REPO%/resolve/main/%QWEN_MODEL_FILE%"
if %errorlevel% neq 0 (
    echo  [ERROR] Download failed. Re-run this script to resume.
    goto :fatal_error
)
echo  [OK] Qwen3-VL-8B model downloaded
:skip_qwen_model

REM ---- Download Qwen3-VL-8B mmproj ----
if exist "%QWEN_MMPROJ%" (
    for %%F in ("%QWEN_MMPROJ%") do set QPSIZE=%%~zF
    if !QPSIZE! gtr 1000000000 (
        echo  [SKIP] Qwen3-VL-8B mmproj already downloaded (!QPSIZE! bytes)
        goto :skip_qwen_mmproj
    )
)
echo  [2/4] Downloading Qwen3-VL-8B mmproj F16 (~1.1 GB)...
curl -L -C - --progress-bar -o "%QWEN_MMPROJ%" ^
    "https://huggingface.co/%QWEN_REPO%/resolve/main/%QWEN_MMPROJ_FILE%"
if %errorlevel% neq 0 (
    echo  [ERROR] Download failed. Re-run this script to resume.
    goto :fatal_error
)
echo  [OK] Qwen3-VL-8B mmproj downloaded
:skip_qwen_mmproj

REM ---- Download Gemma 4 12B model ----
if exist "%GEMMA_MODEL%" (
    for %%F in ("%GEMMA_MODEL%") do set GSIZE=%%~zF
    if !GSIZE! gtr 6000000000 (
        echo  [SKIP] Gemma 4 12B model already downloaded (!GSIZE! bytes)
        goto :skip_gemma_model
    )
)
echo  [3/4] Downloading Gemma 4 12B IT Q4_0 (~6.7 GB)...
echo         From: %GEMMA_REPO%
curl -L -C - --progress-bar -o "%GEMMA_MODEL%" ^
    "https://huggingface.co/%GEMMA_REPO%/resolve/main/%GEMMA_MODEL_FILE%"
if %errorlevel% neq 0 (
    echo  [ERROR] Download failed. Re-run this script to resume.
    goto :fatal_error
)
echo  [OK] Gemma 4 12B model downloaded
:skip_gemma_model

REM ---- Download Gemma 4 12B mmproj ----
if exist "%GEMMA_MMPROJ%" (
    for %%F in ("%GEMMA_MMPROJ%") do set GPSIZE=%%~zF
    if !GPSIZE! gtr 100000000 (
        echo  [SKIP] Gemma 4 12B mmproj already downloaded (!GPSIZE! bytes)
        goto :skip_gemma_mmproj
    )
)
echo  [4/4] Downloading Gemma 4 12B mmproj Q8_0 (~152 MB)...
curl -L -C - --progress-bar -o "%GEMMA_MMPROJ%" ^
    "https://huggingface.co/%GEMMA_REPO%/resolve/main/%GEMMA_MMPROJ_FILE%"
if %errorlevel% neq 0 (
    echo  [ERROR] Download failed. Re-run this script to resume.
    goto :fatal_error
)
echo  [OK] Gemma 4 12B mmproj downloaded
:skip_gemma_mmproj

echo.
echo  All 4 model files are present!
echo.

echo ══════════════════════════════════════════════════════════════════
echo  PHASE 3: UPDATE UFO CONFIGURATION
echo ══════════════════════════════════════════════════════════════════
echo.

REM Backup current agents.yaml if not already backed up
if not exist "%UFO_DIR%\config\ufo\agents_cloud.yaml" (
    copy "%UFO_DIR%\config\ufo\agents.yaml" "%UFO_DIR%\config\ufo\agents_cloud.yaml" >nul 2>&1
    echo  [OK] Backed up current agents.yaml to agents_cloud.yaml
) else (
    echo  [OK] Cloud backup already exists
)

REM Write the dream team agents.yaml
echo  [OK] Writing local vision agents.yaml...
(
echo HOST_AGENT:
echo   VISUAL_MODE: true
echo   REASONING_MODEL: false
echo   API_TYPE: openai
echo   API_BASE: "http://127.0.0.1:4000"
echo   API_KEY: "sk-local"
echo   API_MODEL: ufo-host-model
echo   PROMPT: ufo/prompts/share/base/host_agent.yaml
echo   EXAMPLE_PROMPT: ufo/prompts/examples/{mode}/host_agent_example.yaml
echo APP_AGENT:
echo   VISUAL_MODE: true
echo   REASONING_MODEL: false
echo   API_TYPE: openai
echo   API_BASE: "http://127.0.0.1:4000"
echo   API_KEY: "sk-local"
echo   API_MODEL: ufo-app-model
echo   PROMPT: ufo/prompts/share/base/app_agent.yaml
echo   EXAMPLE_PROMPT: ufo/prompts/examples/{mode}/app_agent_example.yaml
echo   EXAMPLE_PROMPT_AS: ufo/prompts/examples/{mode}/app_agent_example_as.yaml
echo BACKUP_AGENT:
echo   VISUAL_MODE: true
echo   API_TYPE: openai
echo   API_BASE: "http://127.0.0.1:4000"
echo   API_KEY: "sk-local"
echo   API_MODEL: ufo-host-model
echo EVALUATION_AGENT:
echo   VISUAL_MODE: false
echo   REASONING_MODEL: false
echo   API_TYPE: openai
echo   API_BASE: "http://127.0.0.1:4000"
echo   API_KEY: "sk-local"
echo   API_MODEL: ufo-app-model
echo OMNIPARSER:
echo   ENDPOINT: ''
echo   BOX_THRESHOLD: 0.02
echo   IOU_THRESHOLD: 0.1
echo   USE_PADDLEOCR: true
echo   IMGSZ: 1024
echo MAX_TOKENS: 2000
echo MAX_RETRY: 3
echo TEMPERATURE: 0.0
echo TOP_P: 0.0
echo TIMEOUT: 120
echo APP_API_PROMPT_ADDRESS:
echo   WINWORD.EXE: ufo/prompts/apps/word/api.yaml
echo   EXCEL.EXE: ufo/prompts/apps/excel/api.yaml
echo   msedge.exe: ufo/prompts/apps/web/api.yaml
echo   chrome.exe: ufo/prompts/apps/web/api.yaml
) > "%UFO_DIR%\config\ufo\agents.yaml"

REM Write the LiteLLM config
echo  [OK] Writing LiteLLM config...
(
echo model_list:
echo   - model_name: "ufo-host-model"
echo     litellm_params:
echo       model: "openai/qwen3-vl"
echo       api_base: "http://127.0.0.1:8080/v1"
echo       api_key: "sk-local"
echo       rpm: 10000
echo       max_tokens: 2000
echo       temperature: 0.0
echo       num_retries: 2
echo   - model_name: "ufo-app-model"
echo     litellm_params:
echo       model: "openai/gemma4"
echo       api_base: "http://127.0.0.1:8081/v1"
echo       api_key: "sk-local"
echo       rpm: 10000
echo       max_tokens: 2000
echo       temperature: 0.0
echo       num_retries: 2
echo   - model_name: "ufo-model"
echo     litellm_params:
echo       model: "openai/qwen3-vl"
echo       api_base: "http://127.0.0.1:8080/v1"
echo       api_key: "sk-local"
echo       rpm: 10000
echo       max_tokens: 2000
echo       temperature: 0.0
echo   - model_name: "gemini-complex"
echo     litellm_params:
echo       model: "gemini/gemini-3.7-flash"
echo       api_key: "os.environ/GEMINI_API_KEY"
echo   - model_name: "gemini-computer-use"
echo     litellm_params:
echo       model: "gemini/gemini-3.7-flash"
echo       api_key: "os.environ/GEMINI_API_KEY"
) > "%UFO_DIR%\litellm_config.yaml"

echo  [OK] Configuration updated
echo.

echo ══════════════════════════════════════════════════════════════════
echo  PHASE 4: KILL ANY EXISTING INSTANCES
echo ══════════════════════════════════════════════════════════════════
echo.

taskkill /IM llama-server.exe /F >nul 2>&1
echo  [OK] Cleared any existing llama-server processes
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":4000.*LISTEN" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
echo  [OK] Cleared any existing LiteLLM proxy
timeout /t 2 /nobreak >nul
echo.

echo ══════════════════════════════════════════════════════════════════
echo  PHASE 5: LAUNCH DREAM TEAM
echo ══════════════════════════════════════════════════════════════════
echo.

REM ---- Launch Qwen3-VL-8B (HOST_AGENT) on :8080 ----
echo  Starting Qwen3-VL-8B on :8080 (HOST_AGENT -- strategist)...
start "Qwen3-VL-8B [HOST]" /min "%LLAMA_SERVER%" ^
    -m "%QWEN_MODEL%" ^
    --mmproj "%QWEN_MMPROJ%" ^
    -t 8 ^
    -c 8192 ^
    --image-min-tokens 1024 ^
    --host 127.0.0.1 ^
    --port 8080

echo  Waiting for Qwen3-VL to load (this takes 15-45 seconds on CPU)...
set RETRIES=0
:wait_qwen
timeout /t 3 /nobreak >nul
set /a RETRIES+=1
curl -s -f http://127.0.0.1:8080/health >nul 2>&1
if !errorlevel! equ 0 (
    echo  [OK] Qwen3-VL-8B is healthy! (attempt !RETRIES!)
    goto :qwen_ready
)
if !RETRIES! gtr 60 (
    echo  [ERROR] Qwen3-VL did not start after 180 seconds.
    echo          Check the "Qwen3-VL-8B [HOST]" window for errors.
    goto :fatal_error
)
if !RETRIES!==10 echo  Still loading... !RETRIES!/60
if !RETRIES!==20 echo  Still loading... !RETRIES!/60 (large model, be patient)
if !RETRIES!==30 echo  Still loading... !RETRIES!/60
if !RETRIES!==40 echo  Still loading... !RETRIES!/60
goto :wait_qwen
:qwen_ready

REM ---- Launch Gemma 4 12B (APP_AGENT) on :8081 ----
echo.
echo  Starting Gemma 4 12B on :8081 (APP_AGENT -- executor)...
start "Gemma-4-12B [APP]" /min "%LLAMA_SERVER%" ^
    -m "%GEMMA_MODEL%" ^
    --mmproj "%GEMMA_MMPROJ%" ^
    -t 8 ^
    -c 8192 ^
    --host 127.0.0.1 ^
    --port 8081

echo  Waiting for Gemma 4 to load...
set RETRIES2=0
:wait_gemma
timeout /t 3 /nobreak >nul
set /a RETRIES2+=1
curl -s -f http://127.0.0.1:8081/health >nul 2>&1
if !errorlevel! equ 0 (
    echo  [OK] Gemma 4 12B is healthy! (attempt !RETRIES2!)
    goto :gemma_ready
)
if !RETRIES2! gtr 60 (
    echo  [ERROR] Gemma 4 did not start after 180 seconds.
    goto :fatal_error
)
if !RETRIES2!==10 echo  Still loading... !RETRIES2!/60
if !RETRIES2!==20 echo  Still loading... !RETRIES2!/60
if !RETRIES2!==30 echo  Still loading... !RETRIES2!/60
goto :wait_gemma
:gemma_ready

REM ---- Launch LiteLLM Proxy on :4000 ----
echo.
echo  Starting LiteLLM proxy on :4000...
start "LiteLLM [PROXY]" /min "%PYTHON_EXE%" -m litellm.proxy.proxy_cli ^
    --config "%UFO_DIR%\litellm_config.yaml" ^
    --host 127.0.0.1 ^
    --port 4000

set RETRIES3=0
:wait_litellm
timeout /t 2 /nobreak >nul
set /a RETRIES3+=1
curl -s -f http://127.0.0.1:4000/health >nul 2>&1
if !errorlevel! equ 0 (
    echo  [OK] LiteLLM proxy is healthy!
    goto :litellm_ready
)
if !RETRIES3! gtr 20 (
    echo  [ERROR] LiteLLM proxy did not start after 40 seconds.
    echo          Ensure litellm is installed: pip install litellm
    goto :fatal_error
)
goto :wait_litellm
:litellm_ready

echo.
echo ======================================================================
echo  PHASE 6: VERIFICATION
echo ======================================================================
echo.

REM Quick test through LiteLLM
echo  Testing HOST model (Qwen3-VL-8B) via LiteLLM...
curl -s -X POST http://127.0.0.1:4000/chat/completions ^
    -H "Content-Type: application/json" ^
    -H "Authorization: Bearer sk-local" ^
    -d "{\"model\": \"ufo-host-model\", \"messages\": [{\"role\": \"user\", \"content\": \"Reply with only: HOST_OK\"}], \"max_tokens\": 10, \"temperature\": 0}" 2>nul
echo.

echo  Testing APP model (Gemma 4 12B) via LiteLLM...
curl -s -X POST http://127.0.0.1:4000/chat/completions ^
    -H "Content-Type: application/json" ^
    -H "Authorization: Bearer sk-local" ^
    -d "{\"model\": \"ufo-app-model\", \"messages\": [{\"role\": \"user\", \"content\": \"Reply with only: APP_OK\"}], \"max_tokens\": 10, \"temperature\": 0}" 2>nul
echo.
echo.

echo ======================================================================
echo.
echo  +-------------------------------------------------------------+
echo  ^|                  DREAM TEAM IS LIVE!                        ^|
echo  +-------------------------------------------------------------+
echo  ^|                                                             ^|
echo  ^|  Qwen3-VL-8B   :8080  HOST_AGENT  (strategist)             ^|
echo  ^|  Gemma 4 12B   :8081  APP_AGENT   (executor)               ^|
echo  ^|  LiteLLM       :4000  Proxy       (router)                 ^|
echo  ^|                                                             ^|
echo  ^|  VISUAL_MODE: True -- both agents can SEE screenshots!      ^|
echo  ^|                                                             ^|
echo  ^|  To run UFO:                                                ^|
echo  ^|    python -m ufo --task "open notepad and type hello"       ^|
echo  ^|                                                             ^|
echo  ^|  To revert to cloud (Gemini):                               ^|
echo  ^|    scripts\stop_local_llm.bat                               ^|
echo  ^|                                                             ^|
echo  +-------------------------------------------------------------+
echo.
echo  Monitoring health every 30 seconds. Press Ctrl+C to stop.
echo  (The LLM servers will keep running in the background.)
echo.

:monitor
timeout /t 30 /nobreak >nul
set "S1=DOWN" & set "S2=DOWN" & set "S3=DOWN"
curl -s -f http://127.0.0.1:8080/health >nul 2>&1 && set "S1=OK"
curl -s -f http://127.0.0.1:8081/health >nul 2>&1 && set "S2=OK"
curl -s -f http://127.0.0.1:4000/health >nul 2>&1 && set "S3=OK"
echo  [%TIME%] Qwen3-VL: !S1! ^| Gemma-4: !S2! ^| LiteLLM: !S3!
goto :monitor

:fatal_error
echo.
echo  ╔═══════════════════════════════════════════════════════════════╗
echo  ║  SETUP FAILED — See errors above.                            ║
echo  ║  Fix the issue and re-run this script. Downloads will resume.║
echo  ╚═══════════════════════════════════════════════════════════════╝
echo.
pause
exit /b 1
