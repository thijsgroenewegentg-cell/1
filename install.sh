#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# JARVIS (Ollama Edition) — one-click installer
#
#   curl -fsSL <raw url of this file> | bash
#   # or locally:
#   bash install.sh [options]
#
# What it does:
#   1. Installs Node >= 22 (portable, into ~/.jarvis/runtime — no root needed)
#   2. Installs Ollama if missing (best effort) and makes sure it is running
#   3. Installs JARVIS into ~/.jarvis/app
#   4. Writes ~/.jarvis/config.yaml and pulls the default models
#   5. Installs the `jarvis` launcher (+ optional systemd/launchd service)
#   6. Starts the daemon and prints the dashboard URL
#
# Options:
#   --home DIR        Install root            (default: ~/.jarvis)
#   --model NAME      Smart model             (default: llama3.2)
#   --fast-model NAME Fast model              (default: llama3.2:1b)
#   --port N          Dashboard port          (default: 3142)
#   --no-models       Skip pulling models
#   --no-ollama       Skip Ollama install/start (it runs on another machine)
#   --no-start        Don't start the daemon after install
#   --service         Also install a systemd user / launchd service
#   --open            Open the dashboard in a browser when ready
#   --local [DIR]     Install from a local source dir (default: this repo)
#   --uninstall       Remove JARVIS (keeps ~/.jarvis/data; add --purge to wipe)
#   --purge           With --uninstall: delete everything including data
#   -y, --yes         Never prompt
#   -h, --help        Show this help
#
# Env overrides: JARVIS_REF (git branch/tag), JARVIS_REPO, JARVIS_NODE_VERSION
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

VERSION="0.1.0"
JARVIS_HOME="${JARVIS_HOME:-$HOME/.jarvis}"
MODEL="llama3.2"
FAST_MODEL="llama3.2:1b"
PORT="3142"
DO_MODELS=1
DO_START=1
DO_SERVICE=0
DO_OPEN=0
DO_OLLAMA=1
DO_UNINSTALL=0
PURGE=0
ASSUME_YES=0
LOCAL_SRC=""
JARVIS_REPO="${JARVIS_REPO:-https://github.com/thijsgroenewegentg-cell/1.git}"
JARVIS_REF="${JARVIS_REF:-main}"

APP_DIR="$JARVIS_HOME/app"
RUNTIME_DIR="$JARVIS_HOME/runtime"
LAUNCHER="$JARVIS_HOME/bin/jarvis"

# ── pretty output ────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'
else
  C_RESET=""; C_BOLD=""; C_DIM=""; C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""
fi
info() { printf '%s\n' "${C_CYAN}▸${C_RESET} $*"; }
ok()   { printf '%s\n' "${C_GREEN}✔${C_RESET} $*"; }
warn() { printf '%s\n' "${C_YELLOW}⚠${C_RESET} $*" >&2; }
err()  { printf '%s\n' "${C_RED}✖${C_RESET} $*" >&2; }
die()  { err "$*"; exit 1; }
banner() {
  printf '\n%s' "$C_BOLD"
  cat <<'EOF'
       ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
       ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
       ██║███████║██████╔╝██║   ██║██║███████╗
  ██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
  ╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
   ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
EOF
  printf '%s%s\n\n' "$C_RESET" "${C_DIM}Just A Rather Very Intelligent System — Ollama Edition v${VERSION}${C_RESET}"
}

