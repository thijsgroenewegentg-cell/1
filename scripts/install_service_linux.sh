#!/usr/bin/env bash
# /scripts/install_service_linux.sh
# Install JARVIS as a per-user systemd service so it starts with your session.
#
#   bash scripts/install_service_linux.sh          # install + start
#   bash scripts/install_service_linux.sh --remove # uninstall
#
# The service runs the web interface by default (works headlessly). Change
# EXEC_ARGS below to "--voice" if the machine has a microphone attached.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="jarvis"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_FILE="${UNIT_DIR}/${SERVICE_NAME}.service"
PYTHON="${PROJECT_DIR}/.venv/bin/python"
EXEC_ARGS="${JARVIS_ARGS:---web}"

red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
info()  { printf "\033[36m%s\033[0m\n" "$*"; }

if ! command -v systemctl >/dev/null 2>&1; then
  red "systemd not found. Add this to your desktop's autostart instead:"
  echo "  ${PYTHON} ${PROJECT_DIR}/main.py ${EXEC_ARGS}"
  exit 1
fi

if [[ "${1:-}" == "--remove" || "${1:-}" == "--uninstall" ]]; then
  systemctl --user disable --now "${SERVICE_NAME}.service" 2>/dev/null || true
  rm -f "${UNIT_FILE}"
  systemctl --user daemon-reload
  green "JARVIS service removed."
  exit 0
fi

if [[ ! -x "${PYTHON}" ]]; then
  red "No virtualenv at ${PYTHON} — run ./setup.sh first."
  exit 1
fi

mkdir -p "${UNIT_DIR}"
cat > "${UNIT_FILE}" <<UNIT
[Unit]
Description=JARVIS local AI assistant
Documentation=file://${PROJECT_DIR}/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON} ${PROJECT_DIR}/main.py ${EXEC_ARGS}
Environment=PYTHONUNBUFFERED=1
# Ollama must be reachable; give it a moment on a cold boot.
ExecStartPre=/bin/sh -c 'for i in 1 2 3 4 5 6 7 8 9 10; do curl -sf http://localhost:11434/api/tags >/dev/null && exit 0; sleep 3; done; exit 0'
Restart=on-failure
RestartSec=5
StandardOutput=append:${PROJECT_DIR}/logs/service.log
StandardError=append:${PROJECT_DIR}/logs/service.log

[Install]
WantedBy=default.target
UNIT

mkdir -p "${PROJECT_DIR}/logs"
systemctl --user daemon-reload
systemctl --user enable --now "${SERVICE_NAME}.service"

green "Installed ${UNIT_FILE}"
info  "Status : systemctl --user status ${SERVICE_NAME}"
info  "Logs   : journalctl --user -u ${SERVICE_NAME} -f"
info  "Stop   : systemctl --user stop ${SERVICE_NAME}"
info  "Boot without login: sudo loginctl enable-linger \"${USER}\""
