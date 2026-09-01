# VoiceOS Desktop (Electron shell) — Windows & Linux

Wraps the web app in a real desktop window: **frameless, transparent,
always-on-top voice bar** floating top-center, toggled with a **global
hotkey** (`Ctrl+Space`, override with `VOICEOS_HOTKEY`).

## Installers (no build needed)

CI builds them on every release — grab from
[Releases](https://github.com/thijsgroenewegentg-cell/1/releases/latest):

| Platform | Assets | Notes |
| --- | --- | --- |
| Windows | `*-Setup-*.exe`, `portable *.exe` | One-click NSIS installer; portable runs without installing |
| Linux | `*.AppImage`, `*.deb` | AppImage: `chmod +x` and run; deb: `sudo dpkg -i` |

Unsigned by default: Windows may show a SmartScreen prompt → “More info → Run
anyway”. AppImages may need `chmod +x`.

## Run in dev

```bash
cd desktop
npm install     # downloads Electron (~100 MB, one time, free)
npm start
```

## Build installers locally

```bash
npm run dist:win     # Windows: NSIS installer + portable exe (works from Linux too!)
npm run dist:linux   # Linux: AppImage + deb
npm run dist         # all four
```

electron-builder's NSIS target cross-builds fine from Linux — no Windows
machine needed. For signed builds, drop a code-signing cert in and
electron-builder picks it up (`CSC_LINK` / `CSC_KEY_PASSWORD` env vars).

> Note: OS-level dictation into *any* app (the spec's "universal input")
> additionally requires an accessibility/keystroke bridge (e.g. nut.js) —
> that's the next milestone; this shell delivers the overlay window, hotkey,
> and installable packaging.