confirm() { # $1 = question; returns 0 to proceed
  if [ "$ASSUME_YES" -eq 1 ] || [ ! -t 0 ]; then return 0; fi
  local answer
  read -r -p "$1 [Y/n] " answer
  case "${answer:-Y}" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

have() { command -v "$1" >/dev/null 2>&1; }

# ── argument parsing ─────────────────────────────────────────────────────────
usage() {
  cat <<'EOF'
JARVIS (Ollama Edition) installer

Usage: bash install.sh [options]

  --home DIR        Install root            (default: ~/.jarvis)
  --model NAME      Smart model             (default: llama3.2)
  --fast-model NAME Fast model              (default: llama3.2:1b)
  --port N          Dashboard port          (default: 3142)
  --no-models       Skip pulling models
  --no-ollama       Skip Ollama install/start (e.g. it runs on another machine)
  --no-start        Don't start the daemon after install
  --service         Also install a systemd user / launchd service
  --open            Open the dashboard in a browser when ready
  --local [DIR]     Install from a local source dir (default: this repo)
  --uninstall       Remove JARVIS (keeps data; add --purge to wipe)
  --purge           With --uninstall: delete everything including data
  -y, --yes         Never prompt
  -h, --help        Show this help

Env overrides: JARVIS_REF (git branch/tag), JARVIS_REPO, JARVIS_NODE_VERSION
EOF
}
while [ $# -gt 0 ]; do
  case "$1" in
    --home)        JARVIS_HOME="$2"; shift 2 ;;
    --model)       MODEL="$2"; shift 2 ;;
    --fast-model)  FAST_MODEL="$2"; shift 2 ;;
    --port)        PORT="$2"; shift 2 ;;
    --no-models)   DO_MODELS=0; shift ;;
    --no-ollama)   DO_OLLAMA=0; shift ;;
    --no-start)    DO_START=0; shift ;;
    --service)     DO_SERVICE=1; shift ;;
    --open)        DO_OPEN=1; shift ;;
    --local)       LOCAL_SRC="__SELF__"
                   if [ $# -ge 2 ] && [ "${2#-}" = "$2" ]; then LOCAL_SRC="$2"; shift; fi
                   shift ;;
    --uninstall)   DO_UNINSTALL=1; shift ;;
    --purge)       PURGE=1; shift ;;
    -y|--yes)      ASSUME_YES=1; shift ;;
    -h|--help)     usage; exit 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

# recompute derived paths after --home
APP_DIR="$JARVIS_HOME/app"
RUNTIME_DIR="$JARVIS_HOME/runtime"
LAUNCHER="$JARVIS_HOME/bin/jarvis"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) ARCH="x64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *) die "Unsupported CPU architecture: $ARCH" ;;
esac
case "$OS" in
  linux|darwin) ;;
  mingw*|msys*|cygwin*) die "Native Windows is not supported — run this installer inside WSL2." ;;
  *) die "Unsupported OS: $OS" ;;
esac

NODE_BIN=""
OLLAMA_BIN=""

