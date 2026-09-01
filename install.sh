#!/usr/bin/env bash
# =========================================================
#  VoiceOS — simple installer & launcher (macOS / Linux)
#  No dependencies to download: uses Python 3 or Node
#  that you already have. Everything runs locally.
# =========================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

PORT="${PORT:-8080}"
URL="http://localhost:${PORT}"

say()  { printf '\033[1;36mVoiceOS\033[0m  %s\n' "$*"; }
warn() { printf '\033[1;33mVoiceOS\033[0m  %s\n' "$*"; }

echo ""
printf '\033[1;35m'
echo "   ██╗   ██╗ ██████╗ ██╗ ██████╗███████╗ ██████╗ ███████╗"
echo "   ██║   ██║██╔═══██╗██║██╔════╝██╔════╝██╔═══██╗██╔════╝"
echo "   ██║   ██║██║   ██║██║██║     █████╗  ██║   ██║███████╗"
echo "   ╚██╗ ██╔╝██║   ██║██║██║     ██╔══╝  ██║   ██║╚════██║"
echo "    ╚████╔╝ ╚██████╔╝██║╚██████╗███████╗╚██████╔╝███████║"
echo "     ╚═══╝   ╚═════╝ ╚═╝ ╚═════╝╚══════╝ ╚═════╝ ╚══════╝"
printf '\033[0m'
echo "              Say it once, let it go.  ·  v1.0"
echo ""

# --- already running? just open it ------------------------------------------
if command -v curl >/dev/null 2>&1 && curl -sf --max-time 2 "$URL" >/dev/null 2>&1; then
  say "Already running at $URL — opening it."
else
  # --- pick a free port -------------------------------------------------------
  for p in "$PORT" 8081 8082 8083 8084; do
    if ! (command -v curl >/dev/null 2>&1 && curl -sf --max-time 1 "http://localhost:$p" >/dev/null 2>&1); then
      PORT="$p"; URL="http://localhost:${PORT}"; break
    fi
  done

  say "Starting VoiceOS locally at $URL"

  if command -v python3 >/dev/null 2>&1; then
    (python3 -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1 &)
    SERVER="python3"
  elif command -v python >/dev/null 2>&1; then
    (python -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1 &)
    SERVER="python"
  elif command -v node >/dev/null 2>&1; then
    (node -e '
      const http=require("http"),fs=require("fs"),path=require("path");
      const types={".html":"text/html",".css":"text/css",".js":"text/javascript",".png":"image/png",".webmanifest":"application/manifest+json",".json":"application/json"};
      http.createServer((req,res)=>{
        let f=path.join(process.cwd(),decodeURIComponent(req.url.split("?")[0]));
        if(f.endsWith(path.sep))f+="index.html";
        fs.readFile(f,(e,d)=>{if(e){res.writeHead(404);res.end("not found");return;}
          res.writeHead(200,{"Content-Type":types[path.extname(f)]||"application/octet-stream"});res.end(d);});
      }).listen('"$PORT"',"127.0.0.1");' >/dev/null 2>&1 &)
    SERVER="node"
  else
    warn "Neither Python 3 nor Node was found."
    warn "Install either one (free), then re-run this script."
    exit 1
  fi

  sleep 1
  say "Server up ($SERVER).  Press Ctrl+C in the launcher window to stop."
fi

# --- open in the default browser ---------------------------------------------
case "$(uname -s)" in
  Darwin)  open "$URL" ;;
  Linux)   (command -v xdg-open >/dev/null 2>&1 && xdg-open "$URL") || say "Open $URL in your browser." ;;
  *)       say "Open $URL in your browser." ;;
esac

echo ""
say "Tip: in Chrome/Edge you can then choose “Install VoiceOS” (menu bar ⬇ button)"
say "to add it to your Dock like a native app."
echo ""
