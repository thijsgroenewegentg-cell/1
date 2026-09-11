@echo off
rem JARVIS (Ollama Edition) - Windows one-click installer.
rem Double-click this file: it runs install.ps1 with an unrestricted policy
rem for this file only, and keeps the window open so you can read the output.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
