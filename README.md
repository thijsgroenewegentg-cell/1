# J.A.R.V.I.S. — Ollama Edition

**Just A Rather Very Intelligent System, powered 100% by local Ollama models.**

An always-on autonomous AI daemon in the spirit of [vierisid/jarvis](https://github.com/vierisid/jarvis) — a persistent process that remembers, pursues goals, watches folders, delegates to specialist agents, and acts within the authority limits you set — but with **no cloud LLM providers and no API keys**: the brain is your local [Ollama](https://ollama.com) server.

- 🧠 **LLM layer** — Ollama only: a *smart* model for reasoning, a *fast* model for background work, streaming responses, tool calling, model pulls from the dashboard
- 🤖 **Multi-agent hierarchy** — an orchestrator plus 5 specialist roles (researcher, coder, writer, planner, system-operator) with delegation and depth limits
- 🧠 **Knowledge vault** — durable memories (notes, entities, observations, commitments) in SQLite, searchable by the agent before it answers
- 🎯 **Goal pursuit** — OKR-style goals + key results, deadlines, morning plans, evening reviews, hourly heartbeat alerts
- 👁️ **Observer** — watch folders; new/changed files get summarized by the fast model into the vault
- 🔐 **Authority gating** — runtime-enforced levels 0–4 (read-only → shell), every refusal audited
- 🖥️ **Dashboard** — live web UI at `http://localhost:3142`: streaming chat, memory, goals, system, live event feed, browser-based voice in/out (Web Speech API)
- ⌨️ **CLI** — `jarvis start|stop|status|doctor|chat|logs|pull`

Zero native dependencies: Node ≥ 22.13 built-ins only (`node:sqlite`, fetch, fs.watch) plus one pure-JS YAML parser.

---

## One-click install

**macOS / Linux / WSL2** — paste one line:

```bash
curl -fsSL https://raw.githubusercontent.com/thijsgroenewegentg-cell/1/main/install.sh | bash
```

> Until the installer lands on `main`, use the branch:
> `curl -fsSL .../arena/01a08f29-1/install.sh | JARVIS_REF=arena/01a08f29-1 bash`

The installer is idempotent and self-contained:

1. installs **Node ≥ 22** if needed (portable, into `~/.jarvis/runtime` — no root, no system changes)
2. installs **Ollama** if missing and starts it
3. fetches JARVIS into `~/.jarvis/app` and installs dependencies
4. writes `~/.jarvis/config.yaml`, pulls `llama3.2` + `llama3.2:1b`
5. installs the `jarvis` launcher (and optionally a systemd user / launchd service)
6. starts the daemon → dashboard at `http://localhost:3142`

On **macOS** you can also double-click **`install.command`** in Finder.

| Flag | Effect |
|---|---|
| `--model` / `--fast-model` | choose other Ollama models (any tool-calling model works) |
| `--port N` | dashboard port (default 3142) |
| `--service` | auto-start on login (systemd user unit / launchd agent) |
| `--no-models` · `--no-ollama` · `--no-start` | skip a step (e.g. Ollama on another machine) |
| `--open` | open the dashboard in your browser when ready |
| `--local [dir]` | install from a local checkout instead of cloning |
| `--uninstall` · `--uninstall --purge` | remove (keeps `~/.jarvis/data` unless `--purge`) |
| `-y` | non-interactive |

Downloads are retried and Node checksums verified; mirrors are tried in order
(nodejs.org → npmmirror → unofficial-builds, override with `JARVIS_NODE_MIRROR`).

## Manual quick start

Prefer to run it yourself?

```bash
# 1. Ollama — https://ollama.com/download
ollama pull llama3.2        # smart model (tool-calling capable)
ollama pull llama3.2:1b     # fast model for background work

# 2. JARVIS
npm install
npm start                   # foreground, Ctrl+C to stop
# or as a background daemon:
node bin/jarvis.js start -d
```

Open `http://localhost:3142`, and sanity-check the environment anytime with
`node bin/jarvis.js doctor`.

> **Try it without a GPU:** `npm run mock-ollama` starts a scripted fake Ollama
> server so you can explore the full dashboard (streaming, tool calls, memory,
> goals) before wiring up real models. Responses are canned and clearly labeled.

---

## CLI

```
jarvis start [-d]    Start the daemon (foreground, or detached with -d)
jarvis stop          Stop the background daemon
jarvis restart       Restart the daemon
jarvis status        Show daemon status (pid, port, model, ollama reachability)
jarvis doctor        Check node version, ollama, installed models, port
jarvis chat          Chat with the running daemon in the terminal
jarvis logs [-f]     Show / follow the daemon log
jarvis pull <model>  Pull a model from the Ollama registry
```

## Configuration

Copy `config.example.yaml` to `config.yaml` next to where you run the daemon
(or set `JARVIS_HOME` to a config directory). Everything can be overridden by
environment variables.

```yaml
daemon:
  host: 0.0.0.0
  port: 3142
  data_dir: ./data        # sqlite db, pid file, daemon log
  log_level: info

ollama:
  base_url: http://localhost:11434
  model: llama3.2         # smart model — agent reasoning + tool calls
  fast_model: llama3.2:1b # fast model — observations, summaries, routines
  temperature: 0.7
  keep_alive: 30m

authority:
  level: 3                # tool gate, see below (also changeable live in the dashboard)

agent:
  max_turns: 8            # tool-call loop budget per message
  max_delegation_depth: 2

observer:
  enabled: false
  paths: []               # folders to watch → observations land in the vault

cron:
  morning: "0 7 * * *"    # daily plan built from open goals
  evening: "0 20 * * *"   # end-of-day review
  hourly:  "37 * * * *"   # deadline heartbeat

personality:
  name: Jarvis
  core_traits: [loyal, efficient, proactive, respectful]
```

Env overrides: `JARVIS_PORT`, `JARVIS_HOST`, `JARVIS_DATA_DIR`, `JARVIS_HOME`,
`JARVIS_LOG_LEVEL`, `JARVIS_OLLAMA_URL`, `JARVIS_OLLAMA_MODEL`,
`JARVIS_OLLAMA_FAST_MODEL`, `JARVIS_AUTHORITY_LEVEL`.

## Authority model

Tools are gated at runtime; effective rule is `tool.level ≤ authority.level`.
Every refusal is reported to the model *and* audited in the event feed.

| Level | Grants |
|---|---|
| 0 | read-only: `list_dir`, `read_file`, `memory_search` |
| 1 | safe writes: `write_file`, `memory_remember`, `goal_create`, `goal_update` |
| 2 | delegation: `delegate` to specialists |
| 3 | network + user reach: `web_fetch`, `notify` |
| 4 | `shell` execution (60s timeout) |

File tools are sandboxed to the JARVIS home directory; `shell` is the only
tool that can leave it — keep it at level 4 unless you trust the models.

## Architecture

```
bin/jarvis.js          CLI entrypoint
src/
  daemon.ts            boot: config → app wiring → http server → cron/observer
  app.ts               dependency wiring of every module
  config.ts            config.yaml + env merge, clamping, home resolution
  cron.ts              dependency-free 5-field cron parser/scheduler
  events.ts            shared event bus + ring buffer (→ dashboard SSE feed)
  llm/ollama.ts        raw Ollama client: chat, streaming ndjson, tools, pull, embed
  llm/provider.ts      tier routing (smart vs fast model)
  agent/roles.ts       role definitions + tailored system prompts + tool subsets
  agent/tools.ts       tool registry, JSON schemas, authority gate, sandboxing
  agent/orchestrator.ts  tool-calling agent loop, persistence, delegation
  memory/vault.ts      knowledge vault + keyword/recency search + prompt context
  goals/goals.ts       OKR goals, key results, deadline alerts
  goals/routines.ts    morning plan / evening review / hourly heartbeat
  observer/watcher.ts  fs.watch → fast-model summaries → vault observations
  server/http.ts       REST API + SSE + static dashboard
public/                dashboard (vanilla JS, no build step)
scripts/mock-ollama.js scripted fake Ollama for demos/tests
test/                  node:test suite incl. a scripted mock Ollama
```

**How a turn flows:** dashboard → `POST /api/chat` → orchestrator builds the
system prompt (personality + role + open goals + relevant memories) → streams
from Ollama with tool specs → executes any `tool_calls` through the authority
gate → feeds results back → repeats until the model answers or the turn budget
is hit → every message is persisted, every step is published to the event bus.

## HTTP API

| Method & path | Purpose |
|---|---|
| `GET /api/health` | daemon + ollama status, counters |
| `GET /api/models` · `POST /api/models/pull` | installed models / pull (progress on the event stream) |
| `POST /api/chat` | `{message, conversation_id?, stream?}` — SSE tokens or JSON |
| `GET /api/conversations[/:id]` | conversation list / messages |
| `GET/POST /api/memories` · `DELETE /api/memories/:id` | knowledge vault (search with `?q=`) |
| `GET/POST /api/goals` · `PATCH /api/goals/:id` | goals with key results |
| `POST /api/goals/:id/key-results` · `POST /api/key-results/:id/advance` | key-result CRUD/progress |
| `POST /api/routines/morning|evening|heartbeat` | run a routine on demand |
| `PATCH /api/authority` | change the authority level live |
| `GET /api/events` · `GET /api/events/stream` | audit trail / live SSE feed |

## Development

```bash
npm test                # 36 tests against a scripted mock Ollama (no GPU needed)
npm run mock-ollama     # fake Ollama on :11434 for dashboard hacking
npm run dev             # daemon with debug logging
```

Requires Node ≥ 22.13 (`node:sqlite` + TypeScript type-stripping; no build step).

## Roadmap (not built yet)

Deliberately scoped to the core daemon first. Candidates next, roughly in
order of value: embedding-based memory search (`/api/embed` is already
client-supported), a visual workflow runner, channel adapters (Telegram/
Discord), wake-word voice, and a sidecar protocol for desktop awareness —
the parts of the original JARVIS that need more than a single machine's daemon.

## License

MIT
