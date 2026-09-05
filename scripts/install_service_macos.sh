#!/usr/bin/env bash
# /scripts/install_service_macos.sh
# Install JARVIS as a macOS LaunchAgent so it starts when you log in.
#
#   bash scripts/install_service_macos.sh          # install + start
#   bash scripts/install_service_macos.sh --remove # uninstall
#
# Note: for voice mode, grant Terminal (or the Python binary) microphone access
# under System Settings → Privacy & Security → Microphone.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.jarvis.assistant"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
PYTHON="${PROJECT_DIR}/.venv/bin/python"
EXEC_ARGS="${JARVIS_ARGS:---web}"

red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
info()  { printf "\033[36m%s\033[0m\n" "$*"; }

if [[ "${1:-}" == "--remove" || "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || launchctl unload "${PLIST}" 2>/dev/null || true
  rm -f "${PLIST}"
  green "JARVIS LaunchAgent removed."
  exit 0
fi

if [[ ! -x "${PYTHON}" ]]; then
  red "No virtualenv at ${PYTHON} — run ./setup.sh first."
  exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${PROJECT_DIR}/logs"

# Build the <string> entries for the arguments.
ARG_XML=""
for arg in ${EXEC_ARGS}; do
  ARG_XML="${ARG_XML}
    <string>${arg}</string>"
done

cat > "${PLIST}" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>${PROJECT_DIR}/main.py</string>${ARG_XML}
  </array>
  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>${PROJECT_DIR}/logs/service.log</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/logs/service.log</string>
</dict>
</plist>
PLISTEOF

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST}" 2>/dev/null || launchctl load "${PLIST}"

green "Installed ${PLIST}"
info  "Status : launchctl list | grep ${LABEL}"
info  "Logs   : tail -f ${PROJECT_DIR}/logs/service.log"
info  "Stop   : launchctl bootout gui/$(id -u)/${LABEL}"
