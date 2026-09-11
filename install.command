#!/bin/bash
# JARVIS (Ollama Edition) — macOS one-click installer.
# Double-click this file in Finder: Terminal opens and runs the installer.
cd "$(dirname "$0")" || exit 1
bash install.sh "$@"
echo
echo "Press any key to close this window…"
read -r -n 1
