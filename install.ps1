#Requires -Version 5.1
<#
.SYNOPSIS
  JARVIS (Ollama Edition) — Windows one-click installer via WSL2.

.DESCRIPTION
  Sets everything up so you can just double-click:
    1. Requests admin once (needed to enable WSL)
    2. Enables WSL2 and installs Ubuntu if you don't have a distro yet
    3. Turns on systemd inside WSL so JARVIS + Ollama keep running
    4. Runs the Linux one-click installer (install.sh) inside WSL
    5. Opens the dashboard at http://localhost:3142 in your browser

  Afterwards JARVIS lives in ~/.jarvis inside WSL; the dashboard is reachable
  from Windows at http://localhost:3142.

.PARAMETER Ref
  Git branch/tag to install (default: main, or $env:JARVIS_REF).
.PARAMETER Model / FastModel
  Ollama models to use (defaults: llama3.2 / llama3.2:1b).
.PARAMETER Port
  Dashboard port (default 3142).
.PARAMETER NoModels / NoOllama / NoStart
  Skip pulling models / skip Ollama / don't start the daemon.
.PARAMETER Service
  Also install a systemd user service inside WSL (auto-start on login).
.PARAMETER Local
  Install from the repo checkout this script sits in (for developers)
  instead of downloading from GitHub.
.PARAMETER Uninstall
  Remove JARVIS from WSL (keeps data; add -Purge to wipe).
.PARAMETER Purge
  With -Uninstall: delete everything including data.
.PARAMETER NoBrowser
  Don't auto-open the dashboard in the browser.

.EXAMPLE
  .\install.ps1
  .\install.ps1 -Model qwen2.5:7b -Port 4000
  .\install.ps1 -Uninstall -Purge
#>
[CmdletBinding()]
param(
  [string]$Ref = '',
  [string]$Model = '',
  [string]$FastModel = '',
  [int]$Port = 3142,
  [switch]$NoModels,
  [switch]$NoOllama,
  [switch]$NoStart,
  [switch]$Service,
  [switch]$Local,
  [switch]$Uninstall,
  [switch]$Purge,
  [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$RepoOwner = 'thijsgroenewegentg-cell'
$RepoName  = '1'

# ── output helpers ───────────────────────────────────────────────────────────
function Write-Step([string]$m) { Write-Host "[>] $m" -ForegroundColor Cyan }
function Write-Ok([string]$m)   { Write-Host "[v] $m" -ForegroundColor Green }
function Write-Warn2([string]$m){ Write-Host "[!] $m" -ForegroundColor Yellow }
function Write-Err([string]$m)  { Write-Host "[x] $m" -ForegroundColor Red }
function Exit-WithError([string]$m) {
  Write-Err $m
  Write-Host ''
  Write-Host 'Press Enter to close this window…'
  [void][Console]::ReadLine()
  exit 1
}

Write-Host ''
Write-Host '  J.A.R.V.I.S. — Ollama Edition — Windows installer (WSL2)' -ForegroundColor White
Write-Host '  Just A Rather Very Intelligent System, fully local.' -ForegroundColor DarkGray
Write-Host ''

# ── 0. running inside WSL already? then just use install.sh ─────────────────
if ($env:WSL_DISTRO_NAME) {
  Exit-WithError "You are already inside WSL ('$env:WSL_DISTRO_NAME'). Run the Linux installer directly:  bash install.sh"
}

# ── 1. self-elevate (one UAC prompt) ─────────────────────────────────────────
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Step 'Requesting administrator rights (one-time, needed to enable WSL)…'
  $passThru = @()
  if ($Ref)       { $passThru += @('-Ref', $Ref) }
  if ($Model)     { $passThru += @('-Model', $Model) }
  if ($FastModel) { $passThru += @('-FastModel', $FastModel) }
  if ($Port -ne 3142) { $passThru += @('-Port', "$Port") }
  foreach ($flag in @(
      @('NoModels', $NoModels), @('NoOllama', $NoOllama), @('NoStart', $NoStart),
      @('Service', $Service), @('Local', $Local), @('Uninstall', $Uninstall),
      @('Purge', $Purge), @('NoBrowser', $NoBrowser))) {
    if ($flag[1]) { $passThru += ('-' + $flag[0]) }
  }
  # note: pass the bare path — Start-Process quotes arguments with spaces itself
  $args2 = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath) + $passThru
  Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $args2
  exit
}

