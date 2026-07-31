@echo off
REM Build JARVIS Single .EXE - Everything in One - 100% FREE - Voice MUST BE PIPER + YOUR ElevenLabs CwhRBWXzGAHq8TQ4Fs17 optional
REM Double-click to build, output in dist\JARVIS.exe - single file that starts whole JARVIS AI
REM Fixed to use script directory, not current dir - and fixed nested if bug that caused "was unexpected at this time"

setlocal
cd /d "%~dp0"
echo Current dir: %cd%
echo =========================================
echo   J.A.R.V.I.S Build Single .EXE
echo   Everything in One - 100%% FREE
echo   Voice MUST BE PIPER + Your ElevenLabs CwhRBWXzGAHq8TQ4Fs17
echo   RX 9070 XT 16GB Optimized
echo =========================================

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

if not exist "%~dp0JARVIS.py" (
    if not exist JARVIS.py (
        echo JARVIS.py not found. Run this from jarvis folder
        echo Looking in: %~dp0
        dir /B
        pause
        exit /b 1
    )
)

echo [1/5] Installing PyInstaller and dependencies (100%% FREE)...

if exist "%~dp0venv\Scripts\activate.bat" call "%~dp0venv\Scripts\activate.bat"
if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat

pip install pyinstaller --break-system-packages >nul 2>&1
if %errorlevel% neq 0 pip install pyinstaller
pip install -r requirements.txt --break-system-packages >nul 2>&1
if %errorlevel% neq 0 pip install -r requirements.txt

echo [2/5] Checking Piper voice model (MUST BE PIPER - free offline)...
set PIPER_FOUND=0
if exist "%~dp0data\piper_models\en_GB-alan-medium.onnx" set PIPER_FOUND=1
if exist data\piper_models\en_GB-alan-medium.onnx set PIPER_FOUND=1

if %PIPER_FOUND%==0 (
    echo Downloading Piper British voice en_GB-alan-medium (30MB free)...
    pip install piper-tts --break-system-packages >nul 2>&1
    if %errorlevel% neq 0 pip install piper-tts
    python -m piper.download_voices en_GB-alan-medium --data-dir data\piper_models
)

REM Check again after download attempt, manual download if still missing
set PIPER_FOUND2=0
if exist "%~dp0data\piper_models\en_GB-alan-medium.onnx" set PIPER_FOUND2=1
if exist data\piper_models\en_GB-alan-medium.onnx set PIPER_FOUND2=1

if %PIPER_FOUND2%==0 (
    echo Trying manual download via PowerShell...
    powershell -Command "New-Item -ItemType Directory -Force -Path data\piper_models | Out-Null; try { Invoke-WebRequest -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx' -OutFile 'data\piper_models\en_GB-alan-medium.onnx' } catch {}; try { Invoke-WebRequest -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json' -OutFile 'data\piper_models\en_GB-alan-medium.onnx.json' } catch {}"
)

if exist data\piper_models\en_GB-alan-medium.onnx (
    echo Piper model exists: data\piper_models\en_GB-alan-medium.onnx - FREE offline British premium
) else (
    echo Piper model still missing, will use Edge fallback (still free), Sir.
)

echo [3/5] Cleaning previous build...
if exist "%~dp0build" rmdir /S /Q "%~dp0build"
if exist "%~dp0dist" rmdir /S /Q "%~dp0dist"
if exist build rmdir /S /Q build
if exist dist rmdir /S /Q dist
if exist __pycache__ rmdir /S /Q __pycache__

echo [4/5] Building JARVIS.exe single file (this takes 5-10 minutes, please wait)...
echo Using JARVIS.spec - bundles everything

set SPEC_FILE=JARVIS.spec
if exist "%~dp0JARVIS.spec" set SPEC_FILE=%~dp0JARVIS.spec

pyinstaller "%SPEC_FILE%" --noconfirm --clean

if %errorlevel% neq 0 (
    echo Build failed with spec, trying simple onefile build...
    pyinstaller --onefile --name JARVIS --console --hidden-import=jarvis.brain --hidden-import=jarvis.voice.premium --hidden-import=uvicorn --hidden-import=fastapi JARVIS.py
)

echo [5/5] Build done!

if exist "%~dp0dist\JARVIS.exe" (
    echo.
    echo =========================================
    echo   SUCCESS, Sir! Single .EXE Built
    echo =========================================
    echo   File: dist\JARVIS.exe
    dir "%~dp0dist\JARVIS.exe"
    echo.
    echo   Double-click dist\JARVIS.exe to start whole JARVIS AI
    echo   - Web: http://localhost:8000 and /holo
    echo   - Brain: qwen2.5:14b for 9070 XT if Ollama running
    echo   - Voice: MUST BE PIPER free offline British + YOUR ElevenLabs CwhRBWXzGAHq8TQ4Fs17 if .env has key
    echo   - Features: chat, codebase RAG, agent, team, proactive, memory, evolution, self-edits, voice lab
    echo   - Tray: close = minimize to tray
    echo   - 100%% FREE, No API Keys (except optional ElevenLabs for your voice)
    echo.
    echo   To run: double-click dist\JARVIS.exe
    echo.
) else (
    if exist dist\JARVIS.exe (
        echo.
        echo =========================================
        echo   SUCCESS, Sir! Single .EXE Built
        echo =========================================
        dir dist\JARVIS.exe
        echo.
        echo   Double-click dist\JARVIS.exe to start
        echo.
    ) else (
        echo Build failed, dist\JARVIS.exe not found. Check errors above, Sir.
    )
)

pause
endlocal
