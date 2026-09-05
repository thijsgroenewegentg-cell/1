@echo off
REM /scripts/jarvis.bat
REM Convenience launcher for Windows: activates the virtualenv, checks Ollama,
REM then starts JARVIS with whatever arguments you pass.
REM
REM   scripts\jarvis.bat              - voice if available, else text
REM   scripts\jarvis.bat --cli        - text interface
REM   scripts\jarvis.bat --web        - phone/LAN interface
REM   scripts\jarvis.bat --say "what's the weather"

setlocal
set "PROJECT_DIR=%~dp0.."
pushd "%PROJECT_DIR%"

set "PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo No virtual environment found. Creating one...
    python -m venv .venv
    "%PROJECT_DIR%\.venv\Scripts\python.exe" -m pip install --upgrade pip
    "%PROJECT_DIR%\.venv\Scripts\pip.exe" install -r requirements.txt
)

REM Make sure the Ollama server is answering before we start.
curl -s -f http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    where ollama >nul 2>&1
    if errorlevel 1 (
        echo Ollama is not installed - JARVIS will run in degraded ^(no-LLM^) mode.
        echo Download it free from https://ollama.com/download
    ) else (
        echo Starting Ollama...
        start "" /b ollama serve
        timeout /t 5 /nobreak >nul
    )
)

"%PYTHON%" main.py %*
popd
endlocal