# ── 2. make sure WSL2 itself is installed ────────────────────────────────────
function Test-WslInstalled {
  $null = & wsl.exe --status 2>$null
  return ($LASTEXITCODE -eq 0)
}

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
  Exit-WithError 'wsl.exe not found. This version of Windows is too old for WSL2 (Windows 10 2004+ required).'
}

if (-not (Test-WslInstalled)) {
  Write-Step 'Enabling Windows Subsystem for Linux (first time only)…'
  & wsl.exe --install --no-distribution
  if ($LASTEXITCODE -eq 3010) {
    Write-Warn2 'A Windows restart is required to finish enabling WSL.'
    Write-Warn2 'Reboot now, then run this installer again — it will continue where it left off.'
    Exit-WithError 'Reboot required.'
  }
  if ($LASTEXITCODE -ne 0) {
    Write-Warn2 'wsl --install failed; trying the legacy feature install…'
    & dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart | Out-Null
    & dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart | Out-Null
    Exit-WithError 'Windows features enabled. RESTART your PC and run this installer again.'
  }
  Write-Step 'Updating the WSL engine…'
  & wsl.exe --update 2>$null | Out-Null
  if (-not (Test-WslInstalled)) {
    Exit-WithError 'WSL still not ready. Reboot and re-run; if it persists, enable virtualization (VT-x/AMD-V) in BIOS.'
  }
}
Write-Ok 'WSL2 is available'

# ── 3. make sure a distro exists (install Ubuntu if not) ─────────────────────
$distroList = (& wsl.exe -l -q 2>$null) |
  ForEach-Object { ($_ -replace "[`0\u200e\u200f\r]", '').Trim() } |
  Where-Object { $_ -ne '' }
if ($distroList -and $distroList.Count -gt 0) {
  $Distro = $distroList[0]
  Write-Ok "Using existing WSL distro: $Distro"
} else {
  Write-Step 'Installing Ubuntu — a window will open asking you to create a Linux username (one time)…'
  & wsl.exe --install -d Ubuntu
  if ($LASTEXITCODE -ne 0) {
    Write-Warn2 'Store download failed; retrying with --web-download…'
    & wsl.exe --install -d Ubuntu --web-download
    if ($LASTEXITCODE -ne 0) { Exit-WithError 'Could not install Ubuntu. Install a distro manually (wsl --install -d Ubuntu) and re-run.' }
  }
  $Distro = 'Ubuntu'
}

# wait for the distro to answer (OOBE must be finished)
Write-Step "Waiting for $Distro to be ready…"
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
  $null = & wsl.exe -d $Distro -u root -- /bin/sh -c 'echo ready' 2>$null
  if ($LASTEXITCODE -eq 0) { $ready = $true; break }
  Start-Sleep -Seconds 4
}
if (-not $ready) {
  Exit-WithError "The Ubuntu setup window needs to be completed first (create your Linux user), then re-run this installer."
}
Write-Ok "$Distro is ready"

# ── 4. enable systemd inside WSL so the daemon + Ollama keep running ─────────
$wslConf = (& wsl.exe -d $Distro -u root -- /bin/sh -c 'cat /etc/wsl.conf 2>/dev/null' 2>$null) -join "`n"
if ($wslConf -notmatch '(?m)^\s*systemd\s*=\s*true') {
  Write-Step 'Enabling systemd in WSL (keeps JARVIS + Ollama alive between sessions)…'
  & wsl.exe -d $Distro -u root -- /bin/sh -c "printf '\n[boot]\nsystemd=true\n' >> /etc/wsl.conf" | Out-Null
  & wsl.exe --terminate $Distro 2>$null | Out-Null
  Start-Sleep -Seconds 3
  Write-Ok 'systemd enabled'
} else {
  Write-Ok 'systemd already enabled in WSL'
}

# ── 5. uninstall path ────────────────────────────────────────────────────────
if (-not $Ref) {
  if ($env:JARVIS_REF) { $Ref = $env:JARVIS_REF } else { $Ref = 'main' }
}
$rawUrl = "https://raw.githubusercontent.com/$RepoOwner/$RepoName/$Ref/install.sh"

