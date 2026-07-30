# J.A.R.V.I.S - Just A Rather Very Intelligent System
### Ollama-Powered Local AI Assistant

> "At your service, Sir. Always."

A fully local, private, Tony Stark-style JARVIS built on **Ollama**. No cloud APIs. No data leaving your machine. Full voice, memory, tools, and personality.

![Local](https://img.shields.io/badge/100%25%20Local-Private-green) ![Ollama](https://img.shields.io/badge/Brain-Ollama-blue) ![Python](https://img.shields.io/badge/Python-3.10%2B-yellow)

---

## ✨ Features

**🧠 Brain**
- Ollama as the core (supports `llama3.1:8b`, `qwen2.5:7b`, `mistral`, `gemma2`, etc.)
- Custom `jarvis` Modelfile with personality baked-in
- Function calling / Tool use
- Streaming responses

**🎙️ Voice**
- Wake word: "Jarvis"
- STT: Faster-Whisper (local, offline) + fallback to SpeechRecognition
- TTS: Edge-TTS (Jarvis-like voice) + pyttsx3 offline fallback

**🛠️ Tools JARVIS can use autonomously:**
- `get_time` - Date, time, day
- `get_system_info` - CPU, RAM, OS, battery
- `search_web` - DuckDuckGo search
- `get_weather` - Weather for any city (wttr.in)
- `remember` / `recall` - Long-term memory
- `file_manager` - Read/write/list files in allowed workspace
- `execute_code` / `shell` - Run Python & shell commands safely
- `control_system` - Volume, open apps/websites
- `timer` / `reminder`

**💾 Memory**
- Short-term: conversation history
- Long-term: JSON file `data/long_term_memory.json`
- Vector memory ready (extendable to ChromaDB)

**🖥️ Interfaces**
1. **CLI** - `python cli.py` - Talk in terminal
2. **Web UI** - Holographic JARVIS interface at `http://localhost:8000`
3. **Voice Loop** - Hands-free `python -m jarvis.app --voice`
4. **Desktop App Python** - Native `customtkinter` + tray + arc reactor `python desktop/python/main.py`
5. **Desktop Electron** - Slick holographic native app `cd desktop/electron && npm start` (global hotkey `Ctrl+Shift+J`)
6. **WebView Desktop** - Lightweight native wrapper `python desktop/python/webview_app.py`

---

## 🚀 Quick Start

### 0. Prerequisites
- Python 3.10+
- [Ollama installed](https://ollama.com)

### 1. Install & Setup
```bash
git clone this repo
cd jarvis-ollama
./setup.sh
```

Or manually:
```bash
pip install -r requirements.txt
# Start Ollama (in another terminal)
ollama serve

# Pull a capable model (pick one)
ollama pull llama3.1:8b
ollama pull qwen2.5:7b    # best tool calling
ollama pull mistral-nemo  # fast alternative

# Create JARVIS personality model
ollama create jarvis -f Modelfile

# Optional: for web search & voice
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env to set model, voice, etc.
```

### 3. Run

**Terminal Chat:**
```bash
python cli.py
python cli.py --model jarvis
```

**Voice Mode (hands-free):**
```bash
python -m jarvis.app --voice
# or
python cli.py --voice --wake-word
```

**Web UI (Like Stark's lab):**
```bash
python web/server.py
# or
uvicorn web.server:app --reload
# Open http://localhost:8000
```

**Python Desktop (Native, Tray, Arc Reactor):**
```bash
pip install customtkinter pystray pillow --break-system-packages
python desktop/python/main.py
# or
python cli.py --desktop
# or
./run.sh desktop
# Close = minimize to tray. Real JARVIS stays alive.
```

**WebView Desktop (Lightweight native, no browser):**
```bash
pip install pywebview --break-system-packages
python desktop/python/webview_app.py
# or
./run.sh webview
```

**Electron Desktop (Slick, Hotkey Ctrl+Shift+J):**
```bash
cd desktop/electron
npm install
npm start              # dev + auto-start Python backend
npm run build          # build installer (Win/Mac/Linux)
# Global hotkey: Ctrl+Shift+J to show/hide like Spotlight
```

**All Desktops:**
```bash
python desktop/launch.py          # auto-picks best
./run.sh auto                     # same
./run.sh electron                 # force electron
```

**Docker (Ollama + App):**
```bash
docker-compose up -d
# Ollama at :11434, Web UI at :8000
```

---

## ⚙️ Configuration (.env)

```env
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=jarvis
# or llama3.1:8b, qwen2.5:7b, etc
VOICE_ENABLED=false
WAKE_WORD=jarvis
TTS_ENGINE=edge       # edge or pyttsx3
STT_ENGINE=faster-whisper # faster-whisper or google
MEMORY_FILE=data/long_term_memory.json
WORKSPACE_DIR=./workspace
```

---

## 🧬 Project Structure

```
.
├── Modelfile              # Ollama personality definition
├── docker-compose.yml
├── requirements.txt
├── setup.sh / run.sh
├── cli.py                 # Main entry (cli, web, desktop flags)
├── jarvis/
│   ├── config.py
│   ├── personality.py
│   ├── brain.py           # Ollama client + tool loop
│   ├── memory.py
│   ├── tools/             # 8 tool modules
│   ├── voice/             # STT/TTS
│   └── app.py
├── web/                   # Holographic UI
│   ├── server.py (FastAPI)
│   ├── index.html, style.css, app.js
│   └── jarvis-hero.png
└── desktop/               # 🖥️ NEW: Native Desktop Apps
    ├── icon.png
    ├── launch.py          # Auto-launcher (best mode)
    ├── python/
    │   ├── main.py        # Native CustomTkinter + tray + reactor
    │   ├── webview_app.py # PyWebView lightweight native
    │   └── requirements.txt
    └── electron/
        ├── main.js        # Electron main (spawns backend, tray, hotkey)
        ├── preload.js
        ├── package.json
        └── assets/icon.png
```

---

## 🎨 Customizing Personality

Edit `jarvis/personality.py` or `Modelfile`. Default prompt:

> You are J.A.R.V.I.S. You are witty, British, loyal, concise. You address user as Sir unless told otherwise. You have full access to system tools. You are helpful but have dry humor.

Want FRIDAY instead? Change the voice and system prompt.

---

## 🛠️ Adding New Tools

1. Create a function in `jarvis/tools/`
2. Add its schema to `TOOLS_SCHEMA` in `jarvis/tools/__init__.py`
3. Register it in `TOOL_MAP`
4. JARVIS will automatically discover it via Ollama tool calling.

Example:
```python
def brew_coffee():
    return "Coffee brewing... Sir, it's 3 AM. Are we building another suit?"

# In tools/__init__.py
{
  "type": "function",
  "function": {
    "name": "brew_coffee",
    "description": "Brew coffee",
    "parameters": {"type": "object", "properties": {}}
  }
}
```

---

## 🧠 Which Model to Use?

| Model | Tool Calling | Speed | Personality | Recommend |
|-------|-------------|-------|-------------|-----------|
| `qwen2.5:7b` | ★★★★★ | Fast | Great | **BEST** |
| `llama3.1:8b` | ★★★★☆ | Medium | Great | Good |
| `mistral-nemo:12b` | ★★★★☆ | Fast | Good | Good |
| `gemma2:9b` | ★★★☆☆ | Fast | Good | Fast |

For best JARVIS experience: `qwen2.5:7b` or `llama3.1:8b`

```bash
ollama pull qwen2.5:7b
ollama create jarvis -f Modelfile
```

---

## 🔒 Privacy

- 100% offline after model download
- No API keys required
- Memory stays in `data/` folder
- No telemetry

## Voice Not Working?
```bash
# Linux deps
sudo apt install portaudio19-dev espeak -y

# Mac
brew install portaudio
```

## Roadmap
- [x] Electron desktop app ✅ NEW
- [x] Python native desktop + tray ✅ NEW
- [x] Global hotkey Ctrl+Shift+J ✅ NEW
- [ ] Vision (camera + llava model)
- [ ] Home Assistant / IoT integration
- [ ] Proactive notifications
- [ ] Custom wake-word model

---

Built with ❤️ for Stark fans. "Sometimes you gotta run before you can walk."

> Configure Ollama -> Run `cli.py` -> Say "Jarvis, what time is it?" -> You're Iron Man.
