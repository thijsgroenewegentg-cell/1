#!/usr/bin/env bash
# /scripts/jarvis.sh
# Convenience launcher: activates the project virtualenv, makes sure Ollama is
# up, then starts JARVIS with whatever arguments you pass.
#
#   ./scripts/jarvis.sh              # voice if available, else text
#   ./scripts/jarvis.sh --cli        # text interface
#   ./scripts/jarvis.sh --web        # phone/LAN interface
#   ./scripts/jarvis.sh --say "what's the weather"

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

PYTHON="${PROJECT_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON}" ]]; then
  echo "No virtualenv found — running ./setup.sh first."
  bash ./setup.sh
fi

# Start Ollama in the background if it isn't answering yet.
if command -v ollama >/dev/null 2>&1; then
  if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "Starting Ollama…"
    nohup ollama serve >/dev/null 2>&1 &
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break
      sleep 1
    done
  fi
else
  echo "Ollama is not installed — JARVIS will run in degraded (no-LLM) mode."
  echo "Install it from https://ollama.com/download (free)."
fi

exec "${PYTHON}" main.py "$@"
