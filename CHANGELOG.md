# /CHANGELOG.md

# Changes

## 1.2.0 — launch

The first release meant for other people's machines.

### New

- **A voice-first interface.** The browser console is built around a sphere of
  3,200 points that breathes when idle, follows your voice through the real
  audio analyser while the microphone is open, and keeps to white with red as
  the only accent — hard white while listening, red while speaking, and a
  visibly dimmer rest when no language model is reachable. Rendering adapts
  to the machine: frame times are measured and detail is dropped before
  frames are, and `prefers-reduced-motion` calms the sphere to near-still.
- **It shows its working.** The brain publishes which module it chose and which
  tool it ran; the interface draws that as a live trace with timings, and
  lights the module's tile as it happens.
- **A command palette** over every tool, and a keyboard overlay (`?`) so no
  shortcut is hidden knowledge.
- **`python main.py --app`** serves the interface and opens it in a window. The
  page is a progressive web app, so it installs to the dock with its own icon.
  The installer adds desktop entries that use it.
- **A Blender module**: render frames and animations, run bpy scripts
  headlessly, inspect a `.blend`, build a scene from a description, and export
  to glTF, OBJ, FBX, STL, PLY, USD or Alembic. Works with the application or
  with `pip install bpy`.
- **An audit trail.** Everything that needed permission — allowed, confirmed,
  declined or blocked — is recorded, kept across restarts, and readable by
  asking or with `/audit`.
- **`install.py --everything`**: audio libraries, every model, every capability,
  and a closing diagnosis of whatever is still missing.
- **`docs/CONFIGURATION.md`**: all 238 settings with their real defaults,
  generated from the code so they cannot drift.
- **It speaks your language.** Replies follow the language you write in —
  Dutch, English and more — with `assistant.language` as a fixed override.
  The help text and the console's starter questions follow it too.
- **Instant acknowledgment.** A slower task (search, files, code) gets one
  short line in your language the moment it starts, so the silence never
  feels like deafness. Instant actions stay quiet.
- **Unlimited sessions, even offline.** Once the window fills, oldest turns
  fold into a running briefing instead of falling off the deque. A dropped
  socket or a phone refresh restores the visible conversation from that
  window.
- **QR pairing.** The status panel shows a scannable code (and a copyable
  link) so a phone on the same network opens the console without typing a
  URL.
- **Live theming and names.** A hue slider or hex recolours the HUD and the
  speaking orb; your name and the assistant's name save from the status panel.
- **Clipboard intelligence.** Copy text in the console and a floating panel
  offers translate / summarise / explain / fix.
- **Proactive check-ins.** Morning, afternoon and evening — a one-line
  open-task count, held during quiet hours.
- **Topic watches.** "watch the news about X"; new headlines are mentioned
  once a day.
- **Hardware alerts.** CPU and RAM crossing 90% get a spoken/web ping, with
  hysteresis so a machine sitting on the line does not nag.
- **YouTube.** "play lofi on youtube" opens a search (or a video id); pause /
  next / mute / fullscreen go to a YouTube window when one is on screen.
- **Steam and Epic updates.** Best-effort: Steam's downloads list, or
  `legendary` for Epic when that CLI is installed.
- **Telegram.** Optional `telegram.bot_token` / `chat_id`; without them the
  tool explains how to set a BotFather bot instead of pretending to send.
- **Flight lookup.** Search-only Google Flights URL — JARVIS does not book.
- **Audio devices.** List and switch sinks via `pactl` / SwitchAudioSource.
- **Screen watch.** "watch my screen" glances on a timer; no webcam required.
  "look at the webcam" explains itself when there is no camera.
- **Cinema console.** After boot the orb owns the field. Chrome (tiles,
  chips, extra buttons, the side rail) waits until you move, type, or open
  a panel; the mic stays. Escape returns to the quiet field.
- **Whisper boot.** A point of light grows into the orb in about three
  seconds. No overlay title card, no inbound swarm, no whiteout.
- **Cinema polish.** The dock stays at the bottom (no jump when chrome
  returns). The greeting is a pulse, not a caption. `/boot` is debug-only.
  On a phone the transcript stays visible.
- **Chips vs briefing.** Suggestion chips hide while a caption is on
  screen, so they cannot stripe through the morning brief.
- **A local journal and a day recap.** Every turn is logged on this machine;
  "what did I do today" or "recap my day" sums up what got done and what
  still dangles.
- **Topic dossiers.** "fill me in on X" assembles a compact brief from the
  journal, facts, notes and open threads.
- **Bulk actions with a preview.** "tick off everything in the bike project",
  "delete every todo tagged X", "snooze all reminders until tomorrow" —
  anything beyond a few rows shows a preview first.
- **A local vault.** Secrets such as passwords live only in a small obfuscated
  file on this machine — never in notes, logs or the cloud.
- **Self-healing retries.** After a failed action JARVIS suggests the closest
  matching file or folder; "try that again" repeats the attempt.
- **Macros, rules and open threads.** "when I say X, do Y" teaches a fixed
  command; commitments are kept as threads he nudges until they are closed.
- **A console that reads.** Replies render lists, links and code with copy
  buttons; a one-block answer types itself out; clickable starter questions
  sit next to the input, and on a phone the conversation stays visible as a
  scrollable transcript instead of disappearing.

### Fixed

Bugs found by hammering the assistant rather than by reading it:

- `calculate 9**9**9` froze the whole thing — the evaluator bounded code but
  not arithmetic.
- Every database write leaked a file descriptor; ChromaDB clients were never
  closed. A long session would eventually be unable to open a file.
- `convert -5 celsius to fahrenheit` answered 41°F: the number pattern dropped
  minus signs, and read `1e308` as `308`.
- Scripts that read `/etc/passwd` or `~/.ssh/id_rsa` ran without confirmation;
  only writes were being risk-assessed.
- Writes outside `security.allowed_roots` went ahead unchallenged — the guard
  graded them "ask first" and every caller checked only "blocked".
- Interrupting a reply reported that Ollama was offline.
- `web_ui.enabled`, `vision.max_tokens`, `vision.temperature` and
  `vision.fallback_models` were advertised in the config and read by nobody.
- Saving the configuration deleted every comment in it.
- A mistyped slash command was sent to the model as if it were speech.

### Notes for upgraders

- The shipped `config.yaml` is deliberately quiet: the web interface is off
  until you ask for it with `--web`, `--app`, or `web_ui.enabled: true`.
  `python install.py --everything` switches everything on in one go.
- Continuous integration is written but inert until you run
  `bash scripts/enable_ci.sh` — GitHub will not accept workflow files from an
  app without the `workflows` permission.