# ── uninstall ────────────────────────────────────────────────────────────────
do_uninstall() {
  info "Stopping JARVIS…"
  [ -x "$LAUNCHER" ] && "$LAUNCHER" stop >/dev/null 2>&1 || true

  if [ "$OS" = "linux" ] && have systemctl; then
    systemctl --user disable --now jarvis >/dev/null 2>&1 || true
    rm -f "$HOME/.config/systemd/user/jarvis.service"
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi
  if [ "$OS" = "darwin" ]; then
    launchctl unload "$HOME/Library/LaunchAgents/dev.jarvis.daemon.plist" >/dev/null 2>&1 || true
    rm -f "$HOME/Library/LaunchAgents/dev.jarvis.daemon.plist"
  fi
  # only remove the PATH symlink if it points into this install
  if [ -L "$HOME/.local/bin/jarvis" ]; then
    case "$(readlink "$HOME/.local/bin/jarvis")" in
      "$JARVIS_HOME"/*) rm -f "$HOME/.local/bin/jarvis" ;;
    esac
  fi

  rm -rf "$APP_DIR" "$RUNTIME_DIR" "$JARVIS_HOME/bin"
  if [ "$PURGE" -eq 1 ]; then
    rm -rf "$JARVIS_HOME"
    ok "Removed JARVIS completely (including data)."
  else
    ok "Removed JARVIS. Your data was kept in $JARVIS_HOME/data — re-run the installer to restore, or use --purge to wipe it."
  fi
  exit 0
}

banner
[ "$DO_UNINSTALL" -eq 1 ] && do_uninstall
info "Installing into ${C_BOLD}$JARVIS_HOME${C_RESET} ($OS/$ARCH)"
mkdir -p "$JARVIS_HOME"

# ── 1. Node.js >= 22 (portable install, never touches system packages) ──────
node_mirrors() { # mirrors are tried in order; env override first
  local m
  for m in "${JARVIS_NODE_MIRROR:-}" \
           "https://nodejs.org/dist" \
           "https://registry.npmmirror.com/-/binary/node" \
           "https://unofficial-builds.nodejs.org/download/release"; do
    [ -n "$m" ] && printf '%s\n' "$m"
  done
}

install_portable_node() {
  local ext="xz"; have xz || ext="gz"
  local tmp; tmp="$(mktemp -d)"
  info "Downloading portable Node.js (this may take a minute)…"

  # Phase 1 — resolve the newest Node 22 release via the first reachable SHASUMS.
  local tarball="" ver="" line=""
  while IFS= read -r m; do
    line="$(curl -fsSL --retry 2 --max-time 30 "$m/latest-v22.x/SHASUMS256.txt" 2>/dev/null \
      | awk -v want="-$OS-$ARCH.tar.$ext" '$2 ~ want {print $2; exit}')" || true
    if [ -n "$line" ]; then tarball="$line"; break; fi
  done < <(node_mirrors)
  if [ -n "$tarball" ]; then
    ver="$(printf '%s' "$tarball" | sed -E 's/^node-(v[0-9.]+)-.*/\1/')"
  else
    ver="${JARVIS_NODE_VERSION:-v22.22.3}"
    tarball="node-$ver-$OS-$ARCH.tar.$ext"
    warn "Could not resolve the latest Node 22 release; using pinned $ver"
  fi

  # Phase 2 — download the tarball from the first mirror that serves it.
  local downloaded=""
  while IFS= read -r m; do
    info "Trying $m/$ver/$tarball"
    if curl -fSL --retry 3 --retry-delay 2 --progress-bar -o "$tmp/node.tar.$ext" "$m/$ver/$tarball"; then
      downloaded="$m"
      break
    fi
  done < <(node_mirrors)
  [ -n "$downloaded" ] || { rm -rf "$tmp"; die "Node download failed from every mirror — check your network or install Node >= 22 manually."; }

  # Phase 3 — verify the checksum (best effort: not every mirror ships SHASUMS).
  local sum=""
  sum="$(curl -fsSL --retry 2 --max-time 30 "$downloaded/$ver/SHASUMS256.txt" 2>/dev/null \
    | awk -v f="$tarball" '$2==f {print $1; exit}')" || true
  if [ -n "$sum" ]; then
    local actual
    actual="$(cd "$tmp" && (have sha256sum && sha256sum "node.tar.$ext" || shasum -a 256 "node.tar.$ext") | awk '{print $1}')"
    [ "$actual" = "$sum" ] || { rm -rf "$tmp"; die "Node checksum mismatch (expected $sum, got $actual)"; }
    ok "Checksum verified: $tarball"
  else
    warn "Could not fetch checksums — skipped integrity verification"
  fi

  mkdir -p "$RUNTIME_DIR/node"
  tar -xf "$tmp/node.tar.$ext" -C "$RUNTIME_DIR/node" --strip-components=1
  rm -rf "$tmp"
  NODE_BIN="$RUNTIME_DIR/node/bin/node"
  [ -x "$NODE_BIN" ] || die "Node extraction failed"
  ok "Installed Node $("$NODE_BIN" --version) → $RUNTIME_DIR/node"
}

