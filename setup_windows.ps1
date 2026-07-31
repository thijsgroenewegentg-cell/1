# J.A.R.V.I.S Setup for Windows PowerShell - 100% FREE, No API Keys, Piper MUST BE
# For RX 9070 XT 16GB

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  J.A.R.V.I.S 4.0 - Windows PowerShell Setup" -ForegroundColor Cyan
Write-Host "  100% FREE - Piper Voice MUST BE" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# Check Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[1/7] Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "Python not found. Install Python 3.10+ from https://python.org and check Add to PATH" -ForegroundColor Red
    exit 1
}

# Check Ollama
try {
    $ollamaVersion = ollama --version 2>&1
    Write-Host "[2/7] Ollama found: $ollamaVersion" -ForegroundColor Green
} catch {
    Write-Host "Ollama not found. Install from https://ollama.com" -ForegroundColor Yellow
    Write-Host "After install, run: ollama serve in another terminal, then re-run this script" -ForegroundColor Yellow
    exit 1
}

# Check if Ollama running
try {
    Invoke-RestMethod -Uri http://localhost:11434/api/tags -TimeoutSec 2 -ErrorAction Stop | Out-Null
    Write-Host "[3/7] Ollama running at http://localhost:11434" -ForegroundColor Green
} catch {
    Write-Host "[3/7] Starting Ollama serve in background..." -ForegroundColor Yellow
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

# Create venv
if (-not (Test-Path "venv")) {
    Write-Host "[4/7] Creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv
} else {
    Write-Host "[4/7] Venv exists" -ForegroundColor Green
}

Write-Host "[5/7] Installing Python dependencies - 100% FREE..." -ForegroundColor Yellow
& ".\venv\Scripts\Activate.ps1"
python -m pip install --upgrade pip
pip install -r requirements.txt

# Create dirs
$dirs = @("data", "workspace", "workspace\calendar", "workspace\music", "workspace\docs", "data\calendar", "data\piper_models", "data\voices", "data\backups")
foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
}

# Create empty memory files
if (-not (Test-Path "data\long_term_memory.json")) { "[]" | Out-File -FilePath "data\long_term_memory.json" -Encoding utf8 }
if (-not (Test-Path "data\conversations.json")) { "[]" | Out-File -FilePath "data\conversations.json" -Encoding utf8 }
if (-not (Test-Path "data\vectors.json")) { "[]" | Out-File -FilePath "data\vectors.json" -Encoding utf8 }
if (-not (Test-Path "data\user_profile.json")) { "{}" | Out-File -FilePath "data\user_profile.json" -Encoding utf8 }

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from example - Voice MUST BE PIPER already set (free offline)" -ForegroundColor Green
}

Write-Host "[6/7] Installing Piper voice (MUST BE PIPER - 100% FREE OFFLINE)..." -ForegroundColor Yellow
pip install piper-tts

Write-Host "Downloading Piper British voice en_GB-alan-medium (30MB, free)..." -ForegroundColor Yellow
try {
    python -m piper.download_voices en_GB-alan-medium --data-dir data\piper_models
} catch {
    Write-Host "Trying manual download via Invoke-WebRequest..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx" -OutFile "data\piper_models\en_GB-alan-medium.onnx"
    Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json" -OutFile "data\piper_models\en_GB-alan-medium.onnx.json"
}

Write-Host "[7/7] Pulling Ollama models - 100% FREE..." -ForegroundColor Yellow
Write-Host "For RX 9070 XT 16GB, recommended: qwen2.5:14b (smarter than 7b, fits 16GB)" -ForegroundColor Cyan

ollama pull qwen2.5:7b
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to pull qwen2.5:7b, trying llama3.1:8b" -ForegroundColor Yellow
    ollama pull llama3.1:8b
}

ollama pull nomic-embed-text

Write-Host "Creating JARVIS model..." -ForegroundColor Yellow
if (Test-Path "Modelfile.9070xt") {
    Write-Host "Found Modelfile.9070xt for RX 9070 XT 16GB - using 14B model for smarter JARVIS" -ForegroundColor Cyan
    ollama pull qwen2.5:14b
    ollama create jarvis -f Modelfile.9070xt --force
} else {
    ollama create jarvis -f Modelfile --force
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  Setup Complete, Sir. 100% FREE" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Voice MUST BE PIPER is installed and ready - British premium, offline, free" -ForegroundColor Green
Write-Host "Test voice:" -ForegroundColor Cyan
Write-Host "  .\venv\Scripts\Activate.ps1"
Write-Host "  python -m jarvis.voice.premium --engine piper --preset manina_premium --text 'Good evening Sir, Piper free offline'"
Write-Host ""
Write-Host "Run JARVIS:" -ForegroundColor Cyan
Write-Host "  .\venv\Scripts\Activate.ps1"
Write-Host "  python JARVIS.py              # Singular App - everything in one, opens /holo movable UI"
Write-Host "  python web\server.py          # Web UI at http://localhost:8000 and /holo"
Write-Host "  python cli.py                 # CLI chat"
Write-Host "  python cli.py --always-on     # Always-on wake word 24/7 say Jarvis anytime"
Write-Host ""
Write-Host "For RX 9070 XT 16GB for even smarter:" -ForegroundColor Cyan
Write-Host "  ollama pull qwen2.5:14b"
Write-Host "  ollama create jarvis -f Modelfile.9070xt --force"
Write-Host "  python JARVIS.py"
Write-Host ""
Write-Host "Troubleshooting: See INSTALL.md" -ForegroundColor Yellow
