@echo off
REM J.A.R.V.I.S Setup for Windows - 100% FREE, No API Keys, Voice MUST BE PIPER
REM For RX 9070 XT 16GB, PowerShell/CMD

echo =========================================
echo   J.A.R.V.I.S 4.0 - Windows Setup
echo   100%% FREE - Piper Voice MUST BE
echo   At your service, Sir.
echo =========================================

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Install Python 3.10+ from https://python.org
    echo Make sure to check "Add to PATH"
    pause
    exit /b 1
)

echo [1/7] Python found

REM Check Ollama
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo Ollama not found. Please install from https://ollama.com
    echo After install, run: ollama serve in another terminal
    echo Then re-run this setup
    pause
    exit /b 1
)
echo [2/7] Ollama found

REM Check if Ollama running
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    echo Starting Ollama serve in background...
    start /B ollama serve >nul 2>&1
    timeout /t 3 /nobreak >nul
) else (
    echo [3/7] Ollama running
)

REM Create venv
if not exist venv (
    echo [4/7] Creating virtual environment...
    python -m venv venv
) else (
    echo [4/7] Venv exists
)

echo [5/7] Installing Python dependencies - 100%% FREE...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

REM Create dirs
if not exist data mkdir data
if not exist workspace mkdir workspace
if not exist workspace\calendar mkdir workspace\calendar
if not exist workspace\music mkdir workspace\music
if not exist workspace\docs mkdir workspace\docs
if not exist data\calendar mkdir data\calendar
if not exist data\piper_models mkdir data\piper_models
if not exist data\voices mkdir data\voices

REM Create empty memory files if not exist
if not exist data\long_term_memory.json echo [] > data\long_term_memory.json
if not exist data\conversations.json echo [] > data\conversations.json
if not exist data\vectors.json echo [] > data\vectors.json
if not exist data\user_profile.json echo {} > data\user_profile.json

REM Copy .env
if not exist .env (
    copy .env.example .env
    echo Created .env from example - Voice MUST BE PIPER already set
)

echo [6/7] Installing Piper voice (MUST BE PIPER - 100%% FREE OFFLINE)...
pip install piper-tts

echo Downloading Piper British voice en_GB-alan-medium (30MB, free)...
python -m piper.download_voices en_GB-alan-medium --data-dir data\piper_models
if %errorlevel% neq 0 (
    echo Trying manual download...
    powershell -Command "Invoke-WebRequest -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx' -OutFile 'data\piper_models\en_GB-alan-medium.onnx'"
    powershell -Command "Invoke-WebRequest -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json' -OutFile 'data\piper_models\en_GB-alan-medium.onnx.json'"
)

echo [7/7] Pulling Ollama models - 100%% FREE...
echo For RX 9070 XT 16GB, recommended: qwen2.5:14b (smarter than 7b, fits 16GB)

ollama pull qwen2.5:7b
if %errorlevel% neq 0 (
    echo Failed to pull qwen2.5:7b, trying llama3.1:8b
    ollama pull llama3.1:8b
)

ollama pull nomic-embed-text

echo Creating JARVIS model...
if exist Modelfile.9070xt (
    echo Found Modelfile.9070xt for RX 9070 XT 16GB - using 14B model for smarter JARVIS
    ollama pull qwen2.5:14b
    ollama create jarvis -f Modelfile.9070xt --force
) else (
    ollama create jarvis -f Modelfile --force
)

echo.
echo =========================================
echo   Setup Complete, Sir. 100%% FREE
echo =========================================
echo.
echo Voice MUST BE PIPER is installed and ready - British premium, offline, free
echo Test voice:
echo   venv\Scripts\activate
echo   python -m jarvis.voice.premium --engine piper --preset manina_premium --text "Good evening Sir, Piper free offline"
echo.
echo Run JARVIS:
echo   venv\Scripts\activate
echo   python JARVIS.py              - Singular App - everything in one, opens /holo movable UI
echo   python web\server.py          - Web UI at http://localhost:8000 and /holo
echo   python cli.py                 - CLI chat
echo   python cli.py --always-on     - Always-on wake word 24/7 say Jarvis anytime
echo.
echo For RX 9070 XT 16GB for even smarter:
echo   ollama pull qwen2.5:14b
echo   ollama create jarvis -f Modelfile.9070xt --force
echo   python JARVIS.py
echo.
echo Troubleshooting: See INSTALL.md
echo.
pause
