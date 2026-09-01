# Changelog

All notable changes to VoiceOS are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [1.1.0] — 2026-09-01

Windows & Linux focus + workflows, learning, briefing, tasks — with **real installers built by CI**.

### Added
- **Multi-step workflow cards** — the spec's flagship example: *“Send John the latest project deck”* → found → compose → attach → send, with a live checklist that ticks off in the notch as each step executes
- **Contact learning** — *“I meant Sarah, not Sara”* persists an alias and applies it to all future commands
- **Morning briefing** — *“Morning briefing” / “Start my day”* → one card: next meeting, unread mail, reminders, open tasks
- **Tasks app** — new dock app + `create task` / `show my tasks`; open tasks feed the briefing
- **Notes search** — *“Search notes for checklist”* → result card that opens Notes
- **CI** — tests run on every push, on **Windows and Linux** runners
- **Automated installer builds** — pushing a version tag builds and attaches **Windows (NSIS + portable .exe)** and **Linux (AppImage + .deb)** installers to the GitHub release automatically
- **22 new tests** (63 total): workflows, learning, briefing, tasks, notes search, never-confirm workflow auto-run

### Changed
- **Platform pivot: Windows & Linux only.** Dropped the macOS installer; desktop shell hotkey is `Ctrl+Space`; installers are Linux-native (`install.sh`, `install.bat`).
- Search cards now open the *right* app (Mail / Files / Notes / Tasks) per result.

## [1.0.0] — 2026-09-01

## [1.0.0] — 2026-09-01

First full release. 🎉

### Added
- **Notch UI** — idle / listening / processing / card states with animated waveform, confirmations, results, and search cards
- **Dictation mode** — filler-word removal ("um", "uh", "like"), auto casing & punctuation, types into Notes
- **Agent mode** — email, calendar, messages, files, web search, reminders, app control against a live simulated desktop (Mail, Calendar, Messages, Notes, Files with draggable windows and a dock)
- **Intent engine** — full intent taxonomy (dictation / app action / workflow / search / reminder) emitting the spec's JSON schema every turn, viewable in the `{ }` inspector
- **Confirmation system** — levels *always / big stuff only / never*; high-consequence actions (send email, book meeting) confirm, safety refusals for passwords and mass deletes
- **Ambiguity recovery** — missing recipients prompt tap-to-pick contacts; unclear input asks clarifying options
- **Context awareness** — contact resolution (John/Sarah/Maya/Maria/Alex), time intelligence ("tomorrow at 9am", "next week", "friday"), active-app highlighting
- **Voice I/O** — Web Speech API dictation (Ctrl+Space), spoken replies via speech synthesis
- **Onboarding & settings** — first-run setup, voice / speed / confirmations / verbosity, reset & wipe
- **Persistence** — notes, events, messages, reminders and history survive restarts (local storage)
- **PWA** — installable (Add to Dock / Start Menu), fully offline via service worker, generated app icons
- **Simple installers** — `install.command` (macOS), `install.bat` (Windows), `install.sh` (Linux); no downloads, uses the Python 3 or Node you already have
- **Electron desktop shell** (`desktop/`) — frameless always-on-top notch window + global hotkey; `npm run dist` builds `.dmg` / `.exe` installers on your machine
- **Test suite** — 40 headless checks over the parser, confirmation levels, persistence, and the full pipeline (`npm test`)

### Privacy
100% local: no servers, no telemetry, no API keys. Audio and transcripts never leave the device.

[1.1.0]: https://github.com/thijsgroenewegentg-cell/1/releases/tag/v1.1.0
[1.0.0]: https://github.com/thijsgroenewegentg-cell/1/releases/tag/v1.0.0
