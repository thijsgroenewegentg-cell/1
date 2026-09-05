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
| Document RAG | your files + **ChromaDB** + local embeddings | free |
| Vision | **llava** through Ollama | free |
| Email & calendar | plain **IMAP/SMTP** + **iCalendar** | free |
| Phone / LAN UI | **FastAPI** + WebSockets, served from your own machine | free |
| Self-improvement | **GitHub search API** (keyless) + `git clone` + its own LLM | free, no key |

Ten capability modules, 103 callable tools:

* **system_control** — open/close apps, screenshots, CPU/RAM/disk/battery, volume, lock screen, clipboard, keyboard & mouse automation, shell commands (guarded), time/date
* **web_search** — DuckDuckGo search, page scraping + summarising, weather, news, Wikipedia, geocoding
* **productivity** — todos, reminders with real notifications, timers, stopwatch, notes, daily briefing
* **code_assistant** — write, explain, debug, refactor, test, save and *run* code in a sandbox
* **file_manager** — find files by name/content, organise folders, summarise PDF/DOCX/TXT, analyse CSVs, find duplicates, disk usage
* **smart_assistant** — Q&A with web RAG, safe maths, unit & currency conversion, translation, summarising, creative writing
* **knowledge** — a private knowledge base built from *your* documents: index folders, semantic search, cited answers ("what does my lease say about pets?")
* **vision** — looks at your screen or any image with a local llava model: describe, read text, compare screenshots
* **communications** — IMAP inbox triage with LLM summaries, SMTP sending (off by default), and calendars from `.ics` files or secret export URLs
* **self_improve** — searches GitHub, clones repositories, writes its own skill adapters for them, reads and rewrites its own source, runs its own test suite, commits, and rolls back anything that breaks

And the things that make it feel alive:

* **Streaming replies** — tokens appear as they are generated, in the terminal *and* over the web UI
* **Pipelined speech** — the first sentence is spoken while the third is still being written
* **Barge-in that really cancels** — talking over JARVIS stops both playback *and* generation
* **Follow-ups** — "shall I organise it for real?" → just say **yes**
* **Rolling summaries** — long conversations are compressed instead of forgotten
* **Cached web lookups** — a SQLite TTL cache keeps the free endpoints happy
* **It grows** — "find a GitHub library for QR codes and integrate it" adds a working skill to the running assistant, no restart

---

## Quick start — the easy installer

One command. It checks your machine, builds the environment, installs the
packages, installs Ollama, pulls the model, writes the config, adds a desktop
shortcut and self-tests the lot.

**Windows** — double-click **`install.bat`** *(or `py install.py` in PowerShell)*

**macOS** — double-click **`install.command`** *(or `bash install.sh` in Terminal)*

**Linux**

```bash
bash install.sh
```

Nothing installed yet? The installer even fetches the project for you:

```bash
curl -fsSL https://raw.githubusercontent.com/thijsgroenewegentg-cell/1/main/install.sh | bash
```

It asks three questions (install size, your name, desktop shortcut) and then
gets on with it. Prefer no questions at all?

```bash
python3 install.py --yes          # every default, straight through
python3 install.py --minimal      # text only, ~120 MB
python3 install.py --standard     # everything except the microphone stack
python3 install.py --full         # + voice, wake word, Whisper  (the default)
python3 install.py --no-ollama    # skip the LLM engine for now
python3 install.py --repair       # reinstall packages into an existing install
python3 install.py --help         # all the flags
```

| Profile | What you get | Download |
|---|---|---|
| `--minimal` | text + web + phone UI | ~120 MB |
| `--standard` | + memory, documents, desktop control | ~700 MB |
| `--full` *(default)* | + voice, wake word, faster-whisper, edge-tts | ~2.5 GB |

When it finishes:

```bash
.venv/bin/python main.py         # Windows: .venv\Scripts\python main.py
```

Then say **"Jarvis"**, wait for the chime, and talk. Or just type.

> Shell purist? `bash setup.sh` is the original bash installer and still works
> on macOS/Linux. `install.py` is the cross-platform one and does more.

---

## Requirements

* Python 3.9+ (3.11 recommended)
* ~6 GB free disk (LLM + Whisper models)
* 8 GB RAM minimum for `llama3.2`; 16 GB is comfortable
* A microphone and speakers for voice mode (optional — text mode always works)
* `git` on PATH (optional — only for cloning repositories it wants to integrate)

---

## Setup: Windows

> The short version: install Python, then double-click **`install.bat`**.
> The steps below are the manual equivalent, if you would rather do it yourself.

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

