# /scripts/install_service_windows.ps1
# Register JARVIS as a Windows scheduled task that starts at logon.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_service_windows.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_service_windows.ps1 -Remove
#
# By default it launches the web interface (no console window). Pass
# -Arguments "--voice" for the always-listening microphone mode.

[CmdletBinding()]
param(
    [switch]$Remove,
    [string]$TaskName = "JARVIS",
    [string]$Arguments = "--web"
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PythonW    = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"
$Python     = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$MainScript = Join-Path $ProjectDir "main.py"
$LogDir     = Join-Path $ProjectDir "logs"

function Write-Info    ($m) { Write-Host $m -ForegroundColor Cyan }
function Write-Ok      ($m) { Write-Host $m -ForegroundColor Green }
function Write-Problem ($m) { Write-Host $m -ForegroundColor Red }

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Ok "Scheduled task '$TaskName' removed."
    } else {
        Write-Info "No scheduled task named '$TaskName'."
    }
    exit 0
}

if (-not (Test-Path $Python)) {
    Write-Problem "No virtual environment at $Python."
    Write-Problem "Run setup first:  python -m venv .venv; .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

# pythonw.exe runs without a console window; fall back to python.exe if absent.
$Exe = if (Test-Path $PythonW) { $PythonW } else { $Python }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$action = New-ScheduledTaskAction -Execute $Exe `
    -Argument "`"$MainScript`" $Arguments" -WorkingDirectory $ProjectDir

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "JARVIS — local AI assistant (100% free, runs on your machine)" | Out-Null

Write-Ok   "Scheduled task '$TaskName' registered — JARVIS starts at logon."
Write-Info "Start now : Start-ScheduledTask -TaskName $TaskName"
Write-Info "Stop      : Stop-ScheduledTask  -TaskName $TaskName"
Write-Info "Remove    : powershell -ExecutionPolicy Bypass -File scripts\install_service_windows.ps1 -Remove"
Write-Info "Ollama must also be running — it installs its own startup entry."
