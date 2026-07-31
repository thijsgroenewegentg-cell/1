# J.A.R.V.I.S 4.0 — 100% FREE • Self-Evolving • Movable Holo UI • Premium Voice (Free) • Coding Agent Team

> "Now I make myself better, Sir. And fully free."

**100% FREE, Local, Private, No API Keys, No Paid Services.** Every feature works offline with Ollama.

![Free](https://img.shields.io/badge/100%25%20FREE-No_API_Keys-black) ![Local](https://img.shields.io/badge/100%25%20Local-Private-black) ![Ollama](https://img.shields.io/badge/Brain-Ollama-blue) ![Self-Evolving](https://img.shields.io/badge/Brain-Self_Evolving-cyan) ![Movable UI](https://img.shields.io/badge/UI-Movable_Holographic-00d4ff)

---

## ✨ What is This?

A real-life J.A.R.V.I.S. inspired by Manina Labs (@maninalabs — building real-life JARVIS, 24.9K followers [1](https://www.tiktok.com/@maninalabs)), but **100% free and open source, no kits, no paid APIs.**

- **Ollama brain** `qwen2.5:7b` — fully local LLM, function calling
- **Self-learning** — vector memory, auto-extracts facts, user profile, reflection
- **Self-evolution** — self-critic 0-10, prompt evolution, tool forging, memory optimization
- **Self-editing** — can edit own code with backup + compile check + rollback — rewrites his own mind
- **Autonomous Coding Agent** — plans, codes, tests, fixes, commits for hours like Devin
- **Codebase RAG** — knows entire repo via semantic search
- **Git superpowers** — status, diff, log, commit, PR via gh
- **Always-on wake word** — says "Jarvis" anytime, 24/7 listening via openWakeWord (free local ONNX) → whisper tiny → google fallback
- **Proactive Agent** — morning briefing 8:30, evening summary, git watcher, routine suggestions, desktop notifications
- **Multi-Agent Team** — Planner, Researcher, Coder, Reviewer, Supervisor collaborate on complex tasks
- **Movable Holographic UI** — Manina Labs style, draggable panels, holographic glow, save layout
- **Premium Voice — 100% FREE** — deep British cinematic with bass boost + reverb + chorus via pydub, no API key. Edge TTS default free, Piper best free offline (ONNX), XTTS free local cloning. ElevenLabs/OpenAI optional paid, NOT needed.

Every feature: **FREE, local, no keys.**

---

## 🚀 Quick Start — Fully Free

```bash
git clone https://github.com/thijsgroenewegentg-cell/1.git
cd 1
./setup.sh         # pulls qwen2.5:7b + nomic-embed-text + creates jarvis model, all free

ollama serve       # in another terminal, if not running

# Run — all free, no keys
python web/server.py          # Minimal UI http://localhost:8000 + Holo UI at /holo
python cli.py                 # CLI
python cli.py --always-on     # Always-on wake word, say "Jarvis" anytime
python cli.py --proactive     # Proactive briefing + git watcher
python cli.py --team "Research best auth lib and implement"  # Multi-agent team
python cli.py --agent "Add JWT auth"  # Autonomous coding agent
```

**No API keys needed. Ever.**

Optional free offline TTS upgrades (still free, no keys):
```bash
# Best free offline TTS - British, high quality
pip install piper-tts --break-system-packages
python -m piper.download_voices en_GB-alan-medium --data-dir data/piper_models
# Then .env: TTS_ENGINE=piper

# Free local voice cloning - clone Paul Bettany
pip install TTS --break-system-packages  # 2GB model
# Place 5-10 sec WAV of target voice in data/voices/manina_premium.wav
# Then .env: TTS_ENGINE=xtts
```

---

## 🎨 UIs — All Free

- **Minimal:** `/` — Linear/ChatGPT style, 720px centered, floating input. `python web/server.py`
- **Movable Holographic:** `/holo` — Manina Labs style, draggable panels, grid + glow orbs, save layout. Top bar ◫ Holo button.
  - Panels: Chat, Codebase, Git, Agent, Team, Briefing, Memory, Evolution, Terminal, System, Self-Edits, Voice Lab
  - Drag, resize, minimize, close, + Panel menu, Save Layout
- **Python Desktop:** `python desktop/python/main.py` — customtkinter minimal + tray
- **Electron:** `cd desktop/electron && npm install && npm start` — global hotkey Ctrl+Shift+J
- **CLI:** `python cli.py --voice`, `--always-on`, `--proactive`, `--team`, `--agent`

---

## 🎙️ Premium Voice — 100% Free

Manina Labs premium = deep British cinematic with reverb + bass. We do it **free, no API key**:

| Engine | Cost | Quality | Offline? | Setup |
|--------|------|---------|----------|-------|
| **edge + FX (default)** | FREE, no key | 8/10 premium | No, free MS | Works out of box: `TTS_ENGINE=edge`, `PREMIUM_VOICE_STYLE=manina_premium` |
| **piper** | FREE | 9/10 best offline | Yes 100% | `pip install piper-tts && python -m piper.download_voices en_GB-alan-medium` → `TTS_ENGINE=piper` |
| **xtts** | FREE | 10/10 clone any voice | Yes 100% after 2GB download | `pip install TTS`, place WAV sample in `data/voices/manina_premium.wav` → `TTS_ENGINE=xtts` |
| **pyttsx3** | FREE | 5/10 robotic | Yes | Fallback |
| elevenlabs | PAID optional | 10/10 | No | NOT needed, only if you want |
| openai | PAID optional | 9/10 | No | NOT needed |

**Voice presets (all free):** `manina_premium` (deep cinematic), `jarvis_classic` (Paul Bettany), `jarvis_deep` (commanding), `friday` (Irish female), `manina_blender` (clear technical)

Premium FX via `pydub` (free): bass boost (low-pass 250Hz overlay), reverb (echo 80ms decay), chorus (15ms detune), +1.5dB loudness — makes edge sound premium, Manina style.

Test:
```bash
python -m jarvis.voice.premium --engine edge --preset manina_premium --text "Good evening, Sir. Premium voice model online, 100 percent free, no API keys needed."
```

---

## 🧠 Features — All Free

**Brain:** `qwen2.5:7b` (best tools), `llama3.1:8b`, `mistral-nemo`, `gemma2:9b` — local Ollama
**Tools (30+):** time, system, web search DuckDuckGo (free), weather wttr.in (free), memory, files, code exec, shell, timer, search_codebase (vector), analyze_codebase, git_*, run_tests, format_code, improve_self, create_new_tool, read_self_code, edit_self_code, etc — all free
**Memory:** `data/vectors.json` vector memory + `data/user_profile.json` + `data/codebase_vectors.json` — embeddings via `nomic-embed-text` (free) or hash fallback (free)
**Wake Word:** `openwakeword` ONNX local (free) → faster-whisper tiny (free) → google (free)
**Proactive:** APScheduler (free) + plyer notifications (free)
**Team:** 5 agents with own brain copies, no paid framework

---

## ⚙️ Config — Fully Free .env

```env
# ALL FREE, NO KEYS NEEDED
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=jarvis
TTS_ENGINE=edge
PREMIUM_VOICE_STYLE=manina_premium
STT_ENGINE=faster-whisper
ALWAYS_ON_ENABLED=false
PROACTIVE_ENABLED=true
TEAM_ENABLED=true
EVOLUTION_ENABLED=true
SELF_EDIT_ENABLED=true

# OPTIONAL PAID - NOT NEEDED, LEAVE EMPTY FOR FREE:
# ELEVENLABS_API_KEY=
# OPENAI_API_KEY=
```

---

## 🧬 Structure

```
.
├── web/
│   ├── index.html (minimal) + /static/style.css + /static/app.js
│   ├── holo.html (movable holographic) + holo.css + holo.js
│   └── server.py (+ /api/voice/presets, /api/voice/speak, /holo, /api/*)
├── jarvis/
│   ├── voice/premium.py (100% free: edge+FX, piper, xtts, pyttsx3)
│   ├── voice/wakeword.py (free: openwakeword ONNX)
│   ├── proactive/ (free: scheduler, briefing, git watcher)
│   ├── agents/ (free: planner, researcher, coder, reviewer, supervisor, team)
│   ├── coding/ (free: codebase RAG, git tools, agent, etc)
│   ├── learning/ (free: vector store, profile, auto memory)
│   ├── evolution/ (free: self-critic, tool forger, self-editor)
│   └── tools/ (30+ free tools)
└── data/
    ├── voices/ (place WAV samples for free XTTS cloning)
    └── piper_models/ (free Piper ONNX models)
```

---

## 🔒 Privacy — 100% Free & Local

No API keys, no cloud, no telemetry. All in `data/`. Ollama local. Even TTS premium FX is local via pydub. Edge TTS is free Microsoft service, no key. Piper and XTTS are fully offline.

---

## Roadmap — All Free

- [x] Minimal UI + Movable Holographic UI (Manina Labs style)
- [x] Premium Voice 100% free (edge+FX, piper, xtts)
- [x] Always-on wake word free (openwakeword)
- [x] Proactive free (morning briefing, git watcher)
- [x] Multi-agent team free
- [x] Self-evolving + self-editing free
- [x] Coding agent + codebase RAG free
- [ ] Vision (llava:7b free local) — see desk
- [ ] Document RAG — index PDFs free
- [ ] Mobile app via Tailscale (free)

---

> `ollama serve` → `./run.sh web` → Open `/holo` → Drag panels → Say "Jarvis" (if --always-on) → Watch him evolve, all 100% free, Sir.
