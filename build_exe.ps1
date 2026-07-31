# Build JARVIS Single .EXE - PowerShell - Everything in One - 100% FREE
# Voice MUST BE PIPER + Your ElevenLabs CwhRBWXzGAHq8TQ4Fs17 optional premium

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  J.A.R.V.I.S Build Single .EXE" -ForegroundColor Cyan
Write-Host "  Everything in One - 100% FREE" -ForegroundColor Cyan
Write-Host "  Voice MUST BE PIPER + Your ElevenLabs CwhRBWXzGAHq8TQ4Fs17" -ForegroundColor Cyan
Write-Host "  RX 9070 XT 16GB Optimized" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

if (-not (Test-Path "JARVIS.py")) {
    Write-Host "JARVIS.py not found. Run from jarvis folder" -ForegroundColor Red
    exit 1
}

Write-Host "[1/5] Installing PyInstaller and deps (100% FREE)..." -ForegroundColor Yellow

if (Test-Path "venv\Scripts\Activate.ps1") {
    & ".\venv\Scripts\Activate.ps1"
}

pip install pyinstaller --break-system-packages 2>$null || pip install pyinstaller
pip install -r requirements.txt --break-system-packages 2>$null

Write-Host "[2/5] Checking Piper voice (MUST BE PIPER)..." -ForegroundColor Yellow
if (-not (Test-Path "data\piper_models\en_GB-alan-medium.onnx")) {
    Write-Host "Downloading Piper British voice en_GB-alan-medium (30MB free)..." -ForegroundColor Yellow
    pip install piper-tts --break-system-packages 2>$null || pip install piper-tts
    try {
        python -m piper.download_voices en_GB-alan-medium --data-dir data\piper_models
    } catch {
        Write-Host "Manual download..." -ForegroundColor Yellow
        New-Item -ItemType Directory -Force -Path "data\piper_models" | Out-Null
        Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx" -OutFile "data\piper_models\en_GB-alan-medium.onnx"
        Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json" -OutFile "data\piper_models\en_GB-alan-medium.onnx.json"
    }
} else {
    Write-Host "Piper model exists" -ForegroundColor Green
}

Write-Host "[3/5] Cleaning..." -ForegroundColor Yellow
Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force __pycache__ -ErrorAction SilentlyContinue

Write-Host "[4/5] Building JARVIS.exe single file (5-10 min, please wait)..." -ForegroundColor Yellow
Write-Host "Bundles: brain, voice piper + your ElevenLabs CwhRBWXzGAHq8TQ4Fs17, holo movable UI, agent, team, proactive, knowledge, browser, goals..." -ForegroundColor Cyan

pyinstaller JARVIS.spec --noconfirm --clean

if ($LASTEXITCODE -ne 0) {
    Write-Host "Spec build failed, trying simple onefile..." -ForegroundColor Yellow
    pyinstaller --onefile --name JARVIS --console --add-data "web;web" --add-data "orb;orb" --add-data "data\piper_models;data\piper_models" JARVIS.py
}

Write-Host "[5/5] Done!" -ForegroundColor Green

if (Test-Path "dist\JARVIS.exe") {
    Write-Host ""
    Write-Host "=========================================" -ForegroundColor Green
    Write-Host "  SUCCESS, Sir! Single .EXE Built" -ForegroundColor Green
    Write-Host "=========================================" -ForegroundColor Green
    $size = (Get-Item "dist\JARVIS.exe").Length / 1MB
    Write-Host "  File: dist\JARVIS.exe ($([math]::Round($size,1)) MB)" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Double-click dist\JARVIS.exe to start whole JARVIS AI:" -ForegroundColor Cyan
    Write-Host "  - Web: http://localhost:8000 and /holo movable holographic" -ForegroundColor White
    Write-Host "  - Brain: qwen2.5:14b for 9070 XT if Ollama running" -ForegroundColor White
    Write-Host "  - Voice MUST BE PIPER free offline British + YOUR ElevenLabs CwhRBWXzGAHq8TQ4Fs17 if API key in .env" -ForegroundColor White
    Write-Host "  - Proactive, team, agent, second brain, etc - all in one" -ForegroundColor White
    Write-Host "  - Tray: close = minimize to tray, stays alive like real JARVIS" -ForegroundColor White
    Write-Host "  - 100% FREE, No API Keys (except optional ElevenLabs for your voice)" -ForegroundColor White
    Write-Host ""
    Write-Host "  Double-click dist\JARVIS.exe now to test, Sir." -ForegroundColor Green
} else {
    Write-Host "Build failed, dist\JARVIS.exe not found" -ForegroundColor Red
}
