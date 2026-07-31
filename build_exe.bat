@echo off
REM Build JARVIS Single .EXE - Everything in One - 100% FREE - Voice MUST BE PIPER + YOUR ElevenLabs CwhRBWXzGAHq8TQ4Fs17 optional
REM Double-click to build, output in dist\JARVIS.exe - single file that starts whole JARVIS AI

echo =========================================
echo   J.A.R.V.I.S Build Single .EXE
echo   Everything in One - 100%% FREE
echo   Voice MUST BE PIPER + Your ElevenLabs CwhRBWXzGAHq8TQ4Fs17
echo   RX 9070 XT 16GB Optimized
echo =========================================

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

REM Check if in jarvis folder
if not exist JARVIS.py (
    echo JARVIS.py not found. Run this from jarvis folder (where JARVIS.py is)
    echo Current dir: %cd%
    pause
    exit /b 1
)

echo [1/5] Installing PyInstaller and dependencies (100%% FREE)...

REM Activate venv if exists
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

pip install pyinstaller --break-system-packages 2>nul || pip install pyinstaller
pip install -r requirements.txt --break-system-packages 2>nul || pip install -r requirements.txt

echo [2/5] Checking Piper voice model (MUST BE PIPER - free offline)...
if not exist data\piper_models\en_GB-alan-medium.onnx (
    echo Downloading Piper British voice en_GB-alan-medium (30MB free)...
    pip install piper-tts --break-system-packages 2>nul || pip install piper-tts
    python -m piper.download_voices en_GB-alan-medium --data-dir data\piper_models
    if %errorlevel% neq 0 (
        echo Trying manual download...
        powershell -Command "New-Item -ItemType Directory -Force -Path data\piper_models | Out-Null; Invoke-WebRequest -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx' -OutFile 'data\piper_models\en_GB-alan-medium.onnx'; Invoke-WebRequest -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json' -OutFile 'data\piper_models\en_GB-alan-medium.onnx.json'"
    )
) else (
    echo Piper model exists: data\piper_models\en_GB-alan-medium.onnx
)

echo [3/5] Cleaning previous build...
if exist build rmdir /S /Q build
if exist dist rmdir /S /Q dist
if exist __pycache__ rmdir /S /Q __pycache__

echo [4/5] Building JARVIS.exe single file (this takes 5-10 minutes, please wait)...
echo Using JARVIS.spec - bundles everything: brain, voice piper + your ElevenLabs CwhRBWXzGAHq8TQ4Fs17 support, web UI movable holographic, agent, team, proactive, knowledge, browser, goals, etc.

pyinstaller JARVIS.spec --noconfirm --clean

if %errorlevel% neq 0 (
    echo Build failed with spec, trying simple onefile build...
    pyinstaller --onefile --name JARVIS --console --icon=desktop\icon.png --add-data "web;web" --add-data "orb;orb" --add-data "data\piper_models;data\piper_models" --add-data ".env.example;." --hidden-import=jarvis.brain --hidden-import=jarvis.voice.premium --hidden-import=uvicorn --hidden-import=fastapi JARVIS.py
)

echo [5/5] Build done!

if exist dist\JARVIS.exe (
    echo.
    echo =========================================
    echo   SUCCESS, Sir! Single .EXE Built
    echo =========================================
    echo   File: dist\JARVIS.exe
    echo   Size: 
    dir dist\JARVIS.exe
    echo.
    echo   Double-click dist\JARVIS.exe to start whole JARVIS AI and functions:
    echo   - Web server at http://localhost:8000 and /holo movable UI
    echo   - Brain qwen2.5:14b for 9070 XT (if Ollama running)
    echo   - Voice MUST BE PIPER free offline British premium Manina style
    echo   - YOUR ElevenLabs voice CwhRBWXzGAHq8TQ4Fs17 if .env has ELEVENLABS_API_KEY
    echo   - Proactive morning briefing, git watcher, team, agent, second brain, etc
    echo   - Tray icon - close = minimize to tray, stays alive
    echo   - 100%% FREE, No API Keys (except optional ElevenLabs for your premium voice)
    echo.
    echo   To run: double-click dist\JARVIS.exe
    echo   First run may take 30 seconds to start, then browser opens automatically.
    echo.
) else (
    echo Build failed, dist\JARVIS.exe not found. Check errors above, Sir.
)

pause
