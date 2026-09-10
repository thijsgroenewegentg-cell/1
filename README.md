# MARK — local Ollama desktop assistant

This repository is an Ollama port of [FatihMakes/Mark-LII](https://github.com/FatihMakes/Mark-LII) (the linked repository currently redirects to Mark-LIII).

MARK is a PyQt6 desktop assistant with local tool calling, screen/webcam vision, microphone input, long-term memory, computer controls, file processing, browser controls, plugins and a HUD. It does **not** need a Gemini or any other cloud API key.

## Quick start

1. Install [Ollama](https://ollama.com).
2. Pull the recommended models:

   ```bash
   ollama pull qwen2.5:14b
   ollama pull qwen2.5vl:7b
   # Optional fast router/reply model for dual response mode
   ollama pull qwen2.5:7b-instruct
   ```

   `qwen2.5:14b` is a good quality default for a 16 GB RX 9070 XT. MARK now uses `qwen2.5:7b-instruct` for short turns when it is already pulled, and keeps the 14B model for complex questions, Blender work, code and analysis. If you prefer one model, set `response_profile` to `quality` in `config/api_keys.json`.
3. Run the installer to create the private Python environment and desktop shortcut:

   ```bash
   # Windows PowerShell
   powershell -ExecutionPolicy Bypass -File installer/install.ps1

   # Linux/macOS
   python3 installer/install.py
   ```

   For a manual setup without the shortcut, use `python -m venv .venv` and `pip install -r requirements.txt`.
4. Start Ollama if the desktop app did not start it automatically:

   ```bash
   ollama serve
   ```
5. Launch MARK:

   ```bash
   python main.py
   ```

The first-run panel asks for the Ollama URL, chat model and vision model. The defaults are `http://localhost:11434`, `qwen2.5:14b` and `qwen2.5vl:7b`.

### Building the Windows installer

Install [Inno Setup 6](https://jrsoftware.org/isinfo.php), open `installer/MARK.iss`, and build it. The generated installer copies MARK to a user-writable directory, creates a desktop/Start Menu icon, creates `.venv`, and installs the dependencies. Linux and macOS use the cross-platform `installer/install.py` script and create a desktop launcher or application bundle.

## Desktop UI and remote dashboard

MARK opens a PyQt6 HUD with chat input, microphone controls, activity logs, file drop, camera preview, system metrics and settings. The installer creates a desktop shortcut for it.

The **Remote Control** button in the HUD starts the optional LAN dashboard on demand. Scan the QR code with a phone, or open the displayed address and enter the six-character key. The dashboard can send commands, stream a phone microphone, upload files and show MARK's replies and status in real time. It uses a one-time pairing key and authenticated session tokens; the dashboard does not open a listening port until Remote Control is pressed.

The remote dashboard needs the optional packages in `requirements.txt` (`fastapi`, `uvicorn`, `cryptography`, `python-multipart` and `qrcode[pil]`). If they were skipped during installation, run `pip install -r requirements.txt` and restart MARK. The dashboard is intended for a trusted local network; use the HTTPS certificate files in `config/certs/` if you need encrypted transport on the LAN.

The main HUD uses a black, low-distraction particle-orb visualizer: a depth-shaded dotted sphere, restrained blue/indigo glow and compact instrument readouts. The orb keeps the existing microphone/TTS amplitude response, listening/thinking/speaking/muted states, confirmation overlays and accessibility controls, while the surrounding panels remain available for chat, logs and settings. The header status strip reports Ollama, microphone, Edge TTS, vision, Blender, optional ComfyUI and Internet degradation states. **◈ CONTROL CENTER** opens dedicated Task Plan, Timeline, Memory, Workflows and Blender tabs with safe pause/continue/rollback, forget, workflow editing/replay, checkpoints and render/undo controls. Click or focus the orb and press Space/Enter to interrupt a response; when idle, the same control toggles the microphone. During MARK speech, the strip explicitly shows that voice input can barge in and stop generation.

### Included plugins

The `plugins/` folder includes safe examples:

- `git_helper.py` — read-only repository status, diff summary, log, branches, remotes and root lookup. It has a fixed Git argument allowlist and never commits, resets, checks out, pushes or pulls.
- `project_helper.py` — fixed, shell-free project status, test, package-check and Docker-status helpers. It cannot accept arbitrary commands, install packages or mutate containers.
- `blender_control.py` — adapter for the existing BlenderMCP add-on. MARK launches the fixed `uvx blender-mcp` stdio server, discovers its tools, blocks arbitrary Python/command tools, and confirmation-gates scene changes and asset operations.
- `local_calendar.py` — private local `calendar.ics` events with add, list, today, find and remove operations. It defaults to `Documents/MARK/calendar.ics`; set `MARK_CALENDAR_FILE` to use another local file. Add/remove are confirmation-gated.
- `email_client.py` — optional IMAP/SMTP inbox, search, read and send support. It never stores credentials in the repository, requires `MARK_EMAIL_IMAP_HOST`, `MARK_EMAIL_SMTP_HOST`, `MARK_EMAIL_USERNAME` and `MARK_EMAIL_PASSWORD` in the launch environment, and puts every send behind MARK's on-screen confirmation gate.
- `media_control.py` — open/search Spotify, show now-playing/status data, control playback, volume, shuffle and repeat using native player tools available on Windows, macOS or Linux. It uses no Spotify API credential.
- `comfyui_image.py` — loopback-only ComfyUI image generation with a bounded standard workflow, optional explicitly selected local API workflow, queue/history/status, confirmation-gated GPU jobs and safe image downloads under the user home folder.

Plugins are discovered on the next launch and can be enabled or disabled from **⚙ → PLUGINS**. The new **INSTALL LOCAL PLUGIN** button and `core/plugin_installer.py` accept only a local Python file, inspect its literal metadata and syntax without importing it, show a source preview and its SHA-256, require a human confirmation, copy it into `plugins/`, and record the approved hash in the ignored local `config/plugin_trust.json`. Built-in plugins are covered by the committed `core/trusted_plugins.json` manifest. Trust enforcement is enabled by default and can be deliberately disabled from the plugin manager for local development; changes take effect after restart. No arbitrary URL download or silent third-party install is performed.

For a terminal install, use the same approval flow:

```bash
python -m core.plugin_installer /path/to/plugin.py
```

Restart MARK after installation so the self-describing plugin loader can discover the new tool. Direct files dropped into `plugins/` are blocked by default until installed or explicitly allowed in development mode. **⚙ → PLUGIN SETTINGS** now provides local calendar path/default-duration fields and non-secret email host/port/username fields; the email password remains environment-only.

### ComfyUI image generation

Install and run ComfyUI locally, normally on `127.0.0.1:8188`. Open **⚙ → PLUGIN SETTINGS → COMFYUI — LOCAL IMAGE GENERATION**, click **TEST COMFYUI CONNECTION**, and enter the exact checkpoint filename from ComfyUI's `models/checkpoints` directory. Then ask MARK to generate an image. MARK uses a standard-node workflow by default, waits for the result, and saves supported images under `Documents/MARK/comfyui`. GPU jobs and downloads always show a confirmation card first. Advanced users may select an API-format workflow JSON under their home folder; MARK still rejects remote workflow URLs and non-loopback servers.

The upstream MARK repository only provides the template, so these tools are included directly in this Ollama build rather than downloaded from an unverified plugin marketplace.

### Existing Blender MCP integration

MARK uses the existing **Blender MCP** add-on; it does not require another Blender add-on. In Blender's 3D View sidebar, set the port to `9876` and click **Connect to MCP server**. In MARK's **PLUGIN SETTINGS → BLENDER — EXISTING MCP SERVER**, keep host `127.0.0.1`, port `9876`, and launcher `uvx`. MARK starts the fixed `uvx blender-mcp` stdio server on the first Blender request, discovers the tools, blocks arbitrary Python/command execution, and asks for confirmation before mutations. The `blender/mark_bridge.py` file is an optional older MARK bridge and is not needed for the BlenderMCP add-on shown in the panel.

## Voice

Ollama returns text, so MARK uses `edge-tts` for natural spoken replies without an API key. It needs internet access for synthesis. If Edge TTS is unavailable, MARK tries the local `pyttsx3` system voice. Microphone transcription uses `faster-whisper` and downloads its model once on first voice use; typed commands work without a microphone.

If MARK does not hear you, open **⚙ → AUDIO DEVICES**, select the actual microphone, press **TEST MICROPHONE**, or use **RECORD 5s + PLAYBACK** for an end-to-end check, then press **APPLY**. The diagnostics panel shows the live level, peak, frame count, PortAudio device/index, sample rate, channel count and stream status. Applying now reconnects the live microphone stream. Also check that the HUD button says **MICROPHONE ACTIVE**, and that your operating system has granted MARK microphone permission. The Activity Log will show the PortAudio/device error when the stream cannot open.

## AMD GPU

Ollama uses the GPU when the installed Ollama/driver combination supports it. The assistant sends `num_gpu: 99`, which asks Ollama to offload all possible layers and safely falls back to CPU when needed. Verify GPU use with:

```bash
ollama ps
```

## Local-only boundaries

- Chat, tool calls, vision, memory and action-specific model helpers go to Ollama.
- Web search fetches DuckDuckGo results and asks Ollama to summarise them locally.
- No Gemini package or cloud API key is required.
- Edge TTS and web search are optional internet connections; switch `tts_engine` to `system` in `config/api_keys.json` for offline speech.
- Computer access is broad but policy-gated: read-only inspection can be immediate, while file writes/deletes, generated code, app automation, network/credential actions, Blender mutations and administrative operations require an on-screen human confirmation. The only exception is the fixed, read-only DuckDuckGo search helper. There is no unrestricted shell tool and no silent arbitrary command execution.

### Review-first self-improvement

Ask MARK to use `self_update` with `action: review`, a list of repository-relative Python files and an instruction. It reads the requested files, creates a detached Git worktree, asks Ollama for a unified patch, applies and tests it in isolation using fixed compile/pytest commands, displays the full diff, and then asks for confirmation. Only the exact reviewed patch can be applied to the live checkout; conflicts, unrequested files, failed tests and untracked/dirty requested files are refused. The workflow never accepts a shell command from the model.

## Project layout

- `main.py` — Ollama conversation loop, VAD/Whisper microphone and tool dispatch
- `core/llm_client.py` — Ollama HTTP client, tool schema conversion and vision support
- `core/tts.py` — Edge TTS plus offline fallback
- `core/stt.py` — faster-whisper transcription
- `ui.py` — PyQt6 HUD and settings panels
- `dashboard/` — authenticated LAN dashboard and phone relay
- `blender/` — Blender MCP integration notes and optional legacy MARK bridge
- `actions/` — auto-discovered built-in tools, including the review-first `self_update` workflow
- `plugins/` — drop-in tools with a `PLUGIN` dictionary and `run()` function
- `installer/` — cross-platform installer, launchers and Windows Inno Setup definition
- `memory/` — persistent local memory and settings

Runtime settings are stored in `config/api_keys.json`; despite the historical filename, this Ollama build stores no secrets there. Personal memory and other runtime data are ignored by Git.