ensure_node() {
  if have node; then
    local major
    major="$(node -p 'process.versions.node.split(".")[0]')"
    if [ "$major" -ge 22 ]; then
      NODE_BIN="$(command -v node)"
      ok "Using system Node $(node --version)"
      return
    fi
    warn "System Node is v$major (too old — JARVIS needs ≥ 22). Installing a portable one."
  fi
  install_portable_node
}

# ── 2. Ollama ────────────────────────────────────────────────────────────────
ollama_running() { curl -sf --max-time 2 "http://localhost:11434/api/version" >/dev/null 2>&1; }

install_ollama() {
  if [ "$OS" = "linux" ]; then
    info "Installing Ollama via the official installer (may ask for your sudo password)…"
    if curl -fsSL https://ollama.com/install.sh | sh; then
      ok "Ollama installed"
    else
      warn "Automated Ollama install failed. Install it manually: https://ollama.com/download/linux"
    fi
  else # macOS
    if have brew; then
      info "Installing Ollama with Homebrew…"
      brew install ollama && ok "Ollama installed" || warn "brew install ollama failed — install from https://ollama.com/download/mac"
    else
      info "Downloading Ollama.app…"
      local tmp; tmp="$(mktemp -d)"
      if curl -fL --retry 3 --retry-delay 2 --progress-bar -o "$tmp/ollama.zip" "https://ollama.com/download/Ollama-darwin.zip"; then
        (cd "$tmp" && unzip -q ollama.zip)
        local dest="/Applications"
        [ -w "$dest" ] || dest="$HOME/Applications"
        mkdir -p "$dest"
        rm -rf "$dest/Ollama.app"
        mv "$tmp/Ollama.app" "$dest/" && ok "Ollama.app installed → $dest"
        open -a "$dest/Ollama.app" 2>/dev/null || true
      else
        warn "Ollama download failed — install it from https://ollama.com/download/mac"
      fi
      rm -rf "$tmp"
    fi
  fi
}

ensure_ollama() {
  if ! have ollama; then
    if confirm "Ollama is not installed. Install it now?"; then
      install_ollama
    else
      warn "Skipping Ollama install. JARVIS needs it — install later and run: ollama pull $MODEL && ollama pull $FAST_MODEL"
    fi
  else
    ok "Ollama found: $(command -v ollama)"
  fi
  export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.ollama/bin"
  have ollama && OLLAMA_BIN="$(command -v ollama)" || true

  if [ -n "$OLLAMA_BIN" ]; then
    if ollama_running; then
      ok "Ollama server is running"
    else
      info "Starting Ollama server…"
      nohup "$OLLAMA_BIN" serve >"$JARVIS_HOME/ollama.log" 2>&1 &
      for _ in $(seq 1 15); do ollama_running && break; sleep 1; done
      if ollama_running; then ok "Ollama server started"; else
        warn "Ollama server did not come up (log: $JARVIS_HOME/ollama.log). Start it with \`ollama serve\`."
      fi
    fi
  fi
}

pull_models() {
  [ -n "$OLLAMA_BIN" ] || { warn "Cannot pull models — Ollama not available."; return; }
  ollama_running || { warn "Cannot pull models — Ollama server not running."; return; }
  for m in "$MODEL" "$FAST_MODEL"; do
    [ -n "$m" ] || continue
    if "$OLLAMA_BIN" list 2>/dev/null | awk '{print $1}' | grep -qx "$m"; then
      ok "Model already installed: $m"
    else
      info "Pulling model $m (multi-GB download — once per model)…"
      "$OLLAMA_BIN" pull "$m" || warn "Pull failed for $m — you can retry later: ollama pull $m"
    fi
  done
}

