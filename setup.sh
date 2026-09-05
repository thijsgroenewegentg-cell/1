#!/usr/bin/env bash
# /setup.sh
# =============================================================================
# JARVIS — one-click setup.
#
#   1. checks Python
#   2. creates a virtual environment
#   3. installs all requirements
#   4. installs Ollama and pulls the models
#   5. creates directories + default config
#   6. tests every component
#   7. tells you how to start
#
# Usage:  bash setup.sh            (full setup)
#         bash setup.sh --minimal  (skip heavy voice/ML packages)
#         bash setup.sh --no-model (skip the LLM download)
# =============================================================================
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

VENV_DIR="${PROJECT_DIR}/.venv"
LLM_MODEL="${JARVIS_MODEL:-llama3.2}"
EMBED_MODEL="${JARVIS_EMBED_MODEL:-nomic-embed-text}"
MINIMAL=0
SKIP_MODEL=0

for arg in "$@"; do
  case "$arg" in
    --minimal)  MINIMAL=1 ;;
    --no-model) SKIP_MODEL=1 ;;
    -h|--help)  sed -n '2,18p' "$0"; exit 0 ;;
  esac
done

BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'
BLUE=$'\033[36m'; DIM=$'\033[2m'; RESET=$'\033[0m'

say()   { printf "%s\n" "${BLUE}${BOLD}==>${RESET} ${BOLD}$*${RESET}"; }
ok()    { printf "%s\n" "  ${GREEN}✓${RESET} $*"; }
warn()  { printf "%s\n" "  ${YELLOW}!${RESET} $*"; }
fail()  { printf "%s\n" "  ${RED}✗${RESET} $*"; }
note()  { printf "%s\n" "  ${DIM}$*${RESET}"; }

cat <<'BANNER'

     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝

  Free. Local. Yours.  —  setup

BANNER

# -----------------------------------------------------------------------------
# 0. Platform
# -----------------------------------------------------------------------------
case "$(uname -s)" in
  Linux*)   OS=linux ;;
  Darwin*)  OS=macos ;;
  MINGW*|MSYS*|CYGWIN*) OS=windows ;;
  *)        OS=unknown ;;
esac
say "Platform: $OS"

# -----------------------------------------------------------------------------
# 1. Python
# -----------------------------------------------------------------------------
say "Step 1/7 — checking Python"
PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0)"
    major="${version%%.*}"; minor="${version##*.}"
    if [ "${major:-0}" -eq 3 ] && [ "${minor:-0}" -ge 9 ]; then
      PYTHON="$candidate"; break
    fi
  fi
done
if [ -z "$PYTHON" ]; then
  fail "Python 3.9+ not found. Install it from https://python.org and re-run."
  exit 1
fi
ok "Using $($PYTHON --version) at $(command -v "$PYTHON")"

# -----------------------------------------------------------------------------
# 2. System audio dependencies (best effort, never fatal)
# -----------------------------------------------------------------------------
say "Step 2/7 — system audio dependencies"
if [ "$OS" = "linux" ]; then
  if command -v apt-get >/dev/null 2>&1; then
    note "sudo apt-get install -y portaudio19-dev ffmpeg python3-dev"
    sudo apt-get update -qq >/dev/null 2>&1
    sudo apt-get install -y -qq portaudio19-dev ffmpeg python3-dev libsndfile1 >/dev/null 2>&1 \
      && ok "portaudio + ffmpeg installed" || warn "Could not auto-install audio packages (sudo needed)."
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y portaudio-devel ffmpeg python3-devel >/dev/null 2>&1 \
      && ok "portaudio + ffmpeg installed" || warn "Install portaudio-devel and ffmpeg manually."
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --noconfirm portaudio ffmpeg >/dev/null 2>&1 \
      && ok "portaudio + ffmpeg installed" || warn "Install portaudio and ffmpeg manually."
  else
    warn "Unknown package manager — install portaudio and ffmpeg yourself for voice mode."
  fi
elif [ "$OS" = "macos" ]; then
  if command -v brew >/dev/null 2>&1; then
    brew list portaudio >/dev/null 2>&1 || brew install portaudio >/dev/null 2>&1
    brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg >/dev/null 2>&1
    ok "portaudio + ffmpeg present"
  else
    warn "Homebrew not found. Install it (https://brew.sh) then: brew install portaudio ffmpeg"
  fi
else
  note "On Windows, pip wheels bundle the audio libraries. For MP3 playback install ffmpeg:"
  note "  winget install Gyan.FFmpeg"
fi

