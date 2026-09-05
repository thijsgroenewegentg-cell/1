# JARVIS — a free, fully local personal AI assistant

> "Just A Rather Very Intelligent System." Runs on your machine. Costs nothing.
> No API keys, no subscriptions, no cloud.

A voice-driven assistant with a local LLM brain, persistent memory, real
computer control, web research, productivity tools, a coding assistant and file
intelligence — built entirely from free and open-source parts.

```
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
```

---

## What it does

| Capability | How | Cost |
|---|---|---|
| Reasoning / conversation | **Ollama** + Llama 3.2 / Mistral, running locally | free |
| Speech to text | **faster-whisper**, local | free |
| Text to speech | **edge-tts** (Microsoft neural voices) | free, no key |
| Wake word | **Porcupine** free tier *or* keyless local Whisper | free |
| Long-term memory | **ChromaDB** vector store + local embeddings | free |
| Web search | **DuckDuckGo** (`ddgs`) | free, no key |
| Weather | **wttr.in** | free, no key |
| News | public **RSS** feeds | free |
| Encyclopaedia | **Wikipedia** REST API | free |
| Database | **SQLite** | free |
| Desktop control | **pyautogui / psutil** + native OS commands | free |

Six capability modules, ~70 callable tools:

* **system_control** — open/close apps, screenshots, CPU/RAM/disk/battery, volume, lock screen, clipboard, keyboard & mouse automation, shell commands (guarded), time/date
* **web_search** — DuckDuckGo search, page scraping + summarising, weather, news, Wikipedia, geocoding
* **productivity** — todos, reminders with real notifications, timers, stopwatch, notes, daily briefing
* **code_assistant** — write, explain, debug, refactor, test, save and *run* code in a sandbox
* **file_manager** — find files by name/content, organise folders, summarise PDF/DOCX/TXT, analyse CSVs, find duplicates, disk usage
* **smart_assistant** — Q&A with web RAG, safe maths, unit & currency conversion, translation, summarising, creative writing

---

## Quick start

```bash
git clone <your-repo>            # or unzip the project
cd jarvis
bash setup.sh                    # installs everything, pulls the model, self-tests
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python main.py                   # voice mode if a mic exists, otherwise text
```

Then say **"Jarvis"**, wait for the chime, and talk. Or just type.

---

## Requirements

* Python 3.9+ (3.11 recommended)
* ~6 GB free disk (LLM + Whisper models)
* 8 GB RAM minimum for `llama3.2`; 16 GB is comfortable
* A microphone and speakers for voice mode (optional — text mode always works)

---

## Setup: Windows

