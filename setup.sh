#!/bin/bash
set -e

echo "========================================="
echo "  J.A.R.V.I.S  - Ollama Setup"
echo "  At your service, Sir."
echo "========================================="

# Check python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found. Please install Python 3.10+"
    exit 1
fi

# Check ollama
if ! command -v ollama &> /dev/null; then
    echo "📦 Ollama not found. Installing..."
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        curl -fsSL https://ollama.com/install.sh | sh
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "Please install Ollama from https://ollama.com"
        echo "brew install ollama"
        exit 1
    else
        echo "Please install Ollama from https://ollama.com"
        exit 1
    fi
else
    echo "✓ Ollama found: $(ollama --version)"
fi

# Check if ollama is running, if not start it
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "🚀 Starting Ollama service..."
    ollama serve > /dev/null 2>&1 &
    sleep 3
else
    echo "✓ Ollama is running"
fi

# Create venv? Optional
if [ ! -d "venv" ]; then
    echo "🐍 Creating virtual environment..."
    python3 -m venv venv
fi

echo "📦 Installing Python dependencies..."
source venv/bin/activate 2>/dev/null || true
pip install --upgrade pip
pip install -r requirements.txt

# Create dirs
mkdir -p data workspace
touch data/long_term_memory.json
touch data/conversations.json
echo "[]" > data/long_term_memory.json 2>/dev/null || echo '{"memories":[]}' > data/long_term_memory.json

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✓ Created .env from example"
fi

# Pull model
MODEL="qwen2.5:7b"
echo ""
echo "🧠 Pulling brain model: $MODEL (this may take a few minutes)..."
ollama pull $MODEL || echo "Failed to pull $MODEL, trying llama3.1:8b" && ollama pull llama3.1:8b

# Try to create jarvis model
echo ""
echo "🎭 Creating JARVIS personality..."
if [ -f "Modelfile" ]; then
    ollama create jarvis -f Modelfile || echo "⚠️ Could not create jarvis model, using base model"
else
    echo "⚠️ Modelfile not found"
fi

echo ""
echo "========================================="
echo "  Setup Complete, Sir."
echo "========================================="
echo ""
echo "Try it now:"
echo "  source venv/bin/activate"
echo "  python cli.py"
echo ""
echo "Voice mode:"
echo "  python cli.py --voice"
echo ""
echo "Web UI:"
echo "  python web/server.py"
echo "  -> http://localhost:8000"
echo ""
echo "Available models:"
ollama list
echo ""
echo "If jarvis model missing, run: ollama create jarvis -f Modelfile"
