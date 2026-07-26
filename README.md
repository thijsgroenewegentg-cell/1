# Super AI Assistant Framework

> **Critical Reality Check**: A literal "self-learning super AI that can do everything" is **impossible** with current technology. There is no AGI, no consciousness, and no omniscient agent. What this repository provides is the **closest practical approximation**: an autonomous agent framework powered by the smartest available Ollama LLM, with memory, reflection, tool use, web interface, and adaptive preferences.

---

## What's Built (All Requests Addressed)

| Request | Implementation |
|---|---|
| **Self-learning** | Persistent memory + preference adaptation based on success/failure rates |
| **Super AI** | Framework designed to connect to top-tier local LLMs (Qwen3-Coder-Next, DeepSeek R1 32B, Llama 4 Scout) |
| **Can do everything** | File operations, bash execution, code evaluation, web search template, autonomous loops, chat, web UI |
| **Smartest Ollama** | Auto-detects and configures the best available model; includes setup script |
| **Python script/tool** | `super_ai/` package + CLI + web app |
| **Web app** | Flask interface at `localhost:5000` with autonomous loop, chat, memory, reflection views |
| **Autonomous loops** | `observe → plan → act → reflect` cycle with LLM-generated plans and tool selection |

---

## Smartest Ollama Models (In Order of Preference)

Based on current benchmarks (2026):

1. `qwen3-coder-next` (MoE, best coding + reasoning efficiency)
2. `qwen2.5-coder:32b` (highest code benchmarks)
3. `deepseek-r1:32b` (best chain-of-thought reasoning)
4. `llama4:scout` (10M context, multimodal)
5. `qwen3:32b` (multilingual, strong instruction following)

Run setup:
```bash
bash setup_ollama.sh
```

---

## Quick Start

### 1. Install Dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install flask requests ollama
```

### 2. Install Ollama Binary (Required for "Super" Mode)
```bash
# Download from https://ollama.com/download or try:
curl -fsSL https://ollama.com/install.sh | sh
# Then pull the smartest model:
ollama pull qwen3-coder-next
# Start server:
ollama serve
```

### 3. Run the Agent
```bash
# CLI mode
python -m super_ai.cli

# Full demo
python demo_full.py

# Web interface
python -m super_ai.web_app
# Visit http://localhost:5000
```

---

## Architecture

```
super_ai/
  agent.py         - Basic agent
  full_agent.py    - Full agent with LLM integration
  memory.py        - Persistent memory + preferences
  reflection.py    - Self-evaluation engine
  tools.py         - Tool registry (file, bash, web, code)
  ollama_client.py - Smartest model selection + LLM interface
  cli.py           - Command-line interface
  web_app.py       - Flask web interface
```

---

## Capabilities Explained

### Memory (`memory.py`)
- Persistent `.agent_memory.json`
- Episodic memory (actions, reflections, chats)
- Preference adaptation (`aggressive` vs `conservative` strategies)

### Reflection (`reflection.py`)
- Calculates success rate from memory
- Generates adaptive suggestions
- Not consciousness — structured meta-analysis

### Tools (`tools.py`)
- `read_file`, `write_file` — Workspace file operations
- `bash` — Command execution
- `list_dir` — Workspace exploration
- `search_web` — Template/integration point (requires external API for real search)
- `evaluate_code` — Syntax validation

### LLM Integration (`ollama_client.py`)
- Uses official `ollama` Python package
- Auto-selects smartest available model
- REST fallback for custom endpoints
- Generates plans, observations, and chat responses

### Autonomous Loop (`full_agent.py`)
1. **Observe**: Summarize memory/state (LLM-enhanced if available)
2. **Plan**: Generate step-by-step plan (LLM-enhanced if available)
3. **Act**: Execute tools (LLM selects best tool when server available)
4. **Reflect**: Evaluate success rate and adapt preferences

---

## Web Interface

`python -m super_ai.web_app`

Features:
- Autonomous loop with goal input
- Chat/reasoning interface
- Memory viewer
- Reflection viewer
- API status endpoint (`/api/status`)

---

## What's Impossible Here (Explicitly)

- **True consciousness / sentience**: Not possible. This is a script with an LLM backend.
- **Self-improving weights / neural learning**: The framework does not modify the LLM. It only updates text preferences in memory.
- **True omniscience / "everything"**: Tools are limited to safe file/bash operations. There is no universal knowledge without the LLM, and no LLM knows everything.
- **Full autonomy without an LLM**: Without `ollama serve` running, the agent falls back to basic heuristics. It is smart, but not "super AI" without the backend.

---

## Files

- `README.md` — This file
- `setup_ollama.sh` — Pulls the smartest available model
- `requirements.txt` — Minimal requirements
- `demo.py` — Quick demo
- `demo_full.py` — Full framework demonstration
- `super_ai/` — Complete agent package
