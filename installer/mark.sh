#!/usr/bin/env bash
set -e
ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo 'MARK is not installed yet. Run: python3 installer/install.py' >&2
  exit 1
fi
exec "$PY" "$ROOT/main.py" "$@"
