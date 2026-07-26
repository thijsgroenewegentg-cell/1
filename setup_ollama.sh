#!/bin/bash
# Setup script for Super AI with the smartest Ollama model
# Run this after ensuring ollama binary is installed.
# See: https://github.com/ollama/ollama

set -e

echo "=== Super AI + Smartest Ollama Setup ==="
echo "Targeting the best available models for autonomous agent work..."

MODELS=(
  "qwen3-coder-next"
  "qwen2.5-coder:32b"
  "deepseek-r1:32b"
  "llama4:scout"
  "qwen3:32b"
)

echo "Available models will be pulled in order of preference."
echo "This may take a long time depending on your connection and VRAM."

for model in "${MODELS[@]}"; do
    echo "Attempting to pull: $model"
    if ollama pull "$model" 2>/dev/null; then
        echo "Successfully pulled $model"
        # Configure as default in agent config
        echo "$model" > .ollama_default_model
        echo "Default set to: $model"
        break
    else
        echo "Failed to pull $model (not available or server down). Trying next..."
    fi
done

if [ -f .ollama_default_model ]; then
    echo "=== Setup Complete ==="
    echo "Smartest available model configured: $(cat .ollama_default_model)"
else
    echo "=== Setup Incomplete ==="
    echo "No model could be pulled. Ensure ollama server is running and you have network access."
    echo "Try manually: ollama pull qwen3-coder-next"
fi
