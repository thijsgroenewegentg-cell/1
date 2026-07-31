# J.A.R.V.I.S Desktop App

Two native desktop implementations - pick your poison, Sir.

## Option 1: Python Native (Recommended, no Node needed)

A fully native window with arc reactor animation, system tray, direct Ollama brain.

**Look:**
- CustomTkinter modern dark UI (falls back to Tkinter)
- Animated arc reactor
- System tray - stays alive like real JARVIS
- Voice toggle
- Model switcher

**Install & Run:**

```bash
# Install deps
pip install customtkinter pillow pystray --break-system-packages
# Or
pip install -r python/requirements.txt --break-system-packages

# Run
python desktop/python/main.py
# or
python -m desktop.python.main

# Tray: Close window -> minimizes to tray, keeps running
```

**Features:**
- ✅ Native, no Electron bloat (20MB vs 200MB)
- ✅ Direct brain integration
- ✅ Tray with always-on
- ✅ Hotkey ready
- ✅ Voice TTS via existing JARVIS engine

---

## Option 2: Electron Desktop (Slick, web-based)

Wraps the holographic web UI (`web/index.html`) into a native Electron window with:

- Frameless holographic UI
- System tray
- Global shortcut `Ctrl+Shift+J` (or `Cmd+Shift+J` on Mac) to show/hide like Spotlight
- Auto-starts Python backend + checks Ollama
- Installer builds for Win/Mac/Linux

**Install & Run:**

```bash
cd desktop/electron

# Install Node deps
npm install

# Run in dev (needs python backend running OR it will auto-start)
npm run dev
# or
npm start

# Backend auto: Electron will try to start `python web/server.py`
# So you need python deps installed:
cd ../..
pip install -r requirements.txt
```

**Build installers:**

```bash
cd desktop/electron

# All platforms (from your OS)
npm run build

# Platform specific
npm run build:win   # .exe installer
npm run build:mac   # .dmg
npm run build:linux # AppImage

# Output: desktop/electron/dist/
```

**Electron Details:**
- `main.js` - Main process, spawns Python backend, tray, shortcuts
- `preload.js` - Secure bridge to renderer
- Loads `http://localhost:8000` (FastAPI web UI)
- If backend not running, starts `web/server.py` automatically

---

## Icons

`icon.png` - Generated JARVIS arc reactor icon. Used for both apps.
Replace with your own `assets/icon.png` (512x512) for custom build.

To convert to .ico/.icns:
```bash
# Linux
convert icon.png -define icon:auto-resize=256,128,64,48,32,16 icon.ico

# Mac
# Use iconutil or online converter
```

---

## Tray Behavior (Both Apps)

Real JARVIS doesn't quit when you close the window, Sir.

- **Close (X)** -> Minimize to tray, keep running in background
- **Tray Menu**:
  - Show JARVIS
  - Voice ON/OFF
  - Ollama status check
  - Open workspace
  - Quit

So you can `Ctrl+Shift+J` anytime.

---

## Run Modes Summary

| Mode | Command | UI | Size | Needs |
|------|---------|----|------|-------|
| CLI | `python cli.py` | Terminal | Tiny | Python |
| Web | `python web/server.py` | Browser | Small | Python |
| Desktop Python | `python desktop/python/main.py` | Native Tk | ~30MB | Python |
| Desktop Electron | `npm start` in `desktop/electron` | Holographic | ~200MB | Node + Python |

**Best combo:** Run `ollama serve` in background + Electron app. You get JARVIS on `Ctrl+Shift+J` anywhere.

---

## Hotkeys

- `Ctrl+Shift+J` - Global show/hide (Electron)
- `Enter` - Send message
- `Esc` - Minimize to tray (Python app planned)

---

## Troubleshooting

**CustomTkinter not found:**
```bash
pip install customtkinter --break-system-packages
```

**pystray fails on Linux:**
```bash
sudo apt install python3-gi gir1.2-appindicator3-0.1
# or
pip install pystray --break-system-packages
```

**Electron can't start Python:**
- Make sure `python` or `python3` in PATH
- Run manually first: `python web/server.py` then `npm start`

**Ollama offline:**
- Run `ollama serve` in separate terminal
- Check `http://localhost:11434` shows Ollama

---

At your service, Sir. Suit up.
