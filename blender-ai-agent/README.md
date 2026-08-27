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
| `agent.py` | The AI agent. Connects to Blender, chats with an LLM, and turns the model's tool calls into Blender actions. Standard-library Python only — no pip installs. |
| `examples/demo_scene.py` | A test scene (little house) you can run without any LLM to verify the bridge works. |
| `tests/` | Automated tests for the socket protocol and the agent loop (mocked Blender + LLM). |

## How it works

```
 you  →  agent.py (LLM tool-use loop)  →  localhost:9876  →  addon.py  →  Blender/bpy
        Ollama / Groq / Gemini                        (runs inside Blender)
```

1. The add-on inside Blender listens on `127.0.0.1` only (never the network).
2. The agent asks the LLM "what should I do in Blender?" and gets back tool
   calls: `get_scene_info`, `execute_blender_code`, `render_preview`,
   `task_complete`.
3. Code runs in Blender; stdout and any tracebacks go back to the model, so it
   can **see its own results and fix errors** in the next step.
4. Everything is wrapped in undo steps — `Ctrl+Z` in Blender rolls it back.

## Setup (5 minutes, all free)

### 1. Install the add-on in Blender

1. Install [Blender](https://www.blender.org/) (3.6 or newer; 4.x works).
2. In Blender: **Edit → Preferences → Add-ons → Install from Disk…**
   and pick `addon.py` from this folder.
3. Tick the checkbox to enable **AI Agent Bridge**.
4. In the 3D viewport press **N**, open the **AI Agent** tab, and click
   **Start AI Agent Server** (default port 9876).

### 2. Install the free local AI (Ollama)

1. Download and install [Ollama](https://ollama.com) (Windows/macOS/Linux).
2. Pull a code-capable model (in a terminal):

   ```bash
   ollama pull qwen2.5-coder:7b
   ```

   (No GPU? `qwen2.5-coder:3b` works too. More RAM/greater quality:
   `qwen2.5-coder:14b`.)

3. You don't need `ollama serve` on Windows/macOS (it auto-starts).
   On Linux run `ollama serve` once, or it starts on first request.

You need Python 3.9+ for `agent.py` (macOS/Linux already have it; on Windows
use `py agent.py ...` or install from python.org).

### 3. Build something!

```bash
cd blender-ai-agent
python agent.py "build a cozy wooden cabin with a smoking chimney and a tree next to it"
```

Watch Blender — the agent will create objects, materials, lights and a camera
step by step. When it's done it renders nothing unless you ask; to get an image:

```bash
python agent.py "build a red sports car on an asphalt road, add a camera with a nice angle, then render a preview"
```

The render PNG path is printed in the terminal.

### Verify the bridge without any AI

```bash
python agent.py --exec examples/demo_scene.py
```

A little house with a roof, door, grass, sun and camera should appear in Blender.

## Usage reference

```bash
# chat-style request (default: free local Ollama)
python agent.py "make a low-poly windmill on a hill"

# interactive mode (describe many things in one session)
python agent.py

# free hosted alternatives (no local model needed, free API keys):
GROQ_API_KEY=gsk_...   python agent.py --provider groq   "build a chess set"
GEMINI_API_KEY=AIza... python agent.py --provider gemini "build a space station"

# other options
python agent.py --model qwen2.5-coder:14b "a medieval castle"   # different Ollama model
python agent.py --port 9900 "..."                               # match the port in the add-on panel
python agent.py --max-iters 50 "..."                            # more steps for complex builds
```

Interactive mode commands: type your request and press Enter; `/scene` prints
scene info, `/undo` undoes the last step in Blender, `/quit` exits.

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
- **Slow AI** — 7B models on CPU are fine but take a few seconds per step;
  try `qwen2.5-coder:3b`, or use the free Groq provider (very fast).
- **Undo a step** — `Ctrl+Z` in Blender, or `/undo` in interactive mode.

## Development / tests

```bash
python3 tests/test_agent.py            # agent loop vs mocked Blender + mocked LLM
python3 tests/test_addon_protocol.py   # real addon.py server vs a fake bpy
```

No Blender or LLM is needed to run the tests — everything is mocked.

## License

MIT
