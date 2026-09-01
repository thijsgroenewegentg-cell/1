# VoiceOS Desktop (Electron shell)

Wraps the web app in a real desktop window: **frameless, transparent,
always-on-top "notch"** pinned under the menu bar, toggled with a **global
hotkey** (`Ctrl/⌘+Space`, override with `VOICEOS_HOTKEY`).

## Run in dev

```bash
cd desktop
npm install     # downloads Electron (~100 MB, one time, free)
npm start
```

## Build installers

Run these **on the target OS** (macOS `.dmg` signing/notarization requires a
Mac; Windows NSIS works on Mac/Linux too):

```bash
npm run dist:mac   # → dist/VoiceOS-1.0.0.dmg
npm run dist:win   # → dist/VoiceOS Setup 1.0.0.exe
npm run dist       # both
```

Unsigned builds install fine; on macOS the first launch may need
System Settings → Privacy & Security → “Open Anyway”.
For distribution-grade releases, add your Apple Developer ID /
EV code-signing certificate — electron-builder picks them up automatically.

> Note: OS-level dictation into *any* app (the spec's "universal input")
> additionally requires native accessibility permissions and a keystroke
> bridge (e.g. nut.js) — that's the next milestone; this shell delivers the
> overlay window, hotkey, and installable packaging.