1. **Python** — install from [python.org](https://www.python.org/downloads/windows/), ticking *"Add python.exe to PATH"*.
2. **Ollama** — download the installer from [ollama.com/download](https://ollama.com/download), run it, then in PowerShell:
   ```powershell
   ollama pull llama3.2
   ollama pull nomic-embed-text
   ```
   Ollama runs as a background service on Windows; check it with `curl http://localhost:11434/api/tags`.
3. **FFmpeg** (for speech playback):
   ```powershell
   winget install Gyan.FFmpeg
   ```
4. **JARVIS**:
   ```powershell
   cd path\to\jarvis
   python -m venv .venv
   .venv\Scripts\activate
   pip install --upgrade pip
   pip install -r requirements.txt
   python main.py --test
   python main.py
   ```

*Windows notes*
* Volume control uses `pycaw` (installed automatically).
* If `pyaudio`/`sounddevice` fails to build, install the
  [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/), or run text-only mode with `python main.py --cli`.
* Run PowerShell as a normal user; JARVIS never needs admin rights.

---

## Setup: macOS

```bash
# 1. Prerequisites
brew install python@3.11 portaudio ffmpeg
brew install ollama            # or download the app from ollama.com

# 2. Start Ollama and get the models
ollama serve &                 # skip if you installed the .app (it auto-starts)
ollama pull llama3.2
ollama pull nomic-embed-text

# 3. JARVIS
cd ~/jarvis
bash setup.sh                  # or do it manually:
#   python3 -m venv .venv && source .venv/bin/activate
#   pip install -r requirements.txt

source .venv/bin/activate
python main.py --test
python main.py
```

*macOS notes*
* The first run asks for **Microphone** permission, and **Accessibility** +
  **Screen Recording** permission if you use typing/clicking/screenshots:
  *System Settings → Privacy & Security*. Grant them to Terminal (or your IDE).
* Apple Silicon runs Whisper and Ollama with hardware acceleration out of the box.

---

## Setup: Linux

```bash
# 1. System packages (Debian/Ubuntu)
sudo apt update
sudo apt install -y python3 python3-venv python3-dev portaudio19-dev ffmpeg libsndfile1

#    Fedora:  sudo dnf install python3-devel portaudio-devel ffmpeg
#    Arch:    sudo pacman -S python portaudio ffmpeg

# 2. Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &                 # systemd usually starts it for you
ollama pull llama3.2
ollama pull nomic-embed-text

# 3. JARVIS
cd ~/jarvis
bash setup.sh
source .venv/bin/activate
python main.py --test
python main.py
```

*Linux notes*
* Screenshots need one of `gnome-screenshot`, `scrot`, `spectacle`, `grim` or `pyautogui`.
* Volume control uses `pactl`, `wpctl` or `amixer` — whichever you have.
* Screen lock uses `loginctl`, `xdg-screensaver`, `i3lock` or `swaylock`.
* Wayland restricts synthetic keyboard/mouse input; everything else works normally.

---

## Running it

```bash
python main.py                     # auto: voice if audio works, else text
python main.py --cli               # text interface only
python main.py --voice             # force voice mode
python main.py --say "what's my CPU doing"   # one-shot, then exit
python main.py --test              # component self-test
python main.py --debug             # verbose logging
python tests/test_smoke.py         # full offline test suite (no model needed)
```

### Text commands

| Command | Does |
|---|---|
| `help` | command reference |
| `status` | LLM / memory / modules / voice health |
| `tools` | every tool JARVIS can call |
| `memory` | memory statistics |
| `remember <text>` | store a fact forever |
| `recall <query>` | semantic search of memory |
| `forget <text>` | delete matching memories |
| `voice` | jump into voice mode |
| `mute` / `unmute` | speak replies in text mode |
| `clear`, `config`, `exit` | as expected |

### Things to say

```
"Jarvis, what time is it"
"Open Chrome"
"Take a screenshot"
"How's the weather in Amsterdam"
"What's in the news"
"Search for the latest on fusion power"
"Remind me to call mom at 5pm"
"Set a timer for 10 minutes"
"Add buy milk to my todo list"
"Give me my daily briefing"
"Write a python script that renames files by date"
"Run this code"
"Find all PDFs on my desktop"
"Summarize ~/Documents/contract.pdf"
"Organize my downloads folder"
"Convert 10 miles to kilometres"
"Translate good morning into Japanese"
"Remember that I hate meetings before 10am"
```

---

## How it works

```
   microphone ──► wake word ──► faster-whisper ──► transcript
                 (porcupine or                        │
                  local whisper)                      ▼
                                            ┌───────────────────┐
   long-term memory (ChromaDB) ────────────►│   core/brain.py   │
   short-term window (last 20 turns) ──────►│                   │
                                            │  1. classify      │
                                            │  2. ReAct loop:   │
                                            │     reason ─►act  │
                                            │        ▲     │    │
                                            │        └observe   │
                                            │  3. compose reply │
                                            └─────────┬─────────┘
                                                      │ tool calls
        ┌───────────────┬───────────────┬─────────────┼─────────────┬──────────────┐
   system_control   web_search    productivity   code_assistant  file_manager  smart_assistant
                                                      │
                                                      ▼
                                     edge-tts ──► speaker (interruptible)
```

1. **Intent classification** — the LLM picks one module using a structured JSON
   prompt; a keyword router provides a prior and a fallback.
2. **ReAct** — up to 4 iterations of `{"thought", "action", "params", "answer"}`
   JSON. Each action dispatches to a real tool; the observation feeds the next
   step.
3. **Composition** — the observations are turned into a short, spoken-friendly
   reply in JARVIS's voice.
4. **Memory** — every turn is written to SQLite; durable facts are mined in the
   background and embedded into ChromaDB for future recall.

### Project layout

```
jarvis/
├── main.py                  entry point (voice / CLI / one-shot / self-test)
├── config.yaml              every setting
├── requirements.txt
├── setup.sh                 one-click installer + self-test
├── core/
│   ├── brain.py             Ollama client, intent router, ReAct loop, persona
│   ├── memory.py            short-term window + ChromaDB long-term memory
│   └── config.py            YAML config with defaults and env overrides
├── interfaces/
│   ├── voice.py             wake word, VAD, faster-whisper STT, edge-tts, barge-in
│   └── cli.py               rich terminal UI
├── modules/
│   ├── base.py              tool decorator, dispatch, offline routing
│   ├── system_control.py    apps, stats, volume, input, shell
│   ├── web_search.py        DuckDuckGo, scraping, weather, news, Wikipedia
│   ├── productivity.py      todos, reminders, timers, notes, briefing
│   ├── code_assistant.py    write / explain / debug / run / save code
│   ├── file_manager.py      search, organise, summarise, CSV analysis
│   └── smart_assistant.py   Q&A + RAG, maths, conversions, translation, writing
├── utils/
│   ├── logger.py            coloured console + rotating file logs
│   ├── helpers.py           shared utilities
│   └── security.py          risk assessment + confirmation gate
├── tests/
│   ├── test_smoke.py        61-check end-to-end suite
│   └── mock_ollama.py       scripted LLM server for testing
└── data/                    SQLite DB, ChromaDB, notes, code, screenshots, TTS cache
```

---

## Configuration

Everything lives in `config.yaml`. Highlights:

```yaml
user:
  name: "Thijs"          # what JARVIS calls you
  title: "sir"           # or "ma'am", "boss", or "" for none

llm:
  model: "llama3.2"      # any Ollama model: mistral, llama3, phi3, qwen2.5…
  temperature: 0.7
  router_model: ""       # optionally a smaller model for intent classification

voice:
  wake_word: "jarvis"
  engine: "auto"                 # porcupine | whisper | auto
  porcupine_access_key: ""       # optional free key from console.picovoice.ai
  interrupt: true                # talk over JARVIS to stop him
  stt: { model: "base.en" }      # tiny.en is faster, small.en is sharper
  tts: { voice: "en-GB-RyanNeural", rate: "+8%" }

modules:                 # switch any capability off; nothing else breaks
  system_control: true
  web_search: true
  ...

security:
  confirm_dangerous: true   # ask before rm, sudo, kill, moving files…
  allow_shell: true
```

Any setting can be overridden by an environment variable:
`JARVIS_LLM__MODEL=mistral python main.py`.

### Choosing a model

| Model | RAM | Feel |
|---|---|---|
| `llama3.2` (3B) | 8 GB | fast, great default |
| `mistral` (7B) | 16 GB | more capable reasoning |
| `llama3.1` (8B) | 16 GB | strongest tool use |
| `phi3` (3.8B) | 8 GB | tiny and quick |
| `qwen2.5:7b` | 16 GB | excellent at code |

```bash
ollama pull mistral
# then set llm.model: "mistral" in config.yaml
```

### Voices

```bash
python -c "import asyncio, edge_tts; print('\n'.join(v['ShortName'] for v in asyncio.run(edge_tts.list_voices()) if v['Locale'].startswith('en')))"
```
Good JARVIS candidates: `en-GB-RyanNeural`, `en-GB-ThomasNeural`,
`en-US-GuyNeural`, `en-AU-WilliamNeural`.

---

## Wake word without any account

By default (`voice.engine: auto` with no key) JARVIS listens with
**faster-whisper** — completely keyless — and triggers on hearing "jarvis". It
also accepts common mishearings ("jarvas", "jervis", …) and lets you speak the
whole command in one breath: *"Jarvis, what's the weather?"*

For lower CPU use, get a **free** Picovoice access key
([console.picovoice.ai](https://console.picovoice.ai/)) and paste it into
`voice.porcupine_access_key`. Porcupine's free tier is fine for personal use.

---

## Safety

* Destructive shell commands (`rm -rf`, `sudo`, `kill`, `mkfs`, fork bombs…) are
  either blocked outright or require a spoken/typed confirmation.
* File writes are limited to your home directory and the project folder by
  default (`security.allowed_roots`).
* Python snippets run in a temporary directory as a separate, isolated process
  with a timeout; anything touching the filesystem, shell or network prompts
  first.
* Every risk assessment is logged to `logs/jarvis.log`.

---

## Troubleshooting

**"My language model is offline"**
Ollama isn't running. `ollama serve`, then `ollama list` to confirm your model
is installed. JARVIS keeps working in reflex mode meanwhile — timers, stats,
file search and app launching still respond.

**Whisper is slow**
Use a smaller model: `voice.stt.model: tiny.en`. With an NVIDIA GPU, set
`device: cuda` and `compute_type: float16`.

**No sound**
Install ffmpeg (`ffplay` is the default player) or mpv. Check with
`python main.py --test`.

**Microphone not detected**
`python -c "import sounddevice; print(sounddevice.query_devices())"`.
On Linux ensure your user is in the `audio` group; on macOS grant microphone
permission to your terminal.

**Wake word never fires**
Lower `voice.vad.energy_threshold` (e.g. `0.008`) in a quiet room, or raise it
in a noisy one. Run with `--debug` to see what Whisper thinks it heard.

**ChromaDB won't install**
JARVIS automatically falls back to a JSON vector store with the same behaviour —
memory keeps working.

**Everything is slow on first run**
The Whisper model downloads once (~150 MB for `base.en`) and Ollama loads the
LLM into RAM on the first prompt. Subsequent turns are much faster.

---

## Cost

Zero. Forever. The only network calls are to free, key-less public endpoints
(DuckDuckGo, wttr.in, Wikipedia, RSS feeds, Microsoft's public TTS endpoint) —
and even those are optional. Turn off `modules.web_search` and JARVIS is fully
offline.

## Licence

MIT — do whatever you like with it.