if ($Uninstall) {
  Write-Step 'Removing JARVIS from WSL…'
  $uFlags = '--uninstall -y'
  if ($Purge) { $uFlags += ' --purge' }
  & wsl.exe -d $Distro -- bash -lc "curl -fsSL $rawUrl | bash -s -- $uFlags"
  if ($LASTEXITCODE -ne 0) { Exit-WithError "Uninstall failed (exit $LASTEXITCODE)." }
  Write-Ok 'JARVIS removed.'
  Write-Host ''
  Write-Host 'Press Enter to close this window…'
  [void][Console]::ReadLine()
  exit 0
}

# ── 6. run the Linux one-click installer inside WSL ──────────────────────────
$flags = @('-y')
if ($NoModels) { $flags += '--no-models' }
if ($NoOllama) { $flags += '--no-ollama' }
if ($NoStart)  { $flags += '--no-start' }
if ($Service)  { $flags += '--service' }
if ($Model)     { $flags += @('--model', "'$Model'") }
if ($FastModel) { $flags += @('--fast-model', "'$FastModel'") }
if ($Port -ne 3142) { $flags += @('--port', "$Port") }
$flagStr = $flags -join ' '

function ConvertTo-WslPath([string]$p) {
  $drive = $p.Substring(0, 1).ToLower()
  $rest  = $p.Substring(2).Replace('\', '/')
  return "/mnt/$drive$rest"
}

if ($Local) {
  $repoDir = Split-Path -Parent $PSCommandPath
  if (-not (Test-Path (Join-Path $repoDir 'install.sh'))) {
    Exit-WithError "-Local expects install.sh next to install.ps1 (got: $repoDir)"
  }
  $wslRepo = ConvertTo-WslPath $repoDir
  Write-Step "Installing from this repo checkout: $repoDir"
  $innerCmd = "bash '$wslRepo/install.sh' $flagStr"
} else {
  Write-Step 'Downloading and running the JARVIS installer inside WSL…'
  Write-Step "(model pulls are several GB — one-time, go make a coffee)"
  $innerCmd = "if ! command -v curl >/dev/null 2>&1; then sudo apt-get update -y && sudo apt-get install -y curl ca-certificates; fi; curl -fsSL '$rawUrl' | bash -s -- $flagStr"
}

# JARVIS_REF tells install.sh which branch/tag to clone
& wsl.exe -d $Distro -- bash -lc "export JARVIS_REF='$Ref'; $innerCmd"
if ($LASTEXITCODE -ne 0) {
  Exit-WithError "The installer failed inside WSL (exit $LASTEXITCODE). You can re-run this script; logs: wsl -d $Distro -- bash -lc 'cat ~/.jarvis/data/daemon.log'"
}

# ── 7. verify from Windows + open the dashboard ──────────────────────────────
$healthy = $false
for ($i = 0; $i -lt 10; $i++) {
  $null = & wsl.exe -d $Distro -- bash -lc "curl -sf --max-time 2 http://localhost:$Port/api/health" 2>$null
  if ($LASTEXITCODE -eq 0) { $healthy = $true; break }
  Start-Sleep -Seconds 2
}

Write-Host ''
if ($healthy) {
  Write-Ok "JARVIS is running — dashboard: http://localhost:$Port"
  # desktop shortcut for one-click access next time
  try {
    $desktop = [Environment]::GetFolderPath('Desktop')
    Set-Content -Path (Join-Path $desktop 'JARVIS Dashboard.url') -Value "[InternetShortcut]`r`nURL=http://localhost:$Port"
    Write-Ok "Desktop shortcut created: 'JARVIS Dashboard'"
  } catch { Write-Warn2 'Could not create the desktop shortcut.' }
  if (-not $NoBrowser) { Start-Process "http://localhost:$Port" }
} else {
  Write-Warn2 "The daemon did not answer on port $Port yet. Check inside WSL:"
  Write-Warn2 "  wsl -d $Distro -- bash -lc '~/.local/bin/jarvis logs'"
}

Write-Host ''
Write-Host '  Everyday commands (run in PowerShell):' -ForegroundColor White
Write-Host "    wsl -d $Distro -- bash -lc 'jarvis status'      # status"
Write-Host "    wsl -d $Distro -- bash -lc 'jarvis stop'        # stop"
Write-Host "    wsl -d $Distro -- bash -lc 'jarvis start -d'    # start"
Write-Host "    wsl -d $Distro                                  # open Linux shell"
Write-Host "    wsl --shutdown                                  # shuts JARVIS down too"
Write-Host ''
Write-Host 'Press Enter to close this window…'
[void][Console]::ReadLine()
