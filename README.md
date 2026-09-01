<div align="center">
<img src="icons/icon-192.png" width="88" alt="VoiceOS icon" />

# VoiceOS

**Say it once, let it go.**
A voice-first operating layer for **Windows & Linux**: speech → intent → JSON → action.
Dictation and agent modes in a floating, notch-style interface. 100% local, 100% free.

</div>

---

## ⚡ Install (Windows & Linux)

### Option A — Zero-install web app (works everywhere)

Download the **Source code (zip)** from the
[**latest release**](https://github.com/thijsgroenewegentg-cell/1/releases/latest), unzip, then:

**Windows** — double-click `install.bat` · **Linux** — `./install.sh`

**Windows** — double-click `install.bat` · **Linux** — `./install.sh`

No downloads, no accounts — the launcher uses the Python 3 or Node already on
your machine, serves VoiceOS locally, and opens your browser.
Then click **⬇ Install** in the menu bar to pin it as an app — works offline.

### Option B — Native desktop app (voice bar + global hotkey)

Two ways to get ready-made Windows / Linux installers
(`Setup.exe`, portable `.exe`, `.AppImage`, `.deb`):

1. **CI builds them for you** (one-time setup, ~1 minute): see
   [`ci-templates/README.md`](ci-templates/README.md) — copy two files into
   `.github/workflows/`, push, and every future `v*` tag automatically attaches
   signed-ready installers to the release. **Free** for public repos.
2. **Build locally**: `cd desktop && npm install && npm run dist` (Windows
   installer cross-builds from Linux too).

---

## 🎙️ What it does

| Mode | Example | Result |
| --- | --- | --- |
| **Workflow** ⭐ | “Send John the latest project deck” | finds file → composes → attaches → sends, steps ticking live in the notch |
| **Briefing** ⭐ | “Morning briefing” | one card: next meeting, unread mail, reminders, open tasks |
| **Dictation** | “Take a note: um the rollout uh went fine” | fillers stripped, typed into Notes |
| **Email** | “Send email to John about the meeting” | draft → **SEND** card → Sent |
| **Calendar** | “Schedule meeting with Sarah next week” | event on calendar |
| **Messages** | “Reply to Maya” | reads thread → captures reply → sends |
| **Files** | “Find last year’s tax returns” | search card → opens Files at match |
| **Tasks** ⭐ | “Create task: review the launch plan” | lands in Tasks (feeds the briefing) |
| **Notes** ⭐ | “Search notes for checklist” | result card → Notes |
| **Learning** ⭐ | “I meant Sarah, not Sara” | alias remembered for future commands |
| **Reminders** | “Remind me to call Joan tomorrow at 9am” | time-smart reminder |
| **Search / Apps** | “Search web for focus music” · “Open Notes” | web card / window control |

⭐ = new in v1.1 · Ambiguity is handled (“Send message” → *“To who?”* with
tap-to-pick contacts); passwords & mass deletes are always refused.

## ⚙️ Settings

First-run onboarding, then the ⚙️ menu: **voice · speaking speed ·
confirmation level** (always / big stuff only / never) · **verbosity** ·
privacy (local-only) · reset & wipe. Notes, events, tasks, threads, learned
aliases, and history persist across restarts.

## 🖥️ Build desktop installers yourself

```bash
cd desktop
npm install          # one-time, downloads Electron (free)
npm run dist:win     # → dist/ NSIS setup + portable exe
npm run dist:linux   # → dist/ AppImage + deb
npm run dist         # all targets
```

Every `v*` tag also triggers [`ci-templates/release.yml`](ci-templates/release.yml) (one-step enable — see `ci-templates/README.md`),
which builds all four installer variants on GitHub runners (Windows + Linux)
and attaches them to the release automatically.

## 🔒 Privacy

No servers, no telemetry, no API keys. Audio and transcripts never leave your
device. Speech-to-text and text-to-speech use the engines built into your OS
and browser. All data lives in local storage.

## 🧪 Quality

```bash
npm test   # 101 checks: headless parser/logic (63) + real-DOM UI suite in jsdom (38)
```

CI ([`ci-templates/ci.yml`](ci-templates/ci.yml)) runs both suites
on Windows **and** Linux on every push.

## Repo layout

```
index.html · styles.css · app.js   the app (zero-dependency vanilla JS)
manifest.webmanifest · sw.js        PWA: installable + offline
install.sh · install.bat            one-step launchers (Linux / Windows)
icons/                              app icons
desktop/                            Electron shell: voice-bar window + hotkey
ci-templates/                       CI + release-installer workflows (one-step enable)
tests/smoke.js                      63-check headless test drive
tests/domtest.js                    38-check real-DOM suite (jsdom)
```

## Roadmap

- [ ] Universal dictation into any app via desktop shell (accessibility bridge)
- [ ] Real Gmail/Calendar/Slack via OAuth
- [ ] On-device Whisper STT option
- [ ] User-defined macros (“when I say X, do A then B”)
- [ ] Code-signed installers (Windows EV / self-cert)