# ── 3. Fetch JARVIS source ───────────────────────────────────────────────────
fetch_source() {
  rm -rf "$APP_DIR"; mkdir -p "$APP_DIR"
  if [ -n "$LOCAL_SRC" ]; then
    [ "$LOCAL_SRC" = "__SELF__" ] && LOCAL_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    [ -f "$LOCAL_SRC/package.json" ] || die "--local: $LOCAL_SRC does not look like a JARVIS source dir"
    info "Installing from local source: $LOCAL_SRC"
    (cd "$LOCAL_SRC" && tar --exclude=node_modules --exclude=data --exclude=.git -cf - .) | (cd "$APP_DIR" && tar -xf -)
    return
  fi
  if have git; then
    info "Cloning ${JARVIS_REPO%.git} (ref: $JARVIS_REF)…"
    git clone --depth 1 --branch "$JARVIS_REF" "$JARVIS_REPO" "$APP_DIR" \
      || die "git clone failed — check the repo URL / ref (JARVIS_REF=$JARVIS_REF)"
  else
    info "Downloading source tarball…"
    local owner_repo="${JARVIS_REPO#https://github.com/}"; owner_repo="${owner_repo%.git}"
    local tmp; tmp="$(mktemp -d)"
    curl -fSL --retry 3 --retry-delay 2 --progress-bar -o "$tmp/src.tar.gz" \
      "https://codeload.github.com/$owner_repo/tar.gz/refs/heads/$JARVIS_REF" \
      || die "Source download failed for ref $JARVIS_REF"
    tar -xzf "$tmp/src.tar.gz" -C "$tmp"
    local extracted; extracted="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"
    cp -R "$extracted/." "$APP_DIR/"
    rm -rf "$tmp"
  fi
  ok "Source ready → $APP_DIR"
}

install_deps() {
  export PATH="$(dirname "$NODE_BIN"):$PATH"
  info "Installing JS dependencies…"
  (cd "$APP_DIR" && if [ -f package-lock.json ]; then npm ci --omit=dev --no-audit --no-fund; else npm install --omit=dev --no-audit --no-fund; fi) \
    || die "npm install failed"
  ok "Dependencies installed"
}

# ── 4. Config ────────────────────────────────────────────────────────────────
write_config() {
  local cfg="$JARVIS_HOME/config.yaml"
  if [ -f "$cfg" ]; then ok "Keeping existing config: $cfg"; return; fi
  cat > "$cfg" <<EOF
# JARVIS (Ollama Edition) — written by the installer $(date +%F)
daemon:
  host: 0.0.0.0
  port: $PORT
  data_dir: $JARVIS_HOME/data
  log_level: info

ollama:
  base_url: http://localhost:11434
  model: $MODEL
  fast_model: $FAST_MODEL
  temperature: 0.7
  keep_alive: 30m

authority:
  level: 3

observer:
  enabled: false
  paths: []

cron:
  morning: "0 7 * * *"
  evening: "0 20 * * *"
  hourly: "37 * * * *"

personality:
  name: Jarvis
  core_traits: [loyal, efficient, proactive, respectful]
EOF
  ok "Wrote $cfg"
}

# ── 5. Launcher + optional service ───────────────────────────────────────────
write_launcher() {
  mkdir -p "$(dirname "$LAUNCHER")"
  cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# JARVIS launcher — written by the installer
set -e
export JARVIS_HOME="$JARVIS_HOME"
NODE="$NODE_BIN"
[ -x "\$NODE" ] || NODE="\$(command -v node || true)"
[ -n "\$NODE" ] || { echo "JARVIS: Node.js not found" >&2; exit 1; }
exec "\$NODE" --disable-warning=ExperimentalWarning "$APP_DIR/bin/jarvis.js" "\$@"
EOF
  chmod +x "$LAUNCHER"
  # convenience symlink on the default PATH when using the default home
  if [ "$JARVIS_HOME" = "$HOME/.jarvis" ]; then
    mkdir -p "$HOME/.local/bin"
    ln -sf "$LAUNCHER" "$HOME/.local/bin/jarvis"
    ok "Launcher: $HOME/.local/bin/jarvis → $LAUNCHER"
    case ":$PATH:" in
      *":$HOME/.local/bin:"*) ;;
      *) warn "Add this to your shell profile to use \`jarvis\` everywhere:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
    esac
  else
    ok "Launcher: $LAUNCHER"
    warn "Add to PATH:  export PATH=\"$JARVIS_HOME/bin:\$PATH\""
  fi
}

