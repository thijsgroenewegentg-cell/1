# How to Install J.A.R.V.I.S — 100% FREE, No API Keys, RX 9070 XT 16GB Optimized, Voice MUST BE PIPER

> One command install, then you have Stark Tower JARVIS locally.

## Quick Install (30 seconds, recommended)

```bash
git clone https://github.com/thijsgroenewegentg-cell/1.git jarvis
cd jarvis
./setup.sh
```

What `setup.sh` does **100% FREE**:
- Checks Python 3.10+, Ollama
- Creates venv if needed, `pip install -r requirements.txt` (all free)
- Creates `data/`, `workspace/`
- Copies `.env.example` → `.env` (voice MUST BE PIPER already set)
- Pulls `qwen2.5:7b` (fallback) + `nomic-embed-text` (free embeddings)
- Creates `jarvis` model from `Modelfile` (for 9070 XT use `Modelfile.9070xt`)

Then:
```bash
ollama serve  # if not running, in another terminal
# For RX 9070 XT if ROCm too new:
HSA_OVERRIDE_GFX_VERSION=12.0.0 ollama serve

python3 JARVIS.py          # Singular app - everything in one, opens /holo movable UI
# or
./run.sh singular          # Same
# or
./run.sh 9070xt            # Optimized for your RX 9070 XT 16GB - pulls 14B and starts singular
```

Open http://localhost:8000 (minimal) and http://localhost:8000/holo (movable holographic, draggable panels Manina Labs style).

That's it. No API keys, ever.

---

## Manual Install — Step by Step (if quick fails)

### 0. Prerequisites — All Free

- **Python 3.10+**: `python3 --version`
  - Ubuntu/Debian: `sudo apt update && sudo apt install python3 python3-venv python3-pip git -y`
  - Windows: https://python.org → Add to PATH
  - Mac: `brew install python`

- **Ollama** — brains, free local LLM runner: https://ollama.com
  - Linux: `curl -fsSL https://ollama.com/install.sh | sh`
  - Windows/Mac: Download from site, or `brew install ollama`
  - Verify: `ollama --version` and `ollama serve` running

- **For RX 9070 XT 16GB specifically (AMD ROCm)**:
  - Linux: Install ROCm 6.2+ from https://rocm.docs.amd.com/ (Ubuntu 22.04/24.04 supported)
  - Check: `rocm-smi` should show your 9070 XT
  - Ollama uses ROCm automatically via image `ollama/ollama:rocm`
  - If RDNA 4 too new: `HSA_OVERRIDE_GFX_VERSION=12.0.0 ollama serve` and `HCC_AMDGPU_TARGET=gfx1200`
  - No ROCm on Windows? Ollama will fallback to CPU or DirectML, still works but slower

### 1. Clone & Python Env

```bash
git clone https://github.com/thijsgroenewegentg-cell/1.git jarvis
cd jarvis
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

pip install --upgrade pip
pip install -r requirements.txt --break-system-packages
```

`requirements.txt` is 100% free:
- Core: `ollama`, `requests`, `python-dotenv`
- Web: `fastapi`, `uvicorn`, `websockets`
- Tools: `duckduckgo-search` (free search), `psutil`, `beautifulsoup4`
- Voice STT: `faster-whisper` (free offline), `SpeechRecognition`, `pyaudio` (Linux: `sudo apt install portaudio19-dev espeak ffmpeg`)
- Wake Word: `openwakeword` (free ONNX), `webrtcvad`, `onnxruntime`
- Voice TTS MUST BE PIPER: `pyttsx3` (free offline fallback), `edge-tts` (free, no key, with premium FX), `pygame`, `pydub` (for bass+reverb FX), `piper-tts` optional but MUST for premium free offline British
- Document Second Brain: `pypdf` (free PDF), `python-docx` (free docx)
- Browser Computer Use: `playwright` (free local browser)
- Proactive: `apscheduler`, `plyer` (free notifications)
- Desktop: `customtkinter`, `pillow`, `pystray`, `pywebview`
- Optional: `chromadb`

### 2. Voice MUST BE PIPER — 100% FREE Offline British Premium

Default is already piper in `.env.example`, but you need voice model files (free):

```bash
# Install piper (MUST, best free offline)
pip install piper-tts --break-system-packages

# Download British voice model (free, 30MB, from HuggingFace, no key)
python -m piper.download_voices en_GB-alan-medium --data-dir data/piper_models
# Alternatives free British:
# python -m piper.download_voices en_GB-jenny_dioco-medium --data-dir data/piper_models  # FRIDAY female
# python -m piper.download_voices en_GB-southern_english_male-medium --data-dir data/piper_models  # deep commanding

# Or manual download:
mkdir -p data/piper_models
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx -P data/piper_models/
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json -P data/piper_models/

# Verify:
ls data/piper_models/
# Should have: en_GB-alan-medium.onnx + .onnx.json
```

