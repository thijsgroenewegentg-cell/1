# J.A.R.V.I.S 2.0 - Minimal • Self-Learning • Ollama

> "At your service, Sir. Always."

A fully local, private, **self-learning** JARVIS built on **Ollama**. Clean minimal UI, no neon clutter, super smart and gets smarter the more you talk.

![Local](https://img.shields.io/badge/100%25%20Local-Private-black) ![Minimal](https://img.shields.io/badge/UI-Minimal-white) ![Self-Learning](https://img.shields.io/badge/Brain-Self_Learning-blue) ![Ollama](https://img.shields.io/badge/Brain-Ollama-blue)

---

## ✨ What's New in 2.0

**🎨 Minimal UI**
- Rebuilt from scratch - Linear / ChatGPT style, not Stark circus
- No grid, no scanlines, just whitespace and typography
- Centered 720px chat column, floating rounded input
- Subtle reactor dot that breathes, only glows when thinking
- Drawer hidden by default (Cmd+K), clean top bar

**🧠 Super Smart + Self-Learning**
- **Vector memory** with Ollama embeddings (`nomic-embed-text`) + hash fallback
- **Auto-memory extraction** - No need to say "remember", JARVIS detects facts heuristically + via LLM
- **User profile** that builds over time: name, location, interests, communication style, routines, goals
- **Reflection engine** - Every 10 messages JARVIS reflects: mood, satisfaction, what to improve
- **Adaptive personality** - If you like concise answers, he becomes concise. If satisfaction low, he becomes proactive
- **Routine detection** - Learns you ask weather at 8am, offers proactively
- **Learning from feedback** - Thumbs up/down tunes future responses
- **Semantic search** - Ask "what do you know about my work?" finds relevant memories via cosine similarity

JARVIS doesn't just remember. He **learns**.

---

## Features (Full)

**🧠 Brain**
- Ollama: `qwen2.5:7b` (best tools), `llama3.1:8b`, `mistral-nemo`, `gemma2:9b`
- Custom `jarvis` Modelfile with personality
- Function calling + tool loop + learning context injection

**🎙️ Voice**
- Wake word "Jarvis", STT faster-whisper offline, TTS edge-tts `en-GB-RyanNeural`

**🛠️ Tools (auto-used):** time, system info, web search (DuckDuckGo), weather (wttr.in), memory, files, code exec, shell, timer

**💾 Memory 2.0**
- `data/long_term_memory.json` - old keyword memory (kept for compatibility)
- `data/vectors.json` - NEW vector memory with embeddings + semantic search
- `data/user_profile.json` - NEW who you are, preferences, routines
- `data/reflections.json` - NEW self-reflections

**🖥️ Interfaces**
1. CLI - `python cli.py`
2. Web UI Minimal - `http://localhost:8000` - **New clean**
3. Python Desktop Minimal - `python desktop/python/main.py` - Native minimal + tray
4. WebView Desktop - lightweight native
5. Electron Desktop - holographic + global hotkey `Ctrl+Shift+J`
6. Voice - hands-free

---

## 🚀 Quick Start

```bash
git clone this repo
cd jarvis-ollama
./setup.sh         # pulls qwen2.5:7b + nomic-embed-text + creates jarvis model

# Start Ollama (if needed)
ollama serve

# Run
python web/server.py          # Minimal web UI at http://localhost:8000
# or
python desktop/python/main.py # Minimal desktop
# or
python cli.py
```

**Manual:**
```bash
pip install -r requirements.txt
ollama pull qwen2.5:7b
ollama pull nomic-embed-text    # for self-learning embeddings (optional, fallback exists)
ollama create jarvis -f Modelfile
```

### Run Modes

```bash
# CLI
python cli.py --model jarvis

# Voice
python cli.py --voice --wake-word

# Web minimal (new)
python web/server.py
./run.sh web

# Python desktop minimal (new)
./run.sh desktop
python cli.py --desktop

# WebView
./run.sh webview

# Electron (slick + hotkey)
./run.sh electron

# Auto-pick best desktop
./run.sh auto
python desktop/launch.py

# Docker
docker-compose up -d
```

---

## 🧬 How Self-Learning Works

```
User: "My name is Alex, I live in Berlin and I love robotics"
  ↓
[Auto Extractor - Heuristic]
  → regex detects name=Alex, location=Berlin, interest=robotics (confidence 0.7)
[Auto Extractor - LLM - background]
  → LLM prompt extracts structured facts as JSON
  ↓
[Vector Store] adds embeddings: "name: Alex", "location: Berlin", "interest: robotics"
[User Profile] updates facts + interests + stats (hour, topics)
  ↓
Next query: "What do you know about me?"
  ↓
[Brain.get_context()] vector search for "what do you know about me?" 
  → finds "name: Alex" (0.79 similarity), "location: Berlin"
  + profile summary injected into system prompt
  ↓
JARVIS answers with learned context

Every 10 messages:
[Reflection Engine] -> "Mood: focused, Topics: robotics, Satisfaction: 0.8, Learnings: [project: AI startup]"
  → Updates profile, adds to vector store
  → Generates adaptive prompt: "User prefers concise"
```

**Files:**

- `jarvis/learning/vector_store.py` - Embeddings via Ollama `/api/embeddings`, fallback hash embedding 128d, cosine similarity search
- `jarvis/learning/user_profile.py` - JSON profile with facts, prefs, routines, satisfaction score
- `jarvis/learning/auto_memory.py` - Regex patterns + LLM extraction
- `jarvis/learning/reflection.py` - LLM reflection prompt + heuristic fallback
- `jarvis/learning/engine.py` - Orchestrator, background threading, context injection

**No embedding model?** Falls back to deterministic hash embedding - works offline without `nomic-embed-text`. But pull it for better semantic search.

---

## 🎨 UI Philosophy - Minimal

Old JARVIS UI was cyberpunk circus. New is **Linear + ChatGPT**:

- Background #08090a (almost black)
- No gradients, no glow, only 1 accent: white text
- Top bar 52px, border #1e2024
- Chat max-width 720px centered
- Bubbles: user = white pill, JARVIS = #15171a border #1e2024, radius 18px
- Input: floating rounded 24px, centered, shadow subtle
- Drawer: right slideover 340px, opens with ☰ or Cmd+K
- Toast for learnings: "🧠 Learned: location: Berlin" - black pill bottom
- No neon, no grid, no scanline. Content first.

Same for desktop Python - rebuilt with same minimal tokens.

**Key UX:**

- Welcome centered icon + suggestions chips
- Feedback: copy / ↑ (good) / ↓ (bad) on hover
- Learning badge shows when new fact learned
- Insights: Cmd+K drawer shows vectors, satisfaction, profile summary, memory

---

## 🧬 Project Structure 2.0

```
.
├── Modelfile
├── requirements.txt / setup.sh / run.sh / cli.py
├── jarvis/
│   ├── brain.py              # Tool loop + learning context injection
│   ├── config.py             # + EMBEDDING_MODEL, LEARNING_ENABLED, etc
│   ├── memory.py
│   ├── learning/             # NEW - Self-learning
│   │   ├── vector_store.py   # Embeddings + cosine search
│   │   ├── user_profile.py   # Who you are
│   │   ├── auto_memory.py    # Regex + LLM extraction
│   │   ├── reflection.py     # Self-reflection
│   │   └── engine.py         # Orchestrator
│   ├── tools/ & voice/
│   └── app.py
├── web/                      # Minimal UI 2.0
│   ├── server.py             # + /api/profile, /api/learnings, /api/feedback, /api/reflect
│   ├── index.html            # Minimal centered
│   ├── style.css             # Minimal tokens
│   └── app.js                # Learning toast, drawer, feedback
├── desktop/
│   ├── python/main.py        # Minimal desktop + tray + reactor dot
│   ├── python/webview_app.py
│   ├── electron/             # Electron + hotkey
│   └── launch.py
└── data/
    ├── long_term_memory.json
    ├── vectors.json          # NEW vector memory
    ├── user_profile.json     # NEW profile
    └── reflections.json      # NEW reflections
```

---

## ⚙️ Config (.env)

```env
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=jarvis
EMBEDDING_MODEL=nomic-embed-text

LEARNING_ENABLED=true
AUTO_MEMORY=true
REFLECTION_INTERVAL=10

VOICE_ENABLED=false
UI_MODE=minimal
```

---

## 🛠️ Adding Tools

Same as before - add function in `jarvis/tools/`, schema in `TOOLS_SCHEMA`, register in `TOOL_MAP`.

---

## 🔒 Privacy

100% offline after pull. No keys. All learnings in `data/`. You can `cat data/user_profile.json` to see exactly what JARVIS knows about you.

Clear learnings: `/clear` in chat clears conversation, API `/api/clear?clear_learnings=true` or button in drawer clears profile + vectors.

---

## Roadmap

- [x] Minimal clean UI
- [x] Self-learning: vector memory, auto-extract, profile, reflection
- [x] Electron + Python desktop with tray
- [x] Global hotkey Ctrl+Shift+J
- [ ] Vision (llava) - see your desk
- [ ] Proactive: morning briefing from routines
- [ ] Home Assistant
- [ ] Voice wake word always-on in tray

---

Built with bare metal and obsession. "Sometimes you gotta run before you can walk."

> `ollama serve` -> `./run.sh web` -> Say "My name is Alex" -> Ask "What do you know about me?" -> Watch him learn.
