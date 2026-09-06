# /CHANGELOG.md

# Changes

## 1.2.0 — launch

The first release meant for other people's machines.

### New

- **A voice-first interface.** The browser console is built around a sphere of
  3,200 points that breathes when idle, follows your voice through the real
  audio analyser while the microphone is open, turns violet while thinking and
  blue while speaking. Rendering adapts to the machine: frame times are
  measured and detail is dropped before frames are.
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
- **`docs/CONFIGURATION.md`**: all 185 settings with their real defaults,
  generated from the code so they cannot drift.

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
