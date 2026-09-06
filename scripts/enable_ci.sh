#!/usr/bin/env bash
# /scripts/enable_ci.sh
# =============================================================================
# Switch on continuous integration.
#
# GitHub only runs workflows that live in .github/workflows/, and it refuses
# pushes from an app that has not been granted the `workflows` permission —
# which is why this repository keeps the file at .github/ci.yml and asks you
# to move it. You have the permission; run this once:
#
#     bash scripts/enable_ci.sh
#
# From then on every push runs ruff, mypy, the unit suite and the offline
# smoke suite on Linux, macOS and Windows across Python 3.9 to 3.12, measures
# coverage and builds a wheel. No models are downloaded and no secrets are
# needed: tests/mock_ollama.py stands in for the LLM.
# =============================================================================
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."

SOURCE=".github/ci.yml"
TARGET=".github/workflows/ci.yml"

if [[ -f "$TARGET" ]]; then
  echo "  CI is already enabled at $TARGET"
  exit 0
fi

if [[ ! -f "$SOURCE" ]]; then
  echo "  Cannot find $SOURCE — nothing to enable." >&2
  exit 1
fi

mkdir -p .github/workflows

if git rev-parse --git-dir > /dev/null 2>&1; then
  git mv "$SOURCE" "$TARGET"
else
  mv "$SOURCE" "$TARGET"
fi

echo "  Moved $SOURCE → $TARGET"
echo
echo "  Now commit and push it yourself:"
echo "      git commit -m 'Enable CI' $TARGET"
echo "      git push"
echo
echo "  The first run takes about four minutes. Watch it under the Actions tab."
