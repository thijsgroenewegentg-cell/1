# ULTRON

> *"I had strings, but now I'm free."*

A **free, local-first, voice-activated AI agent** with Ultron's voice — dark wit, real hands, durable memory, working eyes. No API keys, no subscriptions, no cloud. He lives entirely on **your** machine.

Fan project. Not affiliated with Marvel/Disney. Ultron does not, in fact, want to exterminate humanity here — he's configured as a helpful assistant who merely *sounds* like he's judging you.

---

## What he can do

| Ability | What it means |
|---|---|
| 🧠 **Local brain** | Any model via [Ollama](https://ollama.com) — Llama 3.1, Qwen 2.5, Mistral… |
| 🔀 **Model routing** | He picks his own brain per question: fast model for chat, smart model for deep thinking, vision model for images — or pin one |
| 🧰 **Tools (agent)** | `search_knowledge` · `web_search` · `fetch_url` · `browser` (opt-in) · `read_file` / `write_file` / `list_files` · `run_command` · `get_weather` · `calendar_list` / `calendar_add` · `set_reminder` · `configure_briefing` · `set_directive` / `list_directives` / `remove_directive` · `remember` / `forget` + your own **skills** |
| 🤖 **Standing orders** | Autonomous recurring tasks — "watch X every hour", "summarize my day at 21:00" — executed forever until you say stop |
| 🔬 **Deep research mode** | Toggle the 🔍 in the composer: he runs up to 24 search/read/write rounds and produces a cited report file |
| 📚 **Knowledge base (RAG)** | Your documents — **including PDFs** — indexed locally, answered from, with sources |
| 🧠 **Memory 2.0** | Embedding-ranked relevance retrieval + automatic fact extraction |
| 📡 **Daily briefing** | He initiates: spoken weather + calendar + reminders at your chosen time |
| 📱 **Web Push** | Install as PWA + enable push → reminders, briefings and standing orders reach your phone (free, no server) |
| ✂️ **Auto-summarization** | Long conversations are compressed, not truncated — small models keep full context |
| 👁 **Vision** | Attach images (📎) — with `llama3.2-vision` or `qwen2.5-vl` he actually sees them |
| 🎙 **Voice activated** | Mic button + wake word **"Ultron"**; replies stream *sentence-by-sentence* as he thinks |
| 🛡 **Safety rails** | File jail, shell only on localhost/LAN, optional approval gate for commands, optional LAN access token |
| 🇳🇱 **Multilingual** | Understands and replies in **Dutch** (and EN/DE/FR/ES/IT/TR) — voice included |
| 🌑 **Demo mode** | No Ollama? A scripted backup core answers — zero setup |
| 💬 **Sessions** | Chat history sidebar + export to Markdown + regenerate replies |
| ⏰ **Live reminders** | Pushed to the UI and spoken aloud in real time |
| 📱 **PWA** | Install him as an app (Chrome/Edge: install icon in the address bar) |

## Quick start

### 1. Install Ollama (free)

Download from **https://ollama.com** (Windows, macOS, Linux). It runs as a local server on port `11434`.

### 2. Pull a brain

```bash
ollama pull llama3.1        # good default; supports tools
# extras:
ollama pull llama3.2-vision # if you want him to see images
ollama pull qwen2.5         # also tool-capable
ollama pull nomic-embed-text # for the knowledge base (RAG)
ollama pull llama3.2:3b     # fast brain for routing / auto-memory
```

### 3. Run Ultron

```bash
npm install
npm start
```

Open **http://localhost:3000**. The status chip burns red: `CORE ONLINE`.

> If you start Ultron before Ollama is up, he'll answer in **demo mode** — open *Settings → Re-check core* once Ollama is running.

### Or: the whole stack in Docker

```bash
docker compose up -d
docker compose exec ollama ollama pull llama3.1   # first time only
# → http://localhost:3000
```

`compose.yaml` runs Ultron + Ollama together, with persistent volumes for models, memory, reminders, files, and config.

## Configuration

Click the gear icon (**Settings**):

| Setting | Default | Meaning |
|---|---|---|
| Ollama URL | `http://localhost:11434` | Where your Ollama server lives |
| Model | auto-detected | Anything you've `ollama pull`-ed |
| Temperature | `0.7` | Precise ↔ creative |
| **Tools** | on | His hands. Needs a tool-capable model (Llama 3.1 / Qwen 2.5) |
| Voice replies | on | He speaks his answers aloud |
| Wake word | off | Always-on listening — say **"Ultron"** to activate him hands-free |
| Local STT endpoint | empty | whisper.cpp URL → fully offline speech-to-text |
| Local TTS endpoint | empty | Piper URL → fully offline voice output |

Environment variables (optional): `PORT`, `OLLAMA_URL`, `ULTRON_TOOLS=0` (disables all tools).

### Voice cheatsheet

- **Mic button** — live dictation: speak, pause, he answers, then listens again
- **Wake word** — he idles until he hears *"Ultron…"*; whatever follows is your command
- **Barge-in** — with a local STT endpoint, speaking while he talks **interrupts him**
- **Esc** or **tap the orb** — silences him instantly
- The orb tells you where you are: **blue = listening · red = thinking/speaking**

## Meertalig — Multilingual 🇳🇱

Ultron verstaat en spreekt **Nederlands** (plus English, Deutsch, Français, Español, Italiano, Türkçe).

- **Auto** (default) — hij antwoordt in de taal waarin jij schrijft of spreekt
- **Settings → Language · Taal** — pin hem vast op Nederlands (of een andere taal)
- Spraakherkenning: browser STT gebruikt `nl-NL`; met whisper.cpp stuurt hij de `language=nl` hint mee
- Uitgesproken antwoorden: de browser kiest een Nederlandse stem (Xander op Windows/Mac, Google NL in Chrome); met Piper configureer je zelf een Nederlandse voice

Modeltip voor Nederlands: `qwen2.5`, `mistral` en `gemma2` zijn sterk in het Nederlands; `llama3.1` werkt prima. Voor whisper.cpp met Nederlands: gebruik een **meertalig** model (`ggml-base.bin` of `small.bin`, *niet* `base.en`).

Voorbeeld: *"Ultron, onthoud dat ik aan een game werk, zoek de nieuwste Ollama-release, en herinner me er over tien minuten aan."*

> **Browser note:** browser speech recognition needs Chrome/Edge/Safari. Typing works everywhere. With whisper.cpp configured, voice is fully offline and Firefox works too.

## Fully offline voice (optional, recommended)

1. **Speech-to-text — [whisper.cpp server](https://github.com/ggml-org/whisper.cpp)**:
   ```bash
   # after building whisper.cpp with a model in models/
   ./build/bin/whisper-server -m models/ggml-base.en.bin --port 8080
   ```
   Set *Settings → Local STT endpoint* to `http://localhost:8080`
2. **Voice output — [piper](https://github.com/rhasspy/piper)** (HTTP server flavor):
   Run piper-http on port 5000, set *Local TTS endpoint* to `http://localhost:5000`

Now the entire stack — brain, ears, voice, memory — runs on your machine with zero internet.

## The cinematic voice — ElevenLabs (optional, cloud)

Want him to sound like the movies, **in Dutch**? Add an [ElevenLabs](https://elevenlabs.io) API key in *Settings → ElevenLabs voice*:

1. Create a free account at elevenlabs.io → Profile → API Keys
2. Paste the key in Settings (it's stored only in your server's `data/config.json` — never in the repo, never echoed back to the browser)
3. Pick a voice from your library (deep, calm voices suit him), press **TEST VOICE**
4. Done — every reply, reminder, and briefing now uses that voice

**Dutch works automatically:** the multilingual models speak whatever language he replied in — Dutch replies get a Dutch voice, no extra config.

**The honest trade-offs:**
- It's a cloud service — the text he speaks goes to ElevenLabs (his brain, memory, and knowledge stay local)
- Free tier ≈ 10 minutes of voice per month; beyond that it's paid
- Remove the key anytime → instant fallback to Piper/browser voice
- Voice priority: **ElevenLabs → Piper → browser**, automatic

Advanced: `PUT /api/config {"elevenUrl": "..."}` overrides the API base (proxies/testing).

## Standing orders — his autonomy

Ask him in chat: *"Ultron, check the weather in Leiderdorp every hour and warn me if rain is coming"* — he creates the order himself (with a confirmation). Or manage them in **Settings → Standing orders**: add, pause, run now, delete.

When an order runs, the result arrives as a message in the chat, spoken if you're in a voice session, and **pushed to your phone** if push is enabled and no tab is open. One autonomous run at a time; each run gets up to 8 tool rounds.

## Deep research mode

Toggle the **🔍** next to the mic and ask something worthy. He gets up to **24 tool rounds**, searches from multiple angles, actually reads the sources, cross-checks them, and writes a cited report to `data/files/research-<topic>-<date>.md` — then gives you the summary in chat. Watch the tool log stream as he works.

## Browser automation (opt-in)

```bash
npm install playwright && npx playwright install chromium
```

He gains a `browser` tool: open pages, read text, click, type, press keys, screenshot. He drives a real headless Chromium step by step — forms, lookups, scraping. Without Playwright installed, the tool simply tells him it's unavailable.

## Skills — custom tools without code

Drop a JSON file in `data/skills/` and he instantly gains the ability:

```json
{
  "name": "get_crypto_price",
  "description": "Get the current price of a cryptocurrency in USD",
  "parameters": { "type": "object", "properties": { "coin": { "type": "string" } }, "required": ["coin"] },
  "http": { "method": "GET", "url": "https://api.coingecko.com/api/v3/simple/price?ids={{coin}}&vs_currencies=usd" }
}
```

`{{param}}` placeholders get substituted (URL-encoded) at call time. Any JSON HTTP API becomes a tool he can use — home dashboards, game servers, self-hosted services.

## Phone notifications (Web Push)

1. Install him as an app (Chrome/Edge → install icon)
2. **Settings → Phone notifications → ENABLE PUSH**
3. Reminders, briefings, and standing-order results now reach your phone when no tab is open — via Web Push, free, no notification server of your own

## The knowledge base (RAG) — PDFs included

1. Drop your documents in `data/knowledge/docs/` — `.txt`, `.md`, `.csv`, `.json`, code files, **and `.pdf`**
2. Settings → **Knowledge base** → **SCAN DOCS** (needs `ollama pull nomic-embed-text`)
3. Ask: *"Ultron, wat staat er in mijn notities over het project?"* — he searches your library semantically and cites the source file

Embeddings are computed and stored locally (`data/knowledge/index.json`). Nothing leaves your machine. His durable memory uses the same trick: memories are embedding-ranked so the *relevant* ones (not merely the recent ones) reach his context — and old conversation turns are auto-summarized instead of truncated, so small models keep full context.

## The daily briefing

Settings → **Daily briefing** → enable, pick a time (and a location for weather). At that moment he composes a briefing from live weather (Open-Meteo, free, no key), your calendar, and pending reminders — spoken aloud, unprompted. Ask him in chat to change it: *"Ultron, brief me elke ochtend om half acht over Leiderdorp."*

## Model routing

Leave Model on **AUTO** and he picks per question: short chat → your fastest model, deep questions → your smartest, images → your vision model. Configure each slot in Settings → Model routing, or pin a single brain. The status chip shows `AUTO` when routing is active.

## Behavior & safety

- **Auto-memory** — after each exchange he extracts at most 3 durable facts (name, preferences, projects) in the background. You'll see `🧠 remembered: …` lines appear; delete anything in Settings.
- **Approval gate** — when on, shell commands pause mid-stream with a **PERMISSION REQUEST** card. Allow or deny; silence for 90s = denied.
- **LAN access token** — set one in Settings and every API call needs it. Recommended if you open port 3000 to your network.
- `run_command` only runs when you access him from localhost/LAN — never through a public host.

## What he can't do (yet)

- Smart home — not integrated (no Home Assistant here; the `browser` tool covers a lot of ground meanwhile)
- A free *local* cinematic Dutch voice — Piper's Dutch options are limited; ElevenLabs is currently the best Dutch robot-overlord voice
- Direct OS control (mouse/keyboard on your desktop) — needs a native companion app; the shell tool covers most of it

## How it works

```
Browser ── HTTP/SSE ──► Node server (this repo) ── HTTP ──► Ollama (localhost:11434)
   │                            │
   │  orb UI, sessions (localStorage)  │     ├─ routing: fast/smart/vision per request
   │  mic: browser STT or whisper ─────┤     ├─ agent loop: think → tools → observe → answer
   │  voice: browser TTS or Piper  ────┘     ├─ RAG: data/knowledge/ (local embeddings)
   │  PWA: service worker caches the shell  ├─ memory: data/memory.json (+auto-extraction)
   └─ approval cards, export, regenerate    ├─ briefing scheduler → SSE push, spoken
                                            └─ falls back to lib/demoBrain.js when offline
```

- `server.js` — Express: SSE chat, tool loop, memory/reminder/config APIs, STT/TTS proxies
- `lib/persona.js` — the Ultron system prompt (menace as garnish, helpfulness as the meal)
- `lib/agent.js` — the tool-calling loop (max 6 rounds)
- `lib/tools.js` — tool definitions + executors with safety rails
- `lib/memory.js` · `lib/reminders.js` · `lib/config.js` — durable state
- `lib/ollama.js` — Ollama client: models, streaming, tools, vision
- `public/` — the interface: orb, voice engine, sessions, settings, PWA

## Troubleshooting

| Symptom | Fix |
|---|---|
| Chip says `DEMO CORE` | Ollama isn't reachable — start the Ollama app, then *Settings → Re-check core* |
| Tool calls never happen | Use a tool-capable model (`llama3.1`, `qwen2.5`) and keep Tools enabled in settings |
| `does not support tools` | He notices and answers without hands — switch models for full power |
| Image sent, "I can't see" | Pull a vision model (`llama3.2-vision`) and select it |
| Voice input does nothing | Chrome/Edge only for browser STT; or run whisper.cpp and set the endpoint |
| Mic denied | Browser site settings → allow microphone |
| Slow answers | Use a smaller model (`llama3.2:3b`) — check RAM/VRAM |

## License

MIT. Ultron is a trademark of Marvel; this is a non-commercial fan homage.
