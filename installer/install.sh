#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3 and run this installer again." >&2
  exit 1
fi

exec "$PYTHON" "$ROOT/installer/install.py" "$@"
