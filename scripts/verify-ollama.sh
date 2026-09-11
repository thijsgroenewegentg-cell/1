#!/usr/bin/env bash
#
# Verifies that jarvis works with Ollama — and shows what breaks without the
# patch in patches/0001-ollama-context-window.patch.
#
# It checks out jarvis at a pinned commit, drives it through its own provider
# factory, LLMManager and tool definitions, and runs the same check twice:
# before the patch and after it. The server it talks to is a stand-in that
# reproduces Ollama's behaviour, including the 4096-token default window and
# the silent front-truncation that deletes the system prompt.
#
# Usage:
#   bash scripts/verify-ollama.sh
#
# To smoke-test your OWN Ollama instead of the stand-in:
#   OLLAMA_BASE_URL=http://localhost:11434 OLLAMA_MODEL=qwen2.5:3b \
#     bash scripts/verify-ollama.sh --real-only
#
set -euo pipefail

JARVIS_REPO="${JARVIS_REPO:-https://github.com/vierisid/jarvis}"
JARVIS_REF="${JARVIS_REF:-9f8738df7184a9e3e5f9163ffffdb999824e72d4}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/.workdir"
PATCH="$ROOT/patches/0001-ollama-context-window.patch"
STANDIN_PORT="${OLLAMA_STANDIN_PORT:-11500}"
REAL_ONLY=0
[ "${1:-}" = "--real-only" ] && REAL_ONLY=1

command -v bun >/dev/null 2>&1 || { echo "bun is required (https://bun.sh)"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "git is required"; exit 1; }
mkdir -p "$WORK"

standin_pid=""
cleanup() {
  [ -n "$standin_pid" ] && kill "$standin_pid" 2>/dev/null || true
}
trap cleanup EXIT

# ── One jarvis checkout at the pinned commit ─────────────────────────────────
DIR="$WORK/jarvis"
if [ ! -d "$DIR/.git" ]; then
  echo "cloning jarvis @ ${JARVIS_REF:0:12} into $DIR"
  rm -rf "$DIR"
  git init -q "$DIR"
  git -C "$DIR" remote add origin "$JARVIS_REPO"
  git -C "$DIR" fetch -q --depth 1 origin "$JARVIS_REF"
  git -C "$DIR" checkout -q FETCH_HEAD
fi
if [ ! -d "$DIR/node_modules" ]; then
  echo "installing dependencies (once)"
  (cd "$DIR" && bun install --ignore-scripts >/dev/null 2>&1)
fi
cp "$ROOT/verify/live-check.ts" "$DIR/verify-live-check.ts"

reset_to_pristine() {
  git -C "$DIR" checkout -q -- src/llm/ollama.ts src/llm/ollama.test.ts 2>/dev/null || true
}

if [ "$REAL_ONLY" -eq 1 ]; then
  echo "== smoke test against a real Ollama at ${OLLAMA_BASE_URL:-http://localhost:11434} =="
  reset_to_pristine
  git -C "$DIR" apply --whitespace=nowarn "$PATCH"
  ( cd "$DIR" && OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11434}" \
      OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}" bun run verify-live-check.ts )
  exit $?
fi

# ── Start the Ollama stand-in ────────────────────────────────────────────────
REQUEST_LOG="$WORK/standin-requests.jsonl"
SERVER_LOG="$WORK/standin-server.log"
: > "$REQUEST_LOG"
echo "== starting Ollama stand-in on port $STANDIN_PORT =="
OLLAMA_STANDIN_PORT="$STANDIN_PORT" OLLAMA_STANDIN_LOG="$REQUEST_LOG" \
  bun run "$ROOT/verify/ollama-stand-in.ts" > "$SERVER_LOG" 2>&1 &
standin_pid=$!
for _ in $(seq 1 50); do
  curl -fsS "http://127.0.0.1:$STANDIN_PORT/api/tags" >/dev/null 2>&1 && break
  sleep 0.2
done
curl -fsS "http://127.0.0.1:$STANDIN_PORT/api/tags" >/dev/null 2>&1 \
  || { echo "stand-in failed to start; log:"; cat "$SERVER_LOG"; exit 1; }

run_check() {
  local label="$1"
  : > "$REQUEST_LOG"   # each run gets a clean request log
  ( cd "$DIR" && OLLAMA_BASE_URL="http://127.0.0.1:$STANDIN_PORT" \
      OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}" \
      OLLAMA_STANDIN_LOG="$REQUEST_LOG" bun run verify-live-check.ts )
  local rc=$?
  echo "[$label] exit=$rc  server-side request log:"
  sed 's/^/    /' "$REQUEST_LOG"
  return $rc
}

echo
echo "== BEFORE — jarvis at the pinned commit, unmodified =="
reset_to_pristine
set +e
run_check before
before_rc=$?
set -e

echo
echo "== patch under test =="
sed -n '1,12p' "$PATCH" | sed 's/^/  /'
echo "  ... $(grep -c '^[+-][^+-]' "$PATCH") changed lines across $(grep -c '^diff --git' "$PATCH") files"

echo
echo "== AFTER — with patches/0001-ollama-context-window.patch =="
reset_to_pristine
git -C "$DIR" apply --whitespace=nowarn "$PATCH"
echo "  repo's own ollama unit tests:"
(cd "$DIR" && bun test src/llm/ollama.test.ts 2>&1 | tail -4 | sed 's/^/  /')
set +e
run_check after
after_rc=$?
set -e

echo
echo "== stand-in server log (Ollama's own view) =="
sed 's/^/  /' "$SERVER_LOG"

echo
echo "== result =="
printf '  before: %s (exit %s)\n' "$([ "$before_rc" -eq 0 ] && echo PASS || echo FAIL)" "$before_rc"
printf '  after : %s (exit %s)\n' "$([ "$after_rc" -eq 0 ] && echo PASS || echo FAIL)" "$after_rc"

if [ "$before_rc" -eq 0 ]; then
  echo "  NOTE: the unpatched provider passed too — the payload may be under the window."
fi
if [ "$after_rc" -ne 0 ]; then
  echo "  FAILED: jarvis still does not survive Ollama's context window."
  exit 1
fi
if [ "$before_rc" -eq 0 ]; then
  echo "  OK (patch is a no-op on this machine's stand-in settings)."
else
  echo "  OK: unpatched jarvis loses its system prompt; patched jarvis keeps it."
fi
