#!/bin/bash
# VoiceOS — double-click launcher for macOS.
# (Finder/Terminal will execute this when double-clicked.)
cd "$(dirname "$0")"
chmod +x ./install.sh 2>/dev/null
exec ./install.sh