> The short version: double-click **`install.command`**.
> The manual equivalent:

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

> The short version: `bash install.sh`. The manual equivalent:

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
python main.py --web               # phone/browser interface on your LAN
python main.py --web --port 9000 --with-cli   # web + terminal in one process
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
| `web [port]` | start the phone/LAN interface in the background |
| `index [path]` | add documents to the private knowledge base |
| `look` | describe what is on your screen (needs `ollama pull llava`) |
| `stream on\|off` | toggle live token-by-token replies |
| `plugins` | list the skills JARVIS has written for itself |
| `changes` / `undo` | its own change history, and roll back the last one |
| `selftest` | run the 154-check smoke suite against the current code |
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
"Index my documents"
"What does my travel policy say about per-diem?"
"What's on my screen?"
"Read the error message on my screen"
"What's on my calendar today"
"Add a dentist appointment tomorrow at 9am"
"Check my email"          (after configuring IMAP)
"Summarise my inbox"
"Stop"                    (cancels a reply mid-sentence)
"Search github for a python library that reads QR codes"
"Integrate that repo"
"What plugins do you have"
"Show me your own code map"
"Read your web_search module, lines 1 to 40"
"Improve your own error messages in modules/productivity.py"
"Run your tests"
"What have you changed about yourself"
"Undo your last change"
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
├── install.py               the easy installer (Windows / macOS / Linux)
├── install.bat              double-click installer for Windows
├── install.command          double-click installer for macOS
├── install.sh               one-line installer for macOS / Linux (can self-clone)
├── main.py                  entry point (voice / CLI / one-shot / self-test)
├── config.yaml              every setting
├── requirements.txt
├── setup.sh                 one-click installer + self-test
├── core/
│   ├── brain.py             Ollama client, intent router, ReAct loop, persona
│   ├── memory.py            short-term window + ChromaDB long-term memory
│   └── config.py            YAML config with defaults and env overrides
├── pyproject.toml           optional packaging → a global `jarvis` command
├── interfaces/
│   ├── voice.py             wake word (porcupine/openWakeWord/whisper), VAD,
│   │                        faster-whisper STT, edge-tts, streaming speech, barge-in
│   ├── cli.py               rich terminal UI with live streaming replies
│   └── web.py               FastAPI + WebSocket phone/LAN chat interface
├── modules/
│   ├── base.py              tool decorator, dispatch, offline routing
│   ├── system_control.py    apps, stats, volume, input, shell
│   ├── web_search.py        DuckDuckGo, scraping, weather, news, Wikipedia
│   ├── productivity.py      todos, reminders, timers, notes, briefing
│   ├── code_assistant.py    write / explain / debug / run / save code
│   ├── file_manager.py      search, organise, summarise, CSV analysis
│   ├── smart_assistant.py   Q&A + RAG, maths, conversions, translation, writing
│   ├── knowledge.py         private document knowledge base (index + cited answers)
│   ├── vision.py            screen and image understanding via llava
│   ├── communications.py    IMAP/SMTP email and .ics calendars
│   └── self_improve.py      GitHub search, repo integration, self-editing, rollback
├── utils/
│   ├── logger.py            coloured console + rotating file logs
│   ├── helpers.py           shared utilities
│   ├── security.py          risk assessment + confirmation gate
│   ├── cache.py             SQLite TTL cache for web lookups
│   └── documents.py         shared PDF/DOCX/PPTX/HTML text extraction + chunking
├── scripts/
│   ├── jarvis.sh / jarvis.bat            launchers that also start Ollama
│   ├── install_service_linux.sh          systemd user service
│   ├── install_service_macos.sh          LaunchAgent
│   └── install_service_windows.ps1       scheduled task at logon
├── .github/ci.yml           lint + smoke suite CI (move to .github/workflows/)
├── plugins/                 skills JARVIS writes for itself (loaded at start-up)
├── tests/
│   ├── test_smoke.py        154-check end-to-end suite
│   └── mock_ollama.py       scripted LLM server (streaming + vision) for testing
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

memory:
  summarize: true            # compress old turns into a running briefing
  summary_trigger: 12        # …once the window passes this many exchanges

voice:
  stream_speech: true        # speak sentence-by-sentence while generating
  conversation_mode: true    # no wake word needed for follow-ups
  conversation_timeout: 12

knowledge:
  paths: ["~/Documents"]     # folders to index
  top_k: 5

vision:
  model: "llava"             # ollama pull llava

