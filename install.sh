#!/usr/bin/env bash
# /install.sh
# =============================================================================
#  JARVIS — one-command installer for macOS and Linux.
#
#    bash install.sh                 interactive install
#    bash install.sh --yes           no questions asked
#    bash install.sh --minimal       text-only, smallest install
#
#  It finds a suitable Python, then runs install.py, which does the rest:
#  virtual environment, packages, Ollama, the model, folders, configuration,
#  a menu shortcut and a component self-test.
#
#  It can also bootstrap from nothing: run it outside a JARVIS folder and it
#  clones the project first.
# =============================================================================
set -uo pipefail

REPO_URL="${JARVIS_REPO:-https://github.com/thijsgroenewegentg-cell/1.git}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"

BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'
BLUE=$'\033[36m'; DIM=$'\033[2m'; RESET=$'\033[0m'

say()  { printf "%s\n" "${BLUE}${BOLD}==>${RESET} ${BOLD}$*${RESET}"; }
ok()   { printf "%s\n" "  ${GREEN}✓${RESET} $*"; }
warn() { printf "%s\n" "  ${YELLOW}!${RESET} $*"; }
die()  { printf "%s\n" "  ${RED}✗${RESET} $*"; exit 1; }

# --- 1. Locate the project ---------------------------------------------------
PROJECT_DIR="$SCRIPT_DIR"
if [ ! -f "$PROJECT_DIR/install.py" ]; then
  say "No JARVIS folder here — fetching a fresh copy"
  command -v git >/dev/null 2>&1 || die "git is required to download JARVIS (https://git-scm.com)."
  PROJECT_DIR="${HOME}/jarvis"
  if [ -d "$PROJECT_DIR/.git" ]; then
    ok "updating the existing copy in ${PROJECT_DIR}"
    git -C "$PROJECT_DIR" pull --ff-only >/dev/null 2>&1 || warn "could not update — using what is there"
  else
    git clone --depth 1 "$REPO_URL" "$PROJECT_DIR" || die "clone failed."
    ok "downloaded to ${PROJECT_DIR}"
  fi
fi
cd "$PROJECT_DIR" || die "cannot enter ${PROJECT_DIR}"

# --- 2. Find a Python 3.9+ ---------------------------------------------------
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  printf "%s\n" "  ${RED}✗${RESET} Python 3.9 or newer was not found."
  if [ "$(uname -s)" = "Darwin" ]; then
    echo "     Install it with:  brew install python@3.12"
    echo "     …or download it from https://www.python.org/downloads/"
  else
    echo "     Debian/Ubuntu:  sudo apt install python3 python3-venv python3-pip"
    echo "     Fedora:         sudo dnf install python3 python3-pip"
    echo "     Arch:           sudo pacman -S python"
  fi
  exit 1
fi
ok "using $("$PYTHON" -V 2>&1) at $(command -v "$PYTHON")"

# --- 3. Hand over to the real installer -------------------------------------
exec "$PYTHON" install.py "$@"
