#!/bin/bash
# JARVIS Quick Launcher
# Usage: ./run.sh [cli|web|voice]

MODE=${1:-cli}

case $MODE in
  cli)
    echo "Starting JARVIS CLI, Sir..."
    python3 cli.py
    ;;
  web)
    echo "Starting JARVIS Web UI at http://localhost:8000"
    python3 web/server.py
    ;;
  voice)
    echo "Starting JARVIS Voice Mode..."
    echo "Say 'Jarvis' to wake"
    python3 cli.py --voice --wake-word
    ;;
  docker)
    docker-compose up --build
    ;;
  *)
    echo "Usage: ./run.sh [cli|web|voice|docker]"
    echo "  cli   - Terminal chat (default)"
    echo "  web   - Web holographic UI"
    echo "  voice - Voice hands-free"
    echo "  docker - Full stack with Ollama"
    ;;
esac