web_ui:
  enabled: false
  host: "0.0.0.0"            # reachable from your phone on the same Wi-Fi
  port: 8765
  token: ""                  # optional shared secret: http://…:8765/?token=…

email:
  enabled: false
  imap_host: "imap.gmail.com"
  user: "you@gmail.com"
  password_env: "JARVIS_EMAIL_PASSWORD"   # the password is NEVER stored in config
  allow_send: false

calendar:
  files: ["~/calendars/work.ics"]
  urls: []                   # Google/Outlook "secret address in iCal format"

self_improve:
  enabled: true
  allow_code_edit: true      # may rewrite its own source files
  allow_plugin_install: true # may write new skills into plugins/
  allow_pip_install: false   # may NOT install packages unless you say so
  run_tests_after_edit: true # every self-edit must survive tests/test_smoke.py
  git_commit: true           # commits each change locally (never pushes)
  protected:                 # files it refuses to touch
    - utils/security.py
    - modules/self_improve.py
    - config.yaml

modules:                 # switch any capability off; nothing else breaks
  system_control: true
  web_search: true
  knowledge: true
  vision: true
  communications: true
  self_improve: true
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
| `llava` (7B) | 8 GB | the eyes — used by the vision module |

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

For lower CPU use you have two free options:

* **openWakeWord** — fully open source, no account at all:
  `pip install openwakeword`, then set `voice.engine: openwakeword`. The
  bundled `hey_jarvis` model is downloaded automatically on first run.
* **Porcupine** — get a free access key from
  [console.picovoice.ai](https://console.picovoice.ai/) and paste it into
  `voice.porcupine_access_key`. The free tier is fine for personal use.

With `voice.conversation_mode: true` you only need the wake word once: after a
reply the microphone stays open for `voice.conversation_timeout` seconds so
follow-up questions flow naturally. Say **"stop"** to cut a reply short.

---

## Your documents, privately (RAG)

```bash
# point it at your folders in config.yaml, then:
python main.py --cli
> index ~/Documents
> what does my travel policy say about per-diem?
```

Files are extracted (PDF, DOCX, PPTX, Markdown, HTML, code, plain text),
chunked with overlap, embedded locally with `nomic-embed-text` and stored in a
ChromaDB collection under `data/knowledge`. Re-indexing only touches files whose
modification time changed. Answers cite the documents they came from. Nothing is
uploaded anywhere.

---

## Eyes: seeing your screen

```bash
ollama pull llava        # ~4.7 GB, free
```

```
"What's on my screen?"          → describes the active desktop
"Read the error on my screen"   → transcribes the text it sees
"Describe ~/Pictures/chart.png" → answers questions about any image
```

Screen capture uses `screencapture` (macOS), PowerShell + .NET (Windows) or
`gnome-screenshot`/`spectacle`/`scrot`/`maim`/`grim` (Linux), with a Pillow
fallback. Screenshots stay in `data/screenshots` and are pruned automatically.

---

## Email and calendar

Email is plain IMAP/SMTP, so every provider works. The password is read from an
environment variable — it is never written to `config.yaml`:

```bash
export JARVIS_EMAIL_PASSWORD='your-app-password'    # Gmail: an App Password
```

```yaml
email:
  enabled: true
  imap_host: "imap.gmail.com"
  smtp_host: "smtp.gmail.com"
  user: "you@gmail.com"
  allow_send: false      # set true only if you want JARVIS to send mail
```

Calendars are read from local `.ics` files and from the "secret address in iCal
format" URL that Google Calendar, Outlook and Nextcloud all publish for free.
`add_event` writes to a local `data/jarvis.ics` you can subscribe to from your
phone. Today's events are folded into the daily briefing.

---

## Chat from your phone

```bash
python main.py --web
#  ✓ Web interface: http://192.168.1.24:8765/
```

Open that address on any device on the same network: a dark, mobile-first chat
page with streaming replies, a Stop button, quick-action chips and optional
spoken answers. It is served **by your own machine** — no tunnel, no cloud.
Set `web_ui.token` to require `?token=…`, and keep it off public Wi-Fi.

There is a plain JSON API too:

```bash
curl -X POST localhost:8765/api/ask -H 'Content-Type: application/json' \
     -d '{"text":"what time is it"}'
```

---

## It can extend and rewrite itself

JARVIS can go shopping on GitHub, turn a repository into one of its own skills,
and edit its own source code — with a test suite, backups and git as the safety
net. No API key: GitHub's search endpoint is free and anonymous (set
`GITHUB_TOKEN` in your environment only if you hit the 10-searches-a-minute
anonymous limit).