`.env` already has:
```
TTS_ENGINE=piper
TTS_VOICE=en_GB-alan-medium
PREMIUM_VOICE_STYLE=manina_premium
```

Test:
```bash
python -m jarvis.voice.premium --engine piper --preset manina_premium --text "Good evening, Sir. Piper premium voice, 100 percent free offline, British, Manina style."
```

If piper fails, it auto-falls back to `edge` (free online, no key, with premium FX bass+reverb) — still free.

**Other free voice engines (no keys):**
- `edge`: Microsoft free online, with premium FX, default fallback, sounds premium
- `xtts`: free local cloning, clone Paul Bettany — `pip install TTS`, place 5-10 sec WAV in `data/voices/manina_premium.wav`, `TTS_ENGINE=xtts`
- `pyttsx3`: free offline robotic fallback

**NO paid keys needed:** `ELEVENLABS_API_KEY` and `OPENAI_API_KEY` are optional, leave empty.

### 3. Ollama Models — All Free, Local

**For RX 9070 XT 16GB (your card, recommended):**

```bash
# Best for 16GB VRAM — much smarter than 7B
ollama pull qwen2.5:14b
# Even smarter, 32B Q4 fits ~12GB VRAM, genius level, ~30-45 tok/s on 9070 XT:
ollama pull qwen2.5:32b-instruct-q4_K_M

# For coding agent specifically
ollama pull qwen2.5-coder:14b

# For vision (JARVIS sees your screen)
ollama pull llava:13b  # fits 10GB, or llava:34b Q4 fits 16GB

# Embeddings for RAG (codebase + documents + learning)
ollama pull nomic-embed-text

# Create jarvis model from Modelfile.9070xt (uses 14B, 16384 ctx, optimized for 9070 XT)
ollama create jarvis -f Modelfile.9070xt --force
# Or for 7B fallback:
# ollama pull qwen2.5:7b
# ollama create jarvis -f Modelfile
```

**For CPU / low VRAM (fallback):**
```bash
ollama pull qwen2.5:7b
ollama create jarvis -f Modelfile
```

List models: `ollama list`

### 4. Browser Computer Use — Free Local Playwright

For JARVIS to control browser like Claude Computer Use, but free:

```bash
pip install playwright --break-system-packages
playwright install chromium  # downloads Chromium ~130MB, free
```

Now tools `browser_navigate`, `browser_click`, `browser_type`, etc work 100% free local.

### 5. Desktop App Dependencies (Optional, Free)

For Python desktop native + tray:

- Linux: `sudo apt install python3-tk portaudio19-dev espeak ffmpeg libnotify-bin -y`
- Windows: No extra, but `pip install pyaudio` needs Microsoft C++ Build Tools
- Mac: `brew install portaudio ffmpeg`

```bash
pip install customtkinter pillow pystray pywebview --break-system-packages
```

For Electron (global hotkey Ctrl+Shift+J):

```bash
cd desktop/electron
npm install  # needs Node.js https://nodejs.org
npm start
```

### 6. Configure .env (Optional, All Free)

```bash
cp .env.example .env
nano .env  # edit if needed
```

Key free settings already set:

```
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=jarvis
TTS_ENGINE=piper  # MUST BE PIPER
TTS_VOICE=en_GB-alan-medium
PREMIUM_VOICE_STYLE=manina_premium
STT_ENGINE=faster-whisper
ALWAYS_ON_ENABLED=false  # set true for 24/7 "Jarvis" listening
PROACTIVE_ENABLED=true   # morning briefing 8:30, git watcher
TEAM_ENABLED=true
# ... all free
# Leave paid keys empty for free:
# ELEVENLABS_API_KEY=
# OPENAI_API_KEY=
```

For email/calendar/media (100% free local, except your own email credentials):

- Calendar: Place ICS files (export from Google Calendar as ICS) into `workspace/calendar/` or `data/calendar/` — no API key, free local parsing via `icalendar`
- Email: Add to `.env` (use app password, not main password):
  ```
  EMAIL_IMAP_HOST=imap.gmail.com
  EMAIL_IMAP_USER=you@gmail.com
  EMAIL_IMAP_PASS=your_app_password_from_myaccount.google.com/apppasswords
  EMAIL_SMTP_HOST=smtp.gmail.com
  EMAIL_SMTP_PORT=587
  ```
  For Outlook: `outlook.office365.com` / `smtp.office365.com`
