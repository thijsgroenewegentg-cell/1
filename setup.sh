#!/bin/bash
set -e

echo "========================================="
echo "  J.A.R.V.I.S 2.0 - Ollama Setup"
echo "  Minimal + Self-Learning"
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
echo "[]" > data/vectors.json 2>/dev/null || echo '[]' > data/vectors.json
echo "{}" > data/user_profile.json 2>/dev/null || echo '{}' > data/user_profile.json
echo "[]" > data/reflections.json 2>/dev/null || true

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✓ Created .env from example"
fi

# Pull models
echo ""
echo "🧠 Pulling brain models (this may take a few minutes)..."

# Main LLM
MODEL="qwen2.5:7b"
echo "-> Pulling $MODEL..."
ollama pull $MODEL || echo "Failed to pull $MODEL, trying llama3.1:8b" && ollama pull llama3.1:8b

# Embedding model for self-learning (optional but recommended)
echo ""
echo "-> Pulling embedding model for self-learning: nomic-embed-text"
ollama pull nomic-embed-text || echo "⚠️ Embedding model pull failed, JARVIS will use hash fallback (still works)"

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
echo "  Setup Complete, Sir. JARVIS 2.0"
echo "========================================="
echo ""
echo "What's new:"
echo "  - Minimal clean UI (Linear/ChatGPT style)"
echo "  - Self-learning: auto-memory, vector search, reflection"
echo "  - Desktop apps: python native + electron"
echo ""
echo "Try it now:"
echo "  source venv/bin/activate"
echo "  python cli.py                              # CLI"
echo "  python web/server.py                       # Minimal Web UI -> http://localhost:8000"
echo "  python desktop/python/main.py              # Minimal Desktop"
echo "  python desktop/launch.py                   # Auto desktop"
echo "  cd desktop/electron && npm install && npm start  # Electron"
echo ""
echo "Voice mode:"
echo "  python cli.py --voice"
echo ""
echo "Available models:"
ollama list
echo ""
echo "If jarvis model missing, run: ollama create jarvis -f Modelfile"
