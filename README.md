# J.A.R.V.I.S 3.0 - Self-Evolving • Minimal • Local

> "Now I make myself better, Sir."

Fully local, private, **self-learning + self-evolving** JARVIS built on Ollama. Minimal UI, super smart, and he rewrites his own mind to get better.

![Local](https://img.shields.io/badge/100%25%20Local-Private-black) ![Minimal](https://img.shields.io/badge/UI-Minimal-white) ![Self-Learning](https://img.shields.io/badge/Brain-Self_Learning-blue) ![Self-Evolving](https://img.shields.io/badge/Brain-Self_Evolving-cyan)

---

## ✨ What's New in 3.0 - Self-Evolution

**JARVIS makes himself better. Automatically.**

Previous 2.0: He learned about *you*.
Now 3.0: He learns about *himself* and improves.

**The Self-Improvement Loop:**

1. **Performance Tracker** - Every response: latency, tool success, satisfaction
2. **Self-Critic** - Scores own response 0-10 via heuristic + LLM: "Too verbose, should have used tool"
3. **Should Evolve?** Triggers if satisfaction <0.5, success <80%, trend declining, critic <6, or every 50 msgs, or user says "improve yourself"
4. **Evolution Engine** (background):
   - **Prompt Evolution**: LLM proposes better prompt: "Be concise for short questions" → saved to `data/evolution/prompt_additions.json` → injected next turn. Personality evolves.
   - **Tool Forging**: Detects missing capability (Spotify, email, calendar...). LLM generates Python tool code, syntax checks, saves to `jarvis/tools/`, registers in `TOOL_MAP`. New ability forged.
   - **Memory Optimization**: Prunes low-value vectors if >800

All evolutions logged + backed up to `data/backups/`. Safe whitelist.

See `EVOLUTION.md` for full architecture.

**You can say:** "JARVIS, improve yourself", "Analyze your performance", "You need a Spotify tool" - and he will.

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

## 🧬 Project Structure 3.0

```
.
├── Modelfile
├── EVOLUTION.md              # How self-evolution works
├── requirements.txt / setup.sh / run.sh / cli.py
├── jarvis/
│   ├── brain.py              # Tool loop + learning + evolution injection
│   ├── config.py             # + LEARNING_ENABLED, EVOLUTION_ENABLED
│   ├── learning/             # Self-learning
│   │   ├── vector_store.py, user_profile.py, auto_memory.py, reflection.py, engine.py
│   ├── evolution/            # NEW 3.0 - Self-evolving
│   │   ├── self_critic.py    # Scores own responses 0-10
│   │   ├── performance_tracker.py # Latency, success, trend
│   │   ├── self_editor.py    # Safe file edits with backups
│   │   ├── tool_forger.py    # LLM forges new tools
│   │   └── evolution_engine.py # Orchestrator
│   ├── tools/                # + evolution_tools.py (improve_self, create_new_tool...)
│   └── voice/ & app.py
├── web/                      # Minimal UI 3.0 + evolution
│   ├── server.py             # + /api/evolution/status, history, improve
│   ├── index.html            # + 🧬 evolution count, improve button
│   ├── style.css
│   └── app.js                # + evolution modal, toasts
├── desktop/
│   ├── python/main.py        # Minimal + evolution stats
│   └── electron/
└── data/
    ├── vectors.json, user_profile.json, reflections.json
    └── evolution/
        ├── prompt_additions.json  # Evolved prompts
        ├── tool_forge_log.json
        ├── performance.json
        ├── evolution_log.json
    └── backups/              # Backups of edited files
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

- [x] Minimal clean UI 2.0
- [x] Self-learning: vector memory, auto-extract, profile, reflection
- [x] Self-evolution 3.0: self-critic, prompt evolution, tool forging, performance tracking
- [x] Electron + Python desktop with tray
- [x] Global hotkey Ctrl+Shift+J
- [ ] Vision (llava) - see your desk
- [ ] Proactive: morning briefing from routines + evolution
- [ ] Home Assistant
- [ ] Voice wake word always-on in tray
- [ ] Full self-code evolution (edit brain.py itself)

---

Built with bare metal and obsession. "Sometimes you gotta run before you can walk."

> `ollama serve` -> `./run.sh web` -> Say "My name is Alex" -> Ask "What do you know about me?" -> Watch him learn.
