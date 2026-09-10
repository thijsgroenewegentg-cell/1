@echo off
set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo MARK is not installed yet. Run installer\install.ps1 first.
  pause
  exit /b 1
)
"%PY%" "%ROOT%\main.py" %*