# -----------------------------------------------------------------------------
# 3. Virtual environment + Python packages
# -----------------------------------------------------------------------------
say "Step 3/7 — virtual environment"
if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON" -m venv "$VENV_DIR" && ok "Created $VENV_DIR" || { fail "venv creation failed"; exit 1; }
else
  ok "Re-using existing $VENV_DIR"
fi

if [ -x "$VENV_DIR/bin/python" ]; then
  VPY="$VENV_DIR/bin/python"
else
  VPY="$VENV_DIR/Scripts/python.exe"
fi

say "Step 4/7 — installing Python packages (this takes a few minutes)"
"$VPY" -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 && ok "pip upgraded"

if [ "$MINIMAL" -eq 1 ]; then
  note "Minimal mode: core + text interface only."
  "$VPY" -m pip install -q PyYAML httpx rich psutil python-dateutil ddgs \
      beautifulsoup4 lxml requests feedparser chromadb pypdf pandas pyperclip \
      fastapi "uvicorn[standard]" \
    && ok "Core packages installed" || warn "Some core packages failed — see output above."
else
  if "$VPY" -m pip install -q -r requirements.txt; then
    ok "All packages installed"
  else
    warn "Full install hit an error — retrying without the optional voice stack."
    "$VPY" -m pip install -q PyYAML httpx rich psutil python-dateutil ddgs \
        beautifulsoup4 lxml requests feedparser chromadb pypdf python-docx pandas \
        pyautogui pyperclip Pillow fastapi "uvicorn[standard]" \
      && ok "Core packages installed (voice extras skipped)" \
      || fail "Package installation failed. Check the errors above."
  fi
fi

# -----------------------------------------------------------------------------
# 4. Ollama + models
# -----------------------------------------------------------------------------
say "Step 5/7 — Ollama (the local LLM engine)"
if command -v ollama >/dev/null 2>&1; then
  ok "Ollama already installed ($(ollama --version 2>/dev/null | head -1))"
else
  case "$OS" in
    linux|macos)
      if command -v brew >/dev/null 2>&1 && [ "$OS" = "macos" ]; then
        brew install ollama >/dev/null 2>&1 && ok "Installed Ollama via Homebrew" \
          || warn "brew install ollama failed — download from https://ollama.com/download"
      else
        note "Running the official installer: curl -fsSL https://ollama.com/install.sh | sh"
        if curl -fsSL https://ollama.com/install.sh | sh >/dev/null 2>&1; then
          ok "Ollama installed"
        else
          warn "Automatic install failed. Get it from https://ollama.com/download"
        fi
      fi
      ;;
    *)
      warn "Download the Windows installer from https://ollama.com/download"
      ;;
  esac
fi

if command -v ollama >/dev/null 2>&1; then
  if ! curl -s --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
    note "Starting the Ollama server in the background…"
    (ollama serve >/dev/null 2>&1 &) 
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      curl -s --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1 && break
      sleep 1
    done
  fi
  if curl -s --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
    ok "Ollama server responding on http://localhost:11434"
    if [ "$SKIP_MODEL" -eq 0 ]; then
      if ollama list 2>/dev/null | grep -q "^${LLM_MODEL}"; then
        ok "Model '${LLM_MODEL}' already present"
      else
        note "Pulling '${LLM_MODEL}' (~2 GB, one time)…"
        ollama pull "$LLM_MODEL" && ok "Model '${LLM_MODEL}' ready" \
          || warn "Pull failed. Try manually: ollama pull ${LLM_MODEL}"
      fi
      if ollama list 2>/dev/null | grep -q "^${EMBED_MODEL}"; then
        ok "Embedding model '${EMBED_MODEL}' already present"
      else
        note "Pulling '${EMBED_MODEL}' (~270 MB, for long-term memory)…"
        ollama pull "$EMBED_MODEL" >/dev/null 2>&1 && ok "Embedding model ready" \
          || warn "Embedding pull failed — JARVIS will use offline hash embeddings."
      fi
    else
      note "Skipping model download (--no-model)."
    fi
  else
    warn "Ollama isn't responding. Start it in another terminal with: ollama serve"
  fi
fi

# -----------------------------------------------------------------------------
# 5. Directories + config
# -----------------------------------------------------------------------------
say "Step 6/7 — directories and configuration"
mkdir -p data/chroma data/notes data/code data/screenshots data/downloads data/tts logs
ok "Created data/ and logs/"

if [ -f config.yaml ]; then
  ok "config.yaml already exists (left untouched)"
else
  "$VPY" - <<'PYCONF'
