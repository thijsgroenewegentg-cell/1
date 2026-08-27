# Free Blender AI Agent

An AI agent that builds things in Blender for you — free and local by default
(Blender + Ollama, no API key or account needed). Works with the **BlenderMCP
add-on you already have** (direct socket or standard MCP stdio), or its own
zero-dependency bridge.

👉 See **[blender-ai-agent/README.md](blender-ai-agent/README.md)** for setup
and usage.

## Highlights

- 🔌 Three transports, auto-detected: **BlenderMCP addon**, generic **MCP stdio**
  (`uvx blender-mcp`), or the bundled bridge (`addon.py` / `bridge_standalone.py`)
- 🗣️ Chat-to-build CLI (`agent.py`) and a browser UI (`webui.py`)
- 👁️ Vision self-check (`--vision`): agent screenshots its work and fixes it
- 🎬 Scene presets (product / archviz / dramatic / outdoor / clay) + helper toolkit
- 💾 Saves `.blend`, renders PNG, exports GLB/STL/FBX/OBJ
- 📡 Watch mode for build queues; 🔒 approve mode; 🛟 free provider fallback

## Quick start

With the BlenderMCP addon server running in Blender (port 9876) — or after
installing `addon.py` and pressing **N → AI Agent → Start Server**:

```bash
python blender-ai-agent/agent.py "build a cozy wooden cabin with a tree"
python blender-ai-agent/webui.py     # or: http://localhost:8765
```

## Layout

- `blender-ai-agent/transports.py` — bridge / BlenderMCP socket / MCP stdio
- `blender-ai-agent/agent.py` — agent CLI
- `blender-ai-agent/webui.py` — browser chat UI
- `blender-ai-agent/addon.py`, `bridge_standalone.py` — bundled Blender bridge
- `blender-ai-agent/blender_helpers.py`, `presets.py` — toolkit + templates
- `blender-ai-agent/tests/` — full mock-based test suites
