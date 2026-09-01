# Changelog

All notable changes to VoiceOS are documented here.
This project follows [Semantic Versioning](https://semver.org/).

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

[1.0.0]: https://github.com/thijsgroenewegentg-cell/1/releases/tag/v1.0.0