- Music: Add MP3s to `workspace/music/` or `~/Music/` — local playback via pygame free

### 7. Run — Singular App (Everything in One)

**Recommended for RX 9070 XT 16GB, 100% free:**

```bash
# Option A: Singular app (web + holo movable + proactive + tray + indexing)
python3 JARVIS.py
# or
./run.sh singular
# Opens http://localhost:8000/ (minimal) and http://localhost:8000/holo (movable holographic, draggable panels Manina Labs style)

# Option B: Optimized for 9070 XT (pulls 14B, creates jarvis from Modelfile.9070xt, starts singular)
./run.sh 9070xt

# Option C: Web only
python3 web/server.py
# Then open http://localhost:8000/holo for movable UI

# Option D: CLI
python3 cli.py
# Voice: python3 cli.py --voice
# Always-on wake word 24/7: python3 cli.py --always-on (say "Jarvis" anytime)
# Proactive: python3 cli.py --proactive
# Agent: python3 cli.py --agent "Add JWT auth"
# Team: python3 cli.py --team "Research best auth lib and implement"
```

**All modes 100% free, no keys.**

### 8. Docker (Optional, 100% Free)

For isolated run, with AMD ROCm for 9070 XT:

```bash
# CPU fallback
docker-compose --profile cpu up --build

# NVIDIA GPU
docker-compose --profile nvidia up --build

# AMD RX 9070 XT 16GB - ROCm, 14B model, optimized
docker-compose --profile 9070xt up --build
# Uses image ollama/ollama:rocm, devices /dev/kfd /dev/dri, HSA_OVERRIDE_GFX_VERSION=12.0.0, pulls qwen2.5:14b + nomic-embed-text, creates jarvis from Modelfile.9070xt

# Then open http://localhost:8000/holo
```

### 9. Verify Installation — 100% Free Check

```bash
# Check components, all should be ✓ free
python3 -c "
from jarvis.voice.premium import VOICE_PRESETS
print('Voice presets (all free):', list(VOICE_PRESETS.keys()))
"

# Test TTS piper free offline
python3 -m jarvis.voice.premium --engine piper --preset manina_premium --text "Good evening Sir, Piper premium voice 100 percent free offline"

# Test brain
curl http://localhost:11434/api/tags  # Ollama running?
ollama list  # models?

# Test codebase RAG
python3 cli.py --index
python3 cli.py --search-code "authentication"

# Test productivity hub (free local ICS)
mkdir -p workspace/calendar
# Place test.ics file in workspace/calendar/ then:
python3 -c "from jarvis.productivity import CalendarHub; c=CalendarHub(); print(c.sync_calendars())"

# Test media (free local)
mkdir -p workspace/music
# Place MP3 in workspace/music/ then:
python3 -c "from jarvis.media import MusicPlayer; m=MusicPlayer(); print(m.get_overview())"
```

### 10. First Use — What to Say

After `python3 JARVIS.py` and browser opens `/holo`:

- **Chat:** "What time is it?" → `get_time` tool (free)
- **Movable UI:** Drag panels, + Panel → Add Codebase, Browser, Goals, Voice Lab, Save Layout
- **Premium Voice Piper:** Top bar Voice Lab → select `manina_premium` → Speak → deep British cinematic, 100% free offline
- **Codebase RAG:** In Chat: "Analyze codebase" → `analyze_codebase`, "Search codebase for auth logic" → `search_codebase`
- **Knowledge:** Place PDFs in `workspace/docs/`, then "Index documents" → `search_knowledge("my notes")` or "Search everything about project X"
- **Browser:** "Open browser to github.com and search for fastapi docs" → `browser_navigate`, `browser_search`, etc (Playwright free)
- **Productivity:** Place ICS in `workspace/calendar/`, then "What are my events today?" → `get_today_events`, "Sync calendars" → `sync_calendars`
- **Email:** Set .env IMAP/SMTP app passwords, then "Fetch latest emails" → `fetch_emails`, "Send email to boss@example.com subject Test body Hello Sir"
- **Media:** Place MP3s in `workspace/music/`, then "Play some jazz" → `play_music`, "List speaker zones" → `list_speaker_zones`, "Set lab volume to 80"
- **Goals:** "Add goal Build SaaS to $1k MRR by Dec 2025 with milestones Design,MVP,Launch" → `add_goal`, "List goals", "Check goals" → accountability
- **Agent:** Click ⚡ Agent → Task "Add JWT auth to web server" → Start → watches plan → code → test → commit autonomous
- **Team:** Click 👥 Team → Task "Research best rate limiting lib for FastAPI and implement" → Planner → Researcher → Coder → Reviewer collaborate
- **Evolution:** Click 🧬 → Improve yourself → he self-critics and rewrites prompt, forges tools
- **Self-Edit:** Say "JARVIS, read your own brain.py and improve it" → `read_self_code` → `edit_self_code` with backup+compile check+rollback

