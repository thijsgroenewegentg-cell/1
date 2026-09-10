# MARK — local Ollama desktop assistant

This repository is an Ollama port of [FatihMakes/Mark-LII](https://github.com/FatihMakes/Mark-LII) (the linked repository currently redirects to Mark-LIII).

MARK is a PyQt6 desktop assistant with local tool calling, screen/webcam vision, microphone input, long-term memory, computer controls, file processing, browser controls, plugins and a HUD. It does **not** need a Gemini or any other cloud API key.

## Quick start

1. Install [Ollama](https://ollama.com).
2. Pull the recommended models:

   ```bash
   ollama pull qwen2.5:14b
   ollama pull qwen2.5vl:7b
   ```

   `qwen2.5:14b` is a good default for a 16 GB RX 9070 XT. If you want lower memory use, use `llama3.1:8b` or `qwen2.5:7b-instruct`.
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

## Voice

Ollama returns text, so MARK uses `edge-tts` for natural spoken replies without an API key. It needs internet access for synthesis. If Edge TTS is unavailable, MARK tries the local `pyttsx3` system voice. Microphone transcription uses `faster-whisper` and downloads its model once on first voice use; typed commands work without a microphone.

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

## Project layout

- `main.py` — Ollama conversation loop, VAD/Whisper microphone and tool dispatch
- `core/llm_client.py` — Ollama HTTP client, tool schema conversion and vision support
- `core/tts.py` — Edge TTS plus offline fallback
- `core/stt.py` — faster-whisper transcription
- `ui.py` — PyQt6 HUD and settings panels
- `actions/` — auto-discovered built-in tools
- `plugins/` — drop-in tools with a `PLUGIN` dictionary and `run()` function
- `installer/` — cross-platform installer, launchers and Windows Inno Setup definition
- `memory/` — persistent local memory and settings

Runtime settings are stored in `config/api_keys.json`; despite the historical filename, this Ollama build stores no secrets there. Personal memory and other runtime data are ignored by Git.