```
you  > find me a github library for reading qr codes
JARVIS > GitHub results for 'qr code python':
         1. lincolnloop/python-qrcode ★4,600 · Python · BSD-3-Clause
         2. NaturalHistoryMuseum/pyzbar ★700 · Python · MIT
         Shall I integrate one of them, sir?
you  > integrate the second one
JARVIS > Integrated NaturalHistoryMuseum/pyzbar as the 'pyzbar' skill.
           source : data/repos/pyzbar
           adapter: plugins/pyzbar.py
           tools  : decode_qr, decode_barcode
           status : loaded and active right now
you  > read the qr code in ~/Downloads/ticket.png
JARVIS > It points to https://…
```

**How an integration works**

1. `search_github` → GitHub's REST search, ranked by stars, with licence and
   last-commit dates so you can judge what you are pulling in.
2. `integrate_repo` → `git clone --depth 1` into `data/repos/<skill>`, then the
   repo is *surveyed*: README, the largest non-test Python files, the package
   name, its requirements and every public entry point (extracted with `ast`).
3. Your local LLM writes an adapter — a normal JARVIS module with 2–5 `@tool`
   methods that call the library.
4. The adapter is **validated before it is ever imported**: it must parse, must
   subclass `BaseModule`, and must not contain `os.system`, `subprocess`,
   `eval`, `exec`, `__import__` or `shutil.rmtree`. A bad first draft is sent
   back to the model once with the error; if it still fails, a safe stub is
   written instead of dangerous code.
5. It is written to `plugins/<skill>.py`, imported, registered with the running
   brain (**no restart**) and committed to git.

Dependencies are never installed behind your back: `allow_pip_install` is
`false` by default, so JARVIS tells you what to install and waits.

**Changing its own code**

```
you  > your weather replies are too long, fix that in your own code
JARVIS > Rewrote modules/web_search.py (change #4).
           tests  : 154 passed in 12.4s
           reload : Reloaded 'web_search' — 8 tools active
           backup : data/backups/20260906_101511_modules_web_search.py
           commit : a91f0c2
         --- a/modules/web_search.py
         +++ b/modules/web_search.py
         @@ …
you  > actually, undo that
JARVIS > Reverted change #4 (edit on modules/web_search.py).
```

Every self-edit goes through the same gauntlet:

| Guard | What it does |
|---|---|
| Protected list | refuses to touch `utils/security.py`, its own `self_improve.py`, or `config.yaml` |
| Sanity check | the rewrite must parse, keep ≥ 50 % of the file, keep every `@tool`, and introduce no `TODO`/`...` placeholders |
| Safety check | rejects any patch that deletes confirmation prompts, `dangerous=True` flags or error handling |
| Backup | the old file is copied to `data/backups/` first (last 40 kept) |
| Tests | `tests/test_smoke.py` runs; **if it fails the file is restored byte-for-byte** |
| Hot reload | the module is re-imported and swapped into the live assistant |
| Git | committed locally with a `self:` message — never pushed anywhere |

**The tools** (say any of these in plain English)

| Tool | Does |
|---|---|
| `search_github` | search repositories by topic, language, stars |
| `repo_details` | stars, licence, activity and README of one repo |
| `integrate_repo` | clone + write + load a new skill (asks first) |
| `list_plugins` / `remove_plugin` | see and delete self-written skills |
| `install_package` | pip install into JARVIS's own venv (off by default) |
| `code_map` | inventory of its own files, lines and tools |
| `read_own_code` | print any of its own source files with line numbers |
| `edit_own_code` | rewrite one of its files to your instruction (asks first) |
| `run_self_tests` | run the smoke suite and report |
| `reload_module` | hot-reload a module after a change |
| `rollback` / `change_history` | undo any change, list everything it has done |
| `suggest_improvements` | read its own code and propose what to improve |
| `self_status` | which of the above powers are switched on |

Turn the whole thing off with `self_improve.enabled: false`, or keep the
research half and disable the surgery with `allow_code_edit: false`.

---

## Starting automatically

```bash
bash scripts/install_service_linux.sh      # systemd user service
bash scripts/install_service_macos.sh      # LaunchAgent
powershell -ExecutionPolicy Bypass -File scripts\install_service_windows.ps1
```

Each script installs a login-time service running `python main.py --web`
(override with `JARVIS_ARGS="--voice"`), logs to `logs/service.log`, and takes a
`--remove` / `-Remove` flag to uninstall.

---

## Safety

