@echo off
REM /install.bat
REM ===========================================================================
REM  JARVIS - one-click installer for Windows.
REM
REM  Just double-click this file. It finds Python, then hands over to
REM  install.py, which does everything else: virtual environment, packages,
REM  Ollama, the model, folders, config, a desktop shortcut and a self-test.
REM
REM  Command line use (optional):
REM     install.bat --minimal        text-only install
REM     install.bat --yes            no questions asked
REM ===========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo   Installing JARVIS - free, local, no API keys.
echo.

REM --- Find a usable Python 3 -------------------------------------------------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    where python3 >nul 2>&1 && set "PY=python3"
)

if not defined PY (
    echo   [X] Python was not found on this computer.
    echo.
    echo   1. Download Python 3.11 or newer from https://www.python.org/downloads/
    echo   2. IMPORTANT: tick "Add python.exe to PATH" in the installer.
    echo   3. Then double-click install.bat again.
    echo.
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)

REM --- Hand over to the real installer ---------------------------------------
%PY% install.py %*
set "STATUS=%ERRORLEVEL%"

if not "%STATUS%"=="0" (
    echo.
    echo   The installer stopped with errors. Scroll up to see what happened,
    echo   or try:   install.bat --minimal
    echo.
)

pause
endlocal
exit /b %STATUS%