import sys
sys.path.insert(0, ".")
from core.config import Config
config = Config.load("config.yaml")
print(f"  wrote {config.path}")
PYCONF
  ok "Default config.yaml generated"
fi

# -----------------------------------------------------------------------------
# 6. Component test
# -----------------------------------------------------------------------------
say "Step 7/7 — testing components"
"$VPY" - <<'PYTEST'
import importlib.util
import sys

sys.path.insert(0, ".")

GREEN, YELLOW, RED, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[0m"


def probe(label, module, required=True):
    """Report whether an optional dependency imported."""
    present = importlib.util.find_spec(module) is not None
    mark = f"{GREEN}✓{RESET}" if present else (f"{RED}✗{RESET}" if required else f"{YELLOW}○{RESET}")
    print(f"  {mark} {label}")
    return present


print("  Python packages:")
core_ok = all([
    probe("PyYAML (config)", "yaml"),
    probe("httpx (Ollama client)", "httpx"),
    probe("rich (terminal UI)", "rich"),
    probe("psutil (system stats)", "psutil"),
])
probe("chromadb (vector memory)", "chromadb", required=False)
probe("ddgs (web search)", "ddgs", required=False)
probe("beautifulsoup4 (scraping)", "bs4", required=False)
probe("feedparser (news)", "feedparser", required=False)
probe("edge-tts (speech out)", "edge_tts", required=False)
probe("faster-whisper (speech in)", "faster_whisper", required=False)
probe("sounddevice (microphone)", "sounddevice", required=False)
probe("pvporcupine (wake word)", "pvporcupine", required=False)
probe("pyautogui (desktop control)", "pyautogui", required=False)
probe("pypdf / python-docx (documents)", "pypdf", required=False)
probe("pandas (CSV analysis)", "pandas", required=False)

print("\n  JARVIS modules:")
try:
    from core.brain import Brain
    from core.config import Config

    config = Config.load("config.yaml")
    brain = Brain(config)
    import asyncio

    asyncio.run(brain._load_modules())
    for name, module in brain.modules.items():
        print(f"  {GREEN}✓{RESET} {name}: {len(module.tools)} tools")
    if not brain.modules:
        print(f"  {RED}✗{RESET} no modules loaded")
except Exception as exc:  # noqa: BLE001
    print(f"  {RED}✗{RESET} module loading failed: {exc}")

sys.exit(0 if core_ok else 1)
PYTEST

TEST_STATUS=$?

# -----------------------------------------------------------------------------
# 7. Done
# -----------------------------------------------------------------------------
echo
if [ "$TEST_STATUS" -eq 0 ]; then
  printf "%s\n" "${GREEN}${BOLD}  Setup complete. JARVIS is ready.${RESET}"
else
  printf "%s\n" "${YELLOW}${BOLD}  Setup finished with warnings — see above.${RESET}"
fi
cat <<EOF

  ${BOLD}Start JARVIS${RESET}
    ${BLUE}source .venv/bin/activate${RESET}        (Windows: .venv\\Scripts\\activate)
    ${BLUE}python main.py${RESET}                   voice mode if a mic is available, else text
    ${BLUE}python main.py --cli${RESET}             force the text interface
    ${BLUE}python main.py --voice${RESET}           force voice mode
    ${BLUE}python main.py --web${RESET}             chat from your phone on the same Wi-Fi
    ${BLUE}python main.py --say "what time is it"${RESET}
    ${BLUE}python main.py --test${RESET}            component self-test

  ${BOLD}First things to try${RESET}
    "what time is it"            "open chrome"
    "how's the weather"          "set a timer for 10 minutes"
    "add buy milk to my todos"   "write a python script that renames files"
    "find all PDFs on my desktop"  "index my documents"
    "what's on my screen"          "what's on my calendar today"

  ${BOLD}Notes${RESET}
    · Ollama must be running: ${BLUE}ollama serve${RESET}
    · Wake word works with no API key (local Whisper). For Porcupine's
      lower-power detector, put a free key from console.picovoice.ai into
      config.yaml under voice.porcupine_access_key.
    · Optional extras, all free:
        ${BLUE}pip install openwakeword${RESET}     keyless "hey jarvis" wake word
        ${BLUE}ollama pull llava${RESET}            let JARVIS look at your screen
        ${BLUE}bash scripts/install_service_linux.sh${RESET}   start at login (systemd)
        ${BLUE}bash scripts/install_service_macos.sh${RESET}   start at login (LaunchAgent)
    · Everything runs locally. Nothing is sent to a paid service.

EOF
exit 0