install_service() {
  if [ "$OS" = "linux" ] && have systemctl; then
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$HOME/.config/systemd/user/jarvis.service" <<EOF
[Unit]
Description=JARVIS AI daemon (Ollama Edition)
After=network.target

[Service]
Environment=JARVIS_HOME=$JARVIS_HOME
ExecStart=$LAUNCHER start
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now jarvis \
      && ok "systemd user service enabled (start on login). For boot-time start on a headless box: sudo loginctl enable-linger \$USER" \
      || warn "Could not start the systemd service — start manually with: $LAUNCHER start"
  elif [ "$OS" = "darwin" ]; then
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$HOME/Library/LaunchAgents/dev.jarvis.daemon.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>dev.jarvis.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>$LAUNCHER</string>
    <string>start</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>JARVIS_HOME</key><string>$JARVIS_HOME</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$JARVIS_HOME/data/launchd.log</string>
  <key>StandardErrorPath</key><string>$JARVIS_HOME/data/launchd.log</string>
</dict>
</plist>
EOF
    launchctl unload "$HOME/Library/LaunchAgents/dev.jarvis.daemon.plist" >/dev/null 2>&1 || true
    launchctl load -w "$HOME/Library/LaunchAgents/dev.jarvis.daemon.plist" \
      && ok "launchd agent installed (auto-start at login)" \
      || warn "Could not load the launchd agent — start manually with: $LAUNCHER start"
  else
    warn "No supported service manager found — skipping --service"
  fi
}

# ── 6. Start & verify ────────────────────────────────────────────────────────
start_and_verify() {
  if curl -sf --max-time 2 "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
    ok "JARVIS is already running (started by the service)"
  else
    info "Starting the JARVIS daemon…"
    "$LAUNCHER" start -d
  fi
  local healthy=""
  for _ in $(seq 1 15); do
    if curl -sf --max-time 2 "http://localhost:$PORT/api/health" >/dev/null 2>&1; then healthy=1; break; fi
    sleep 1
  done
  if [ -n "$healthy" ]; then
    ok "JARVIS is up"
    if [ "$DO_OPEN" -eq 1 ]; then
      if [ "$OS" = "darwin" ]; then open "http://localhost:$PORT" 2>/dev/null || true
      elif have xdg-open; then xdg-open "http://localhost:$PORT" 2>/dev/null || true; fi
    fi
  else
    warn "Daemon did not answer on port $PORT yet. Check: $LAUNCHER logs -f"
  fi
}

# ── go ───────────────────────────────────────────────────────────────────────
ensure_node
[ "$DO_OLLAMA" -eq 1 ] && ensure_ollama || true
fetch_source
install_deps
write_config
[ "$DO_MODELS" -eq 1 ] && pull_models || true
write_launcher
[ "$DO_SERVICE" -eq 1 ] && install_service
[ "$DO_START" -eq 1 ] && start_and_verify || true

printf '\n%s%s🎉 JARVIS is installed!%s\n\n' "$C_BOLD" "$C_GREEN" "$C_RESET"
cat <<EOF
  Dashboard    →  http://localhost:$PORT
  Launcher     →  $LAUNCHER   (try: jarvis status / doctor / chat)
  Config       →  $JARVIS_HOME/config.yaml
  Data + DB    →  $JARVIS_HOME/data
  Uninstall    →  bash install.sh --uninstall   (add --purge to wipe data)

  Try in the dashboard:  "remember that I love espresso"  ·  "create a goal to ship v1 by Friday"
EOF
