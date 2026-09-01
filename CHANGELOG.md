# Changelog

All notable changes to VoiceOS are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [1.3.0] — 2026-09-01

Replica-class landing + full Dutch language support. 🇳🇱

### Added
- **Nederlands, end to end** — ONBOARDING → settings → chips → spoken replies → confirmation buttons → **the command parser itself**: “Stuur een e-mail naar John over de vergadering”, “Zoek de belastingaangifte van vorig jaar”, “Herinner me eraan Joan morgen om 9 uur te bellen”, “Maak taak: …”, “Open Notities”, “Ja”/“Nee” voice-confirmation. Dutch fillers scrubbed from dictation (“eh”, “zeg maar”, “weet je”), Dutch date vocabulary (“overmorgen”, “volgende maandag”, “om 19 uur”), Dutch-calendar formatting, nl-NL mic + nl voices
- **Landing page rebuilt to the reference site's structure** — badge → hero → app-tile marquee → point/cursor → 1×/4×/10× productivity bars → voice-to-action chips → rotating search → agent → **privacy toggles** → wall of love → CTA. All original copy/assets (no borrowed brand icons or text), animated productivity bars filling on scroll, ticker marquee, lens float
- **Site language toggle** (🇬🇧/🇳🇱, auto-detected from browser, persisted) — hero demo scenes and rotator follow the active language
- **15 Dutch parser tests + 12 landing/structure/i18n tests + 6 app-side Dutch journey tests** → **146 checks total**

### Fixed
- Regex alternation branch without `.test()` (always-truthy) — caught by the suite mid-build; exactly why the suite exists

## [1.2.0] — 2026-09-01

Presentation & craft release.

### Added
- **Product landing page** (`index.html`) — hero with generated key art, looping live-demo card in the notch mock, scrolling command ticker, feature grid, architecture sample, 3-path install, footer
- **Sound design** — synthesized WebAudio cues (listen / work / card / send / success / cancel), zero audio assets, honors the 🔊 toggle
- **Typewriter dictation card** — watch the cleaned transcription type itself (~≤0.9s regardless of length)
- **Landing test suite** (`tests/landingtest.js`, 11 checks) — structure, links, privacy claims, live demo
- MIT `LICENSE` file

### Changed
- The app moved to `app.html`; `/` is now the landing page (menu-bar logo links back)
- PWA `start_url` → `app.html` (installed icon opens the app, not the site)
- `npm test` runs all three suites: **114 checks** (63 headless + 11 landing + 40 DOM)

## [1.1.1] — 2026-09-01

Professional-review polish pass. Verified with a real DOM-level test suite.

### Added
- **DOM test suite** (`tests/domtest.js`, 38 checks) — drives the real page in jsdom: clicks chips & confirm buttons, types commands, asserts notch cards, windows, onboarding, settings, persistence
- **Polish**: click anywhere on a window raises it; `Esc` dismisses overlays/cards; composer placeholder rotates through example commands
- `npm test` now runs both suites (101 checks total); jsdom added as devDependency

### Fixed
- Stray “on this Mac” copy → platform-neutral
- DOM-test harness: `$$` replacement injection (harness bug)

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

[1.3.0]: https://github.com/thijsgroenewegentg-cell/1/releases/tag/v1.3.0
[1.2.0]: https://github.com/thijsgroenewegentg-cell/1/releases/tag/v1.2.0
[1.1.1]: https://github.com/thijsgroenewegentg-cell/1/releases/tag/v1.1.1
[1.1.0]: https://github.com/thijsgroenewegentg-cell/1/releases/tag/v1.1.0
[1.0.0]: https://github.com/thijsgroenewegentg-cell/1/releases/tag/v1.0.0
