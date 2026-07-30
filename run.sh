#!/bin/bash
# JARVIS Quick Launcher
# Usage: ./run.sh [cli|web|voice|desktop|electron|webview|docker]

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
  desktop|python)
    echo "Starting JARVIS Python Desktop (Native)..."
    python3 desktop/python/main.py
    ;;
  webview)
    echo "Starting JARVIS WebView Desktop..."
    python3 desktop/python/webview_app.py
    ;;
  electron)
    echo "Starting JARVIS Electron Desktop..."
    cd desktop/electron
    if [ ! -d "node_modules" ]; then
      echo "Installing npm deps, Sir..."
      npm install
    fi
    npm start
    ;;
  auto)
    echo "Auto-launching best desktop, Sir..."
    python3 desktop/launch.py
    ;;
  docker)
    docker-compose up --build
    ;;
  install)
    echo "Full install, Sir..."
    ./setup.sh
    pip install -r desktop/python/requirements.txt --break-system-packages || true
    echo "Optional: cd desktop/electron && npm install"
    ;;
  *)
    echo "J.A.R.V.I.S Launcher - Stark Industries"
    echo "Usage: ./run.sh [mode]"
    echo ""
    echo "Modes:"
    echo "  cli       - Terminal chat (default)"
    echo "  web       - Web holographic UI http://localhost:8000"
    echo "  voice     - Voice hands-free with wake word"
    echo "  desktop   - Python native desktop (customtkinter + tray)"
    echo "  webview   - PyWebView desktop (lightweight native)"
    echo "  electron  - Electron desktop (slick, needs npm)"
    echo "  auto      - Auto-pick best desktop"
    echo "  docker    - Full stack with Ollama"
    echo "  install   - Full setup"
    echo ""
    echo "Examples:"
    echo "  ./run.sh cli"
    echo "  ./run.sh desktop"
    echo "  ./run.sh electron"
    ;;
esac