All 100% free, no API keys, fully local, RX 9070 XT 16GB optimized.

---

## Troubleshooting — 100% Free Fixes

**Ollama not running:**
```bash
ollama serve
# For 9070 XT RDNA 4 too new:
HSA_OVERRIDE_GFX_VERSION=12.0.0 ollama serve
```

**Piper voice not found:**
```bash
pip install piper-tts --break-system-packages
python -m piper.download_voices en_GB-alan-medium --data-dir data/piper_models
ls data/piper_models/  # should have .onnx + .json
# .env already TTS_ENGINE=piper, TTS_VOICE=en_GB-alan-medium
```

**pyaudio / portaudio error (Linux):**
```bash
sudo apt install portaudio19-dev espeak ffmpeg python3-pyaudio -y
pip install pyaudio --break-system-packages
```

**Playwright browser not installed:**
```bash
pip install playwright --break-system-packages
playwright install chromium
```

**openwakeword / faster-whisper fails:**
```bash
pip install openwakeword webrtcvad onnxruntime faster-whisper --break-system-packages
```

**No MP3s for music:**
```bash
mkdir -p workspace/music
# Add MP3s to workspace/music/ or ~/Music/
# Then: list_music tool or Music panel
```

**Calendar empty:**
```bash
mkdir -p workspace/calendar
# Export Google Calendar as ICS: calendar.google.com → Settings → Export → place ICS in workspace/calendar/
# Then: sync_calendars tool or ask "Sync calendars"
```

**Email not configured:**
```
.env: EMAIL_IMAP_HOST=imap.gmail.com, EMAIL_IMAP_USER=you@gmail.com, EMAIL_IMAP_PASS=app_password (from myaccount.google.com/apppasswords, not main password), EMAIL_SMTP_HOST=smtp.gmail.com, EMAIL_SMTP_PORT=587
```

**Web UI 404 /style.css:**
- Make sure you run from project root: `python3 web/server.py` or `python3 JARVIS.py`
- Access via http://localhost:8000/ and http://localhost:8000/holo (not file://)
- Static files served at /static/style.css etc, index.html now uses /static/ paths

**RX 9070 XT not detected:**
```bash
rocm-smi  # Linux, should show 9070 XT
# If not, install ROCm 6.2+: https://rocm.docs.amd.com/
# Fallback: still works on CPU, slower
```

---

## Quick Cheat Sheet — Fully Free

| What | Command | Free? | Needs Key? |
|------|---------|-------|------------|
| Install all | `./setup.sh` | ✅ Free | No |
| Brain 14B for 9070 XT | `ollama pull qwen2.5:14b && ollama create jarvis -f Modelfile.9070xt --force` | ✅ Free | No |
| Singular app everything | `python3 JARVIS.py` or `./run.sh 9070xt` | ✅ Free | No |
| Minimal UI | `http://localhost:8000/` | ✅ Free | No |
| Holographic movable | `http://localhost:8000/holo` | ✅ Free | No |
| Voice piper premium | `python -m jarvis.voice.premium --engine piper --preset manina_premium` | ✅ Free | No |
| Wake word 24/7 | `python3 JARVIS.py --always-on` or `python3 cli.py --always-on` | ✅ Free | No |
| Agent | Click ⚡ or `/agent Add JWT auth` | ✅ Free | No |
| Team | Click 👥 or `/team Research X and implement` | ✅ Free | No |
| Codebase search | `search_codebase("auth")` | ✅ Free | No |
| Knowledge search | `search_knowledge("my notes")` | ✅ Free | No |
| Browser control | `browser_navigate("github.com")` | ✅ Free | No |
| Calendar | Place ICS in `workspace/calendar/` → `get_today_events()` | ✅ Free | No |
| Email | Set IMAP app password in `.env` → `fetch_emails()` | ✅ Free (your own provider) | Your app password only |
| Music | Place MP3s in `workspace/music/` → `play_music("jazz")` | ✅ Free | No |
| Speaker zones | `list_speaker_zones()`, `set_zone_volume(lab, 80)` | ✅ Free | No |
| Goals | `add_goal("Build SaaS...")` | ✅ Free | No |

**Everything: 100% FREE, No API Keys, Fully Local, RX 9070 XT 16GB Optimized, Voice MUST BE PIPER.**

---

At your service, Sir.
