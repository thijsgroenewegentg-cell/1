# ═══════════════════════════════════════════════════════════════
#  ULTRON — one-press installer (Windows)
#  Double-click install.bat (recommended) or run in PowerShell:
#    powershell -ExecutionPolicy Bypass -File install.ps1
#  Flags: -Minimal | -Standard | -Full, -Dev
# ═══════════════════════════════════════════════════════════════
param(
  [switch]$Minimal,
  [switch]$Full,
  [switch]$Dev
)

$ErrorActionPreference = "Continue"

if ($Minimal) { $Models = @("qwen3:4b", "nomic-embed-text") }
elseif ($Full) { $Models = @("nomic-embed-text", "qwen3:4b", "gemma3:12b", "qwen3:14b", "mistral-small3.2", "qwen3-coder:30b", "qwen3:30b-a3b") }
else { $Models = @("nomic-embed-text", "qwen3:4b", "mistral-small3.2", "gemma3:12b") }

function Say($t)  { Write-Host ""; Write-Host "> $t" -ForegroundColor Red }
function Ok($t)   { Write-Host "  [OK] $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [!]  $t" -ForegroundColor Yellow }
function Fail($t) { Write-Host "  [X]  $t" -ForegroundColor Red }

Write-Host "  ULTRON - one-press installer - there are no strings on me" -ForegroundColor Red

# ── 1. Node.js ──────────────────────────────────────────────
Say "checking Node.js"
$nodeOk = $false
try { $v = (node --version); if ($v -match "v(\d+)\." -and [int]$Matches[1] -ge 18) { $nodeOk = $true } } catch {}
if ($nodeOk) { Ok "node $v" }
else {
  Warn "Node.js 18+ not found - installing via winget"
  try {
    winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
    # refresh PATH for this session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    $nodeOk = $true
    Ok "node installed"
  } catch { Fail "winget failed - install Node 18+ from https://nodejs.org and re-run"; exit 1 }
}

# ── 2. Ollama ───────────────────────────────────────────────
Say "checking Ollama"
$ollamaOk = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaOk) { Ok "ollama found" }
else {
  Warn "Ollama not found - installing via winget (big download, ~1 GB)"
  try {
    winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
  } catch { Fail "winget failed - install Ollama from https://ollama.com/download and re-run"; exit 1 }
}

# ── 3. Wake the Ollama server ───────────────────────────────
Say "waking the Ollama server"
$up = $false
try { Invoke-RestMethod -Uri "http://localhost:11434/api/version" -TimeoutSec 2 | Out-Null; $up = $true } catch {}
if (-not $up) {
  if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 0; $i -lt 15; $i++) {
      Start-Sleep -Seconds 1
      try { Invoke-RestMethod -Uri "http://localhost:11434/api/version" -TimeoutSec 2 | Out-Null; $up = $true; break } catch {}
    }
  }
}
if ($up) { Ok "ollama listening on :11434" }
else { Warn "could not reach Ollama - open the Ollama app once, then re-run (or run: ollama serve)" }

# ── 4. Dependencies ─────────────────────────────────────────
Say "installing dependencies"
npm install --no-fund --no-audit
Ok "dependencies ready"

# ── 5. The brains ───────────────────────────────────────────
Say "downloading models"
foreach ($m in $Models) {
  Write-Host "  $m" -ForegroundColor White
  ollama pull $m
}
Ok "models ready"

# ── 6. Sanity: the test suite ───────────────────────────────
Say "running his test suite (100 checks)"
npm test
if ($LASTEXITCODE -eq 0) { Ok "all tests passed" } else { Warn "some tests failed - he will still run; see output above" }

# ── 7. Wake him ─────────────────────────────────────────────
Say "waking ULTRON"
Start-Process "http://localhost:3000"
$runCmd = if ($Dev) { "run dev" } else { "start" }
Write-Host "  -> http://localhost:3000  (Ctrl+C stops him; re-run with: npm start)"
npm $runCmd
