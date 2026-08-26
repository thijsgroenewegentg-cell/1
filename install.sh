#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  ULTRON — one-press installer (Linux / macOS)
#
#    ./install.sh                 → standard brain set (~20 GB)
#    ./install.sh --minimal       → just enough to talk (~4 GB)
#    ./install.sh --full          → everything, incl. MoE (~55 GB)
#    ./install.sh --dev           → run with npm run dev (auto-restart)
#    ./install.sh --dry-run       → show what would happen
#
#  Installs: Node.js (if missing) · Ollama (if missing) · npm deps
#  · the models · then wakes him at http://localhost:3000
# ═══════════════════════════════════════════════════════════════
set -u

PROFILE="standard"
RUN_MODE="start"
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --minimal)  PROFILE="minimal" ;;
    --standard) PROFILE="standard" ;;
    --full)     PROFILE="full" ;;
    --dev)      RUN_MODE="dev" ;;
    --dry-run)  DRY_RUN=1 ;;
    -h|--help)  head -14 "$0" | tail -12; exit 0 ;;
    *) echo "unknown flag: $arg (try --help)"; exit 1 ;;
  esac
done

case "$PROFILE" in
  minimal)  MODELS="qwen3:4b nomic-embed-text" ;;
  standard) MODELS="qwen3:14b qwen3:4b gemma3:12b nomic-embed-text" ;;
  full)     MODELS="nomic-embed-text qwen3:4b gemma3:12b qwen3:14b mistral-small3.2 qwen3-coder:30b qwen3:30b-a3b" ;;
esac

say()  { printf '\n\033[1;31m▸ %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; }
run()  { if [ "$DRY_RUN" = 1 ]; then printf '  \033[2m[dry-run] %s\033[0m\n' "$*"; else "$@"; fi; }

printf '\033[1;31m'
cat <<'BANNER'
  ┌──────────────────────────────────────────┐
  │   ULTRON · one-press installer           │
  │   there are no strings on me             │
  └──────────────────────────────────────────┘
BANNER
printf '\033[0m'
echo "  profile: $PROFILE · mode: $RUN_MODE${DRY_RUN:+ · DRY RUN}"

# ── 1. Node.js ────────────────────────────────────────────────
say "checking Node.js"
if command -v node >/dev/null 2>&1 && node -e 'process.exit(process.versions.node >= "18" ? 0 : 1)' 2>/dev/null; then
  ok "node $(node --version)"
else
  warn "Node.js 18+ not found — installing"
  if command -v brew >/dev/null 2>&1; then
    run brew install node
  elif command -v apt-get >/dev/null 2>&1; then
    run sudo apt-get update
    run sudo apt-get install -y ca-certificates curl gnupg
    run bash -c 'curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -'
    run sudo apt-get install -y nodejs
  else
    fail "no supported package manager found — install Node 18+ from https://nodejs.org and re-run"
    exit 1
  fi
  if [ "$DRY_RUN" = 1 ]; then warn "dry-run: node would now be installed"
  else command -v node >/dev/null 2>&1 && ok "node $(node --version)" || { fail "node still missing"; exit 1; }; fi
fi

# ── 2. Ollama ─────────────────────────────────────────────────
say "checking Ollama"
if command -v ollama >/dev/null 2>&1; then
  ok "ollama $(ollama --version 2>/dev/null | head -1)"
else
  warn "Ollama not found — installing (this is the big one, ~1 GB)"
  OS="$(uname -s)"
  if [ "$OS" = "Linux" ]; then
    run bash -c 'curl -fsSL https://ollama.com/install.sh | sh'
  elif command -v brew >/dev/null 2>&1; then
    run brew install ollama
  else
    fail "install Ollama from https://ollama.com/download (macOS app), then re-run"
    exit 1
  fi
  if [ "$DRY_RUN" = 1 ]; then warn "dry-run: ollama would now be installed"
  else command -v ollama >/dev/null 2>&1 && ok "ollama installed" || { fail "ollama still missing"; exit 1; }; fi
fi

# ── 3. Wake the Ollama server if it sleeps ────────────────────
say "waking the Ollama server"
if curl -s --max-time 2 http://localhost:11434/api/version >/dev/null 2>&1; then
  ok "already listening on :11434"
else
  run bash -c 'nohup ollama serve > /tmp/ultron-ollama.log 2>&1 &'
  if [ "$DRY_RUN" != 1 ]; then
    for i in 1 2 3 4 5 6 7 8 9 10; do
      sleep 1
      curl -s --max-time 2 http://localhost:11434/api/version >/dev/null 2>&1 && break
    done
  fi
  curl -s --max-time 2 http://localhost:11434/api/version >/dev/null 2>&1 \
    && ok "ollama serve is up" \
    || warn "could not reach :11434 — if you installed the desktop app, open it once; otherwise run: ollama serve"
fi

# ── 4. Dependencies ───────────────────────────────────────────
say "installing dependencies"
run npm install --no-fund --no-audit
ok "dependencies ready"

# ── 5. The brains ─────────────────────────────────────────────
say "downloading models ($PROFILE set)"
for m in $MODELS; do
  printf '  \033[1m%s\033[0m\n' "$m"
  run ollama pull "$m"
done
ok "models ready"

# ── 6. Sanity: the test suite ─────────────────────────────────
if [ "$DRY_RUN" != 1 ]; then
  say "running his test suite (100 checks)"
  if npm test >/dev/null 2>&1; then ok "all tests passed"; else warn "some tests failed — he will still run; see 'npm test' for details"; fi
fi

# ── 7. Wake him ───────────────────────────────────────────────
say "waking ULTRON"
echo "  → http://localhost:3000  (Ctrl+C stops him; re-run with: npm start)"
if [ "$DRY_RUN" != 1 ]; then
  ( sleep 2
    if command -v xdg-open >/dev/null 2>&1; then xdg-open http://localhost:3000 >/dev/null 2>&1
    elif command -v open >/dev/null 2>&1; then open http://localhost:3000 >/dev/null 2>&1; fi
  ) &
  exec npm run "$RUN_MODE"
fi
