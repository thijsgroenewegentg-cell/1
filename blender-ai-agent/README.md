# 🤖 Blender AI Agent — build things in Blender by chatting, for free

An AI agent that builds 3D scenes, models, materials, lighting and animation
**inside your live Blender** — you describe what you want in plain English,
it writes and runs the Blender Python code to create it.

**Works with the BlenderMCP add-on you already have.** The agent auto-detects
and talks directly to the popular [BlenderMCP](https://github.com/ahujasid/blender-mcp)
add-on over its socket (port 9876) — no extra MCP process needed. It also
speaks the generic MCP stdio protocol (`uvx blender-mcp` / `npx …`), or its own
zero-dependency bridge add-on.

**100% free by default**: [Ollama](https://ollama.com) on your own computer
(no API key/account/credits/internet for the AI). Free hosted options (Groq,
Google Gemini) are built in, with automatic fallback and vision-capable models
that can *look at* their own renders.

## What you get

| File | What it is |
|---|---|
| `transports.py` | Three ways to reach Blender: our bridge addon, the **BlenderMCP addon (direct socket)**, and a generic **MCP stdio** client. Auto-detected. |
| `addon.py` | Our own Blender add-on (optional). Localhost server that runs `bpy` code on Blender's main thread. |
| `bridge_standalone.py` | Zero-install launcher: `blender --python bridge_standalone.py` (GUI and headless). |
| `agent.py` | The AI agent CLI: LLM tool-use loop, vision routing, presets, watch mode. Stdlib only. |
| `webui.py` | Browser chat UI (`python webui.py`) — streams the build log and shows renders inline. |
| `blender_helpers.py` | Version-safe Blender toolkit (`add_primitive`, `make_material`, `quick_setup`, `ground_objects`, `animate_*`, …) injected for the model. |
| `presets.py` | Scene templates: **product, archviz, dramatic, outdoor, clay** (camera+lights+world). |
| `examples/demo_scene.py` | Test scene (little house), no LLM needed. |
| `tests/` | Automated tests for transports (incl. a fake MCP server), agent loop, web UI and presets. |

## Features

- 🔌 **Three transports** — BlenderMCP addon direct (what you already have),
  generic MCP stdio (`uvx blender-mcp`), or the bundled bridge. Auto-detected.
- 🗣️ **Chat to build** — describe what you want in plain English.
- 👁️ **Vision feedback** (`--vision`) — fast viewport screenshots are attached
  to the model so it can see and fix floating parts, bad framing, wrong colors.
- 🖼️ **Reference images** (`--image photo.jpg`) — build from a picture.
- 🎬 **Presets** (`--preset product|archviz|dramatic|outdoor|clay`) and an
  `apply_preset` tool — professional camera/lighting/world in one step.
- 🧰 **Helper toolkit** — version-safe functions for geometry, materials,
  3-point lighting, cameras, grounding, linear/rotation animation.
- 💾 **Auto save/export** — `.blend`, PNGs, and **GLB/STL/FBX/OBJ** into `output/`.
- ↕️ **Model routing** — fast text models for planning, vision models only
  when an image is in context.
- 📡 **Watch mode** (`--watch tasks.txt` or stdin) — continuous build queue.
- 🌐 **Web UI** (`python webui.py`) — chat in the browser, see renders live.
- ↩️ **Self-undo**, 🛟 **provider fallback**, 🔒 `--approve` review mode.

## How it works

```
 you  →  agent.py / webui.py  →  transport  →  Blender
        (LLM tool loop)         9876 socket    BlenderMCP addon  ← what you already have
        Ollama/Groq/Gemini                     or our addon.py / bridge_standalone.py
                                            or any MCP server over stdio
```

1. The agent connects to whatever is listening: it first probes for the
   **BlenderMCP** addon's protocol (`ping` → `{"status":"success"}`), then
   for our bridge, so you don't have to change a thing if BlenderMCP is running.
2. The model calls tools: `get_scene_info`, `execute_blender_code`,
   `apply_preset`, `render_and_inspect`, `save_blend`, `export_model`,
   `undo_blender`, `task_complete`.
3. Stdout/tracebacks return to the model for self-correction; in vision mode
   the viewport screenshot is attached too.
4. All changes land on Blender's main thread and are undoable (`Ctrl+Z`).

## Setup (5 minutes, all free)

### 1. Connect Blender — use whatever you already have

**Option A — BlenderMCP add-on (if you have it installed — nothing new to add):**
just start its server as usual (sidebar **N → BlenderMCP → Connect to Claude**,
default port 9876). This agent detects it automatically. You can also run the
standard MCP server in front of it:
```bash
python agent.py --transport mcp-stdio --mcp-cmd "uvx blender-mcp" "a windmill"
```

**Option B — this project's add-on (recommended for full features):**
1. Install [Blender](https://www.blender.org/) (3.6+; 4.x works).
2. **Edit → Preferences → Add-ons → Install from Disk…** and pick `addon.py`.
3. Tick **AI Agent Bridge**; press **N** → **AI Agent** tab → **Start AI Agent Server**.

**Option C — zero install:**
```bash
blender --python bridge_standalone.py
```
(Also headless: `blender --background --python bridge_standalone.py -- --port 9876`)

Auto-detection probes for BlenderMCP first, then the bundled bridge. Force one
with `--transport blendermcp | bridge | mcp-stdio`.

> Note on transports: the BlenderMCP addon runs code with a **fresh Python
> namespace per call**, so the agent is told to name objects and re-fetch them
> by name (its helper toolkit is auto-prepended to every call). Its viewport
> screenshot reflects the 3D view; the bundled bridge can do full-camera
> renders — both work, but the bridge gives the richest feedback.

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

Watch Blender — the agent creates objects, materials, lights and camera step
by step, then saves a `.blend` and a render into the `output/` folder.

**In the browser instead of the terminal:**
```bash
python webui.py            # then open http://localhost:8765
```

**Vision** (it screenshots its work and fixes visual problems itself):
```bash
python agent.py --vision "build a red sports car on an asphalt road and make it look good"
```

**Reference photo + scene preset:**
```bash
python agent.py --vision --image sneaker.jpg --preset product "model this shoe for a product shot"
```

**3D print / game export:**
```bash
python agent.py "build a low-poly chess knight and export it as STL"
```

**Continuous build queue** (one task per line; great for batching or piping
other tools into the agent):
```bash
printf 'a red mug\nblue chair next to it\n' | python agent.py --watch
python agent.py --watch tasks.txt
```

**Review each code action before it runs:**
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
# chat-style request (default: free local Ollama, transport auto-detected)
python agent.py "make a low-poly windmill on a hill"

# use the BlenderMCP addon explicitly, or a generic MCP server over stdio
python agent.py --transport blendermcp "a windmill"
python agent.py --transport mcp-stdio --mcp-cmd "uvx blender-mcp" "a windmill"

# vision + reference image + lighting preset
python agent.py --vision --image ref.jpg --preset product "model this"

# continuous / queued builds
printf 'a mug\na spoon next to it\n' | python agent.py --watch
python agent.py --watch tasks.txt

# browser UI
python webui.py --vision

# free hosted providers (keys auto-detected, with fallback between them)
GROQ_API_KEY=gsk_...   python agent.py --provider groq   "a chess set"
GEMINI_API_KEY=AIza... python agent.py --provider gemini "a space station"

# other options
python agent.py --preset archviz "interior scene"   # product|archviz|dramatic|outdoor|clay
python agent.py --approve "castle"                  # review code before it runs
python agent.py --max-iters 50 "complex scene"      # more agent steps
python agent.py --no-fallback "..."                 # don't auto-switch providers
python agent.py --port 9900 "..."                   # match the bridge port
```

Interactive mode (`python agent.py` with no task): `/scene`, `/undo`,
`/render`, `/save`, `/preset <name>`, `/quit`.

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
python3 tests/test_transports.py       # bridge / BlenderMCP / MCP-stdio (incl. fake MCP server)
python3 tests/test_agent.py            # agent loop, vision routing, presets, watch, helpers
python3 tests/test_addon_protocol.py   # real addon.py server (save/export/...) vs fake bpy
python3 tests/test_standalone.py       # zero-install standalone bridge launch
python3 tests/test_webui.py            # web chat UI endpoints and event stream
```

No Blender or LLM is needed to run the tests — everything is mocked (the MCP
stdio test even spawns a local fake MCP server subprocess).

## License

MIT
