# Free Blender AI Agent

An AI agent that builds things in Blender for you — free and local by default
(Blender + Ollama, no API key or account needed).

👉 See **[blender-ai-agent/README.md](blender-ai-agent/README.md)** for setup
and usage.

- `blender-ai-agent/addon.py` — Blender add-on (localhost bridge server)
- `blender-ai-agent/bridge_standalone.py` — zero-install launcher (`blender --python ...`)
- `blender-ai-agent/agent.py` — the AI agent CLI (stdlib-only Python); supports
  vision self-check (`--vision`), reference images (`--image`), auto-save/export,
  self-undo, approve mode, and free provider fallback
- `blender-ai-agent/examples/demo_scene.py` — no-LLM verification scene
- `blender-ai-agent/tests/` — protocol + standalone bridge + agent-loop tests

Quick start: install/enable `addon.py` in Blender, press **N → AI Agent →
Start Server**, then:

```bash
python blender-ai-agent/agent.py "build a cozy wooden cabin with a tree"
```
