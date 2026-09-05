#!/usr/bin/env bash
# /install.command
# Double-clickable installer for macOS: opens in Terminal and runs install.sh.
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
bash ./install.sh "$@"
status=$?
echo
if [ "$status" -eq 0 ]; then
  echo "  Installation finished. You can close this window."
else
  echo "  The installer stopped with errors (exit $status). Scroll up for details."
fi
echo "  Press Enter to close…"
read -r _
exit $status
