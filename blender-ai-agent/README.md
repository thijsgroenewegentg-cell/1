# 🤖 Blender AI Agent — build things in Blender by chatting, for free

An AI agent that builds 3D scenes, models, materials, lighting and animation
**inside your live Blender** — you describe what you want in plain English,
it writes and runs the Blender Python code to create it.

**100% free by default**: it uses [Ollama](https://ollama.com) running on your
own computer, so there's no API key, no account, no credits and no internet
requirement for the AI. Blender itself is free too. Free hosted options
(Groq, Google Gemini) are also built in if you'd rather use those.

## What you get

| File | What it is |
|---|---|
| `addon.py` | Blender add-on. Runs a tiny localhost socket server inside Blender that executes Python (`bpy`) code safely on Blender's main thread. |
| `bridge_standalone.py` | Same bridge, zero install: `blender --python bridge_standalone.py` (works in GUI and headless `--background`). |
| `agent.py` | The AI agent. Connects to Blender, chats with an LLM, and turns the model's tool calls into Blender actions. Standard-library Python only — no pip installs. |
| `examples/demo_scene.py` | A test scene (little house) you can run without any LLM to verify the bridge works. |
| `tests/` | Automated tests for the socket protocol, standalone bridge and agent loop (mocked Blender + LLM). |

## Features

- 🗣️ **Chat to build** — describe what you want in plain English.
- 👁️ **Vision feedback** (`--vision`) — the agent renders its work, looks at
  the image, and fixes visual mistakes (floating objects, bad colors, wrong
  framing) by itself.
- 🖼️ **Reference images** (`--image photo.jpg`) — build from a picture.
- 💾 **Auto saving** — saves `.blend`, renders PNGs and can export
  **GLB/STL/FBX/OBJ** (for games or 3D printing) into an `output/` folder.
- ↩️ **Self-undo** — the agent can undo its own steps when a build goes wrong
  (plus `Ctrl+Z` works for you).
- 🛟 **Provider fallback** — if Ollama isn't running it automatically tries
  Groq, then Gemini (whichever keys you have).
- 🔒 **Approve mode** (`--approve`) — review each piece of code before it runs.
- 🧰 **Zero-install launch** — run Blender with `bridge_standalone.py`, no
  add-on installation required.

## How it works

```
 you  →  agent.py (LLM tool-use loop)  →  localhost:9876  →  addon.py / bridge_standalone.py
        Ollama / Groq / Gemini                                   →  Blender / bpy
```

1. The bridge inside Blender listens on `127.0.0.1` only (never the network).
2. The agent asks the LLM "what should I do in Blender?" and gets back tool
   calls: `get_scene_info`, `execute_blender_code`, `render_and_inspect`,
   `render_preview`, `save_blend`, `export_model`, `undo_blender`,
   `task_complete`.
3. Code runs in Blender; stdout and tracebacks go back to the model, so it
   can **see its results and fix errors**. In vision mode the rendered PNG is
   attached too, so it can **see the actual 3D scene**.
4. Everything is wrapped in undo steps — `Ctrl+Z` in Blender rolls it back.

## Setup (5 minutes, all free)

### 1. Start the bridge in Blender

**Option A — add-on (recommended):**
1. Install [Blender](https://www.blender.org/) (3.6 or newer; 4.x works).
2. **Edit → Preferences → Add-ons → Install from Disk…** and pick `addon.py`.
3. Tick **AI Agent Bridge**, then in the 3D viewport press **N**, open the
   **AI Agent** tab, and click **Start AI Agent Server** (default port 9876).

**Option B — zero install:**
```bash
blender --python bridge_standalone.py
```
(Also works headless on a server: `blender --background --python bridge_standalone.py -- --port 9876`)

### 2. Install the free local AI (Ollama)

1. Download and install [Ollama](https://ollama.com) (Windows/macOS/Linux).
2. Pull a code-capable model (in a terminal):

   ```bash
   ollama pull qwen2.5-coder:7b
   ```

   (No GPU? `qwen2.5-coder:3b` works too. More RAM/greater quality:
   `qwen2.5-coder:14b`.)

3. **Optional, for vision** (agent sees and checks its own renders):

   ```bash
   ollama pull llama3.2-vision:11b
   ```

   Then add `--vision` to your commands. Note: tool use in pure vision models
   varies; if the local vision model doesn't call tools, use the free
   **Groq** or **Gemini** provider — `gemini-2.0-flash` and Groq Llama-4 Scout
   do vision *and* tool calling reliably.

You need Python 3.9+ for `agent.py` (macOS/Linux already have it; on Windows
use `py agent.py ...` or install from python.org).

### 3. Build something!

```bash
cd blender-ai-agent
python agent.py "build a cozy wooden cabin with a smoking chimney and a tree next to it"
```

Watch Blender — the agent creates objects, materials, lights and a camera step
by step, then saves a `.blend` and a render PNG into the `output/` folder.

With vision (it checks its own work and fixes problems):

```bash
python agent.py --vision "build a red sports car on an asphalt road and make it look good"
```

Build from a reference photo:

```bash
python agent.py --vision --image my_car_photo.jpg "model this car"
```

Ask for files for games / 3D printing (it exports automatically when asked):

```bash
python agent.py "build a low-poly chess knight and export it as STL for 3D printing"
```

Review every piece of code before it runs (safety):

```bash
python agent.py --approve "build a medieval castle"
```

### Verify the bridge without any AI

```bash
python agent.py --exec examples/demo_scene.py
```

A little house with a roof, door, grass, sun and camera should appear in Blender.

## Usage reference

```bash
# chat-style request (default: free local Ollama)
python agent.py "make a low-poly windmill on a hill"

# vision mode + reference image
python agent.py --vision "build a futuristic city block, then check the render"
python agent.py --vision --image reference.jpg "build something like this"

# review every code action before it runs
python agent.py --approve "build a chess set"

# interactive mode (describe many things in one session)
python agent.py

# force a provider, or use free hosted alternatives:
python agent.py --provider ollama "build a chess set"
GROQ_API_KEY=gsk_...   python agent.py --provider groq   "build a chess set"
GEMINI_API_KEY=AIza... python agent.py --provider gemini "build a space station"

# other options
python agent.py --model qwen2.5-coder:14b "a medieval castle"   # different model
python agent.py --port 9900 "..."                               # match the bridge port
python agent.py --max-iters 50 "..."                            # more steps for complex builds
python agent.py --no-fallback "..."                            # don't auto-switch providers
```

Interactive mode commands: type your request and press Enter; `/scene` prints
scene info, `/undo` undoes the last step, `/render` renders, `/save` saves a
`.blend`, `/quit` exits.

### Free providers

| Provider | Cost | How |
|---|---|---|
| **Ollama** (default) | Free, local, offline | `ollama pull qwen2.5-coder:7b` |
| **Groq** | Free tier, cloud | free key at console.groq.com/keys → set `GROQ_API_KEY` |
| **Gemini** | Free tier, cloud | free key at aistudio.google.com/apikey → set `GEMINI_API_KEY` |
| OpenAI | paid (listed for convenience) | set `OPENAI_API_KEY` |

Any other OpenAI-compatible server works too: `--base-url http://...:1234/v1`.

## Prompt tips for better results

- Be concrete: *"a wooden dining table, 2m long, with four chairs, a mug on top"*.
- Ask for materials and lighting: *"…with a PBR wood material, a window light, and a camera"*.
- Complex scenes benefit from iterative chat: build the main object first,
  then ask for additions ("now add a leather chair beside it and a rug under it").
- Something went wrong? Press `Ctrl+Z` in Blender, or ask the agent to fix it
  ("the roof is inside the walls, move it up"), or restart the server and
  the agent for a fresh scene.

## Security

The server binds to `127.0.0.1` and never to your network — only programs on
your own machine can connect. The agent can run arbitrary Blender Python
code in your session, which is the point; just click **Stop** in the add-on
panel when you're done, or use the add-on's shutdown command.

## Troubleshooting

- **"Could not connect to Blender"** — start the server in the add-on panel
  first; check the port matches (`--port`).
- **"Cannot reach the LLM"** — is Ollama installed and running? Did you
  `ollama pull` a model? The agent prints a hint on failure.
- **Model says it "can't build things" instead of using tools** — use a
  tool-capable model: `qwen2.5-coder:7b`, `llama3.1:8b`, Groq's
  `llama-3.3-70b-versatile`, or `gemini-2.0-flash`.
- **Vision model doesn't call tools / only chats about the image** — some
  local vision models are weak at function calling. Use `--provider gemini`
  or `--provider groq` (both free and reliable for vision + tools).
- **Slow AI** — 7B models on CPU are fine but take a few seconds per step;
  try `qwen2.5-coder:3b`, or use the free Groq provider (very fast).
- **Undo a step** — `Ctrl+Z` in Blender, `/undo` in interactive mode, or tell
  the agent "undo that".
- **Where are the files?** — renders, `.blend` saves and exports go to the
  `output/` folder next to `agent.py`; the paths are also printed in the terminal.

## Development / tests

```bash
python3 tests/test_agent.py            # agent loop, vision, JSON repair, fallback
python3 tests/test_addon_protocol.py   # real addon.py server (save/export/...) vs fake bpy
python3 tests/test_standalone.py       # zero-install standalone bridge launch
```

No Blender or LLM is needed to run the tests — everything is mocked.

## License

MIT
