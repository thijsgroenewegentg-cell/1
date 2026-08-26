# Desktop companion 🖥️

A tiny frameless, always-on-top window containing Ultron's **mini mode** (compact orb + voice + chat). Sits in your system tray.

## Setup

```bash
# 1. the main Ultron server must be running (npm start in the project root)
cd desktop
npm install          # downloads Electron (~100 MB, once)
npm start
```

- **Alt+Shift+U** — show/hide the orb, from anywhere
- **Tray icon** — show/hide, quit
- The window loads `http://localhost:3000/?mini=1` — the compact UI with the orb, mic, and composer

## Notes

- Scaffolded, not battle-tested on every OS — tweaks to `transparent`/`frame` may be needed on Linux/Wayland.
- The tray icon expects `desktop/icon.png` (copy `public/icon-512.png` there, resized to ~64px).
- Want it to start with your OS? Add `npm start` (in this folder) to your startup programs.
