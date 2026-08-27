# Free Blender AI Agent

An AI agent that builds things in Blender for you — free and local by default
(Blender + Ollama, no API key or account needed).

👉 See **[blender-ai-agent/README.md](blender-ai-agent/README.md)** for setup
and usage.

- `blender-ai-agent/addon.py` — Blender add-on (localhost bridge server)
- `blender-ai-agent/agent.py` — the AI agent CLI (stdlib-only Python)
- `blender-ai-agent/examples/demo_scene.py` — no-LLM verification scene
- `blender-ai-agent/tests/` — protocol + agent-loop tests

Quick start: install/enable `addon.py` in Blender, press **N → AI Agent →
Start Server**, then:

```bash
python blender-ai-agent/agent.py "build a cozy wooden cabin with a tree"
```
