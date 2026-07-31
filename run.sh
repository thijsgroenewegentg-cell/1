#!/bin/bash
# JARVIS Singular App Launcher - RX 9070 XT 16GB Optimized - 100% FREE
# Usage: ./run.sh [mode]

MODE=${1:-singular}

case $MODE in
  singular|jarvis|main)
    echo "Starting JARVIS Singular App - Everything in One - RX 9070 XT 16GB - 100% FREE, Sir..."
    echo "Features: Minimal + Holo Movable + Agent + Team + Proactive + Always-On + Evolution + Self-Edit + Voice"
    python3 JARVIS.py
    ;;
  9070xt|amd)
    echo "Starting JARVIS for RX 9070 XT 16GB - Optimized 14B model, ROCm, Singular App"
    echo "Checking ROCm..."
    rocm-smi 2>/dev/null || echo "ROCm not found, but will try HSA_OVERRIDE_GFX_VERSION=12.0.0"
    echo "Pulling 14B model for 9070 XT (best for 16GB)..."
    ollama pull qwen2.5:14b || ollama pull qwen2.5:7b
    ollama pull nomic-embed-text || true
    echo "Creating jarvis model from Modelfile.9070xt (14B)..."
    ollama create jarvis -f Modelfile.9070xt --force || ollama create jarvis -f Modelfile --force
    echo "Starting Singular App..."
    python3 JARVIS.py
    ;;
  cli)
    echo "Starting JARVIS CLI, Sir..."
    python3 cli.py
    ;;
  web)
    echo "Starting JARVIS Web UI at http://localhost:8000 and /holo"
    python3 web/server.py
    ;;
  holo)
    echo "Starting JARVIS Holographic Movable UI at http://localhost:8000/holo"
    python3 web/server.py &
    sleep 2
    xdg-open http://localhost:8000/holo 2>/dev/null || open http://localhost:8000/holo 2>/dev/null || echo "Open http://localhost:8000/holo"
    wait
    ;;
  voice)
    echo "Starting Voice Mode..."
    python3 cli.py --voice --wake-word
    ;;
  always-on)
    echo "Starting Always-On Wake Word 24/7 - Say 'Jarvis' anytime"
    python3 cli.py --always-on
    ;;
  proactive)
    echo "Starting Proactive Engine - Morning briefing, git watcher"
    python3 cli.py --proactive
    ;;
  agent)
    TASK=${2:-"Analyze codebase and add tests"}
    echo "Starting Coding Agent: $TASK"
    python3 cli.py --agent "$TASK"
    ;;
  team)
    TASK=${2:-"Research best auth lib and implement JWT"}
    echo "Starting Multi-Agent Team: $TASK"
    python3 cli.py --team "$TASK"
    ;;
  desktop|python)
    echo "Starting Python Desktop..."
    python3 desktop/python/main.py
    ;;
  webview)
    echo "Starting WebView Desktop..."
    python3 desktop/python/webview_app.py
    ;;
  electron)
    echo "Starting Electron Desktop..."
    cd desktop/electron
    [ ! -d "node_modules" ] && npm install
    npm start
    ;;
  auto)
    echo "Auto-launching best desktop..."
    python3 desktop/launch.py
    ;;
  docker)
    echo "Docker - choose profile:"
    echo "  CPU: docker-compose --profile cpu up"
    echo "  NVIDIA: docker-compose --profile nvidia up"
    echo "  AMD 9070 XT: docker-compose --profile 9070xt up (ROCm, 14B model)"
    docker-compose --profile cpu up --build
    ;;
  docker-amd|amd-docker|9070xt-docker)
    echo "Docker AMD ROCm for RX 9070 XT 16GB - 14B model"
    docker-compose --profile 9070xt up --build
    ;;
  install)
    echo "Full install - 100% FREE"
    ./setup.sh
    pip install -r requirements.txt --break-system-packages || true
    echo "For 9070 XT: ollama pull qwen2.5:14b && ollama create jarvis -f Modelfile.9070xt --force"
    ;;
  index)
    echo "Indexing codebase for RAG..."
    python3 cli.py --index
    ;;
  *)
    echo "J.A.R.V.I.S 4.0 Singular App - RX 9070 XT 16GB - 100% FREE"
    echo "Usage: ./run.sh [mode] [task]"
    echo ""
    echo "SINGULAR APP (everything in one):"
    echo "  singular  - Singular App - web + holo + tray + proactive + wake word + agent + team (default)"
    echo "  9070xt    - Optimized for RX 9070 XT 16GB - pulls 14B, creates jarvis from Modelfile.9070xt, starts singular"
    echo ""
    echo "MODES:"
    echo "  cli       - Terminal chat"
    echo "  web       - Web UI http://localhost:8000 + /holo movable"
    echo "  holo      - Holographic movable UI only"
    echo "  voice     - Voice chat"
    echo "  always-on - 24/7 wake word 'Jarvis' like real JARVIS"
    echo "  proactive - Proactive engine briefing + git watcher"
    echo "  agent [task] - Autonomous coding agent"
    echo "  team [task]  - Multi-agent team (planner/researcher/coder/reviewer)"
    echo "  desktop   - Python desktop native"
    echo "  webview   - PyWebView desktop"
    echo "  electron  - Electron desktop, global hotkey Ctrl+Shift+J"
    echo "  auto      - Auto-pick best desktop"
    echo "  docker    - Docker CPU"
    echo "  docker-amd - Docker AMD ROCm 9070 XT profile (14B)"
    echo "  install   - Full setup"
    echo "  index     - Index codebase for RAG"
    echo ""
    echo "EXAMPLES:"
    echo "  ./run.sh singular"
    echo "  ./run.sh 9070xt"
    echo "  ./run.sh agent 'Add JWT auth'"
    echo "  ./run.sh team 'Research best rate limit lib and implement'"
    echo "  ./run.sh always-on"
    ;;
esac