* Destructive shell commands (`rm -rf`, `sudo`, `kill`, `mkfs`, fork bombs…) are
  either blocked outright or require a spoken/typed confirmation.
* File writes are limited to your home directory and the project folder by
  default (`security.allowed_roots`).
* Python snippets run in a temporary directory as a separate, isolated process
  with a timeout; anything touching the filesystem, shell or network prompts
  first.
* Self-modification is gated: dangerous tools ask for confirmation, generated
  plugins are scanned before import, self-edits must pass the test suite, and
  every change is backed up and revertible with `rollback`.
* JARVIS commits its own changes locally but **never pushes** to a remote.
* Every risk assessment is logged to `logs/jarvis.log`.

---

## Troubleshooting

**The installer says Python was not found (Windows)**
Reinstall Python from [python.org](https://www.python.org/downloads/windows/)
and tick *"Add python.exe to PATH"* on the first screen, then double-click
`install.bat` again.

**A package refuses to build during installation**
Almost always an audio or ML wheel. Rerun with a smaller profile — everything
except voice still works:

```bash
python install.py --standard      # no microphone stack
python install.py --minimal       # text and web only
```

The installer already retries optional groups package by package, so a single
failure only disables that one feature; the list is repeated at the end.

**Ollama was installed but "command not found"**
Open a new terminal (PATH is only read at start-up) and rerun the installer —
it is safe to run as often as you like and skips anything already done. On
macOS, launch the Ollama app once so it can install its command-line tool.

**Something got into a strange state**
```bash
python install.py --repair        # reinstall the packages, keep your config
python install.py --recreate      # rebuild the virtual environment from scratch
```

**"My language model is offline"**
Ollama isn't running. `ollama serve`, then `ollama list` to confirm your model
is installed. JARVIS keeps working in reflex mode meanwhile — timers, stats,
file search and app launching still respond.

**"GitHub is rate-limiting me"**
Anonymous search allows ten queries a minute. Create a *classic* token with no
scopes at <https://github.com/settings/tokens> and export it as `GITHUB_TOKEN`
(30/minute). It stays optional — nothing else uses it.

**A self-written plugin misbehaves**
`remove_plugin` deletes it and unloads it live, or just delete
`plugins/<name>.py` and restart. Set `modules.<name>: false` to keep the file
but stop loading it.

**A self-edit broke something**
It shouldn't — the tests run first and a failure restores the file. If you
disabled `run_tests_after_edit`, say *"undo your last change"* (`rollback`), or
copy the file back yourself from `data/backups/`.

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

**"The web interface needs FastAPI and uvicorn"**
`pip install fastapi "uvicorn[standard]"` — both are free and small.

**"I have no eyes yet"**
The vision module needs a multimodal model: `ollama pull llava`.
Check the rest of the pipeline with `look` in the CLI or "vision status".

**Email says "No password found"**
Export the variable named by `email.password_env` before starting JARVIS:
`export JARVIS_EMAIL_PASSWORD='…'`. Gmail and Outlook require an *app
password*, not your account password.

**The phone can't reach the web UI**
Both devices must be on the same network, `web_ui.host` must be `0.0.0.0`, and
your firewall must allow the port (macOS: System Settings → Network → Firewall;
Windows: `New-NetFirewallRule -DisplayName JARVIS -Direction Inbound -LocalPort 8765 -Protocol TCP -Action Allow`).

**Everything is slow on first run**
The Whisper model downloads once (~150 MB for `base.en`) and Ollama loads the
LLM into RAM on the first prompt. Subsequent turns are much faster.

---

## Installing it as a command (optional)

```bash
pip install -e .            # from the project directory
jarvis --cli                # now available anywhere
jarvis --web --port 8765
```

Extras mirror the optional dependencies: `pip install -e ".[voice]"`,
`".[web]"`, `".[vision]"` or `".[all]"`.

---

## Continuous integration

`.github/ci.yml` (move it to `.github/workflows/ci.yml` to switch it on) runs
pyflakes, byte-compiles every module, executes
the 154-check offline smoke suite on Linux, macOS and Windows (Python 3.9–3.12)
and builds a wheel. No models are downloaded — `tests/mock_ollama.py` scripts
the LLM, including token streaming and vision responses.

---

## Cost

Zero. Forever. The only network calls are to free, key-less public endpoints
(DuckDuckGo, wttr.in, Wikipedia, RSS feeds, GitHub's anonymous search API,
Microsoft's public TTS endpoint) —
and even those are optional. Turn off `modules.web_search` and JARVIS is fully
offline.

## Licence

MIT — do whatever you like with it.
