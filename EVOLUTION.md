# JARVIS Self-Evolution - How He Makes Himself Better

JARVIS doesn't just learn about you. He **improves his own mind**.

## The Loop

```
User talks to JARVIS
  ↓
[Performance Tracker] records: latency, tool success, satisfaction
  ↓
[Self-Critic] scores response 0-10: issues, improvements, strengths
  - Heuristic: checks empty response, broke character, missed tool, verbose, etc
  - LLM: Ollama critiques: "Score 7.5, issues: too verbose, improvements: be concise"
  ↓
[Should Evolve?] Trigger if:
  - satisfaction < 0.5
  - success_rate < 80%
  - trend declining
  - critic_score < 6.0
  - every 50 interactions
  - user says "improve yourself"
  ↓
[Evolution Engine] does in background:

  1. Prompt Evolution:
     - Takes critique + user profile
     - LLM proposes: "Be more concise when user asks short questions"
     - Saves to data/evolution/prompt_additions.json (active=true)
     - Next message, this is injected into system prompt
     - JARVIS personality literally evolves

  2. Tool Forging:
     - Detects missing capability: user asks Spotify, email, calendar, etc
     - If assistant said "I can't" and no tool exists
     - LLM generates Python function code (20-60 lines)
     - Syntax check + saves to jarvis/tools/<name>.py
     - Registers in TOOL_MAP, logs to tool_forge_log.json
     - New ability forged, no restart needed for next version (dynamic)

  3. Memory Optimization:
     - Prunes vector store if >800 entries, keeps high access_count
     - Consolidates similar memories

  ↓
  Logs to data/evolution/evolution_log.json
  Backup to data/backups/
  ↓
Next interaction uses evolved prompt + new tools
```

## Files

- `jarvis/evolution/self_critic.py` - Scores 0-10, heuristic + LLM
- `jarvis/evolution/performance_tracker.py` - Tracks 500 interactions, stats, trend detection
- `jarvis/evolution/self_editor.py` - Safe file editing with whitelist, backups, approval mode
- `jarvis/evolution/tool_forger.py` - Detects missing tool pattern, LLM code gen, creates tool file
- `jarvis/evolution/evolution_engine.py` - Orchestrator, background threads

- `data/evolution/prompt_additions.json` - Evolved prompt directives
- `data/evolution/tool_forge_log.json` - Forged tools history
- `data/evolution/performance.json` - 500 perf records
- `data/evolution/evolution_log.json` - All evolutions
- `data/backups/` - Backup of edited files

## Whitelist Safety

**Auto-edit allowed (no approval):**
- `jarvis/personality.py` (prompt additions file, not core)
- `data/evolution/*`
- `jarvis/tools/` (create new tools)

**Requires approval (proposed but not auto-applied unless SELF_EDIT_ENABLED=true):**
- `jarvis/brain.py`, `config.py`, `learning/`, `evolution/`, `web/`, `desktop/`

**Never:**
- `.git/`, `data/backups/`, `.env`, `venv/`

Set `SELF_EDIT_ENABLED=false` (default) = safe mode. He proposes evolutions, saves to JSON files that are read on next startup. Prompt evolutions are applied as additions to system prompt, not overwriting core prompt.

Set `SELF_EDIT_ENABLED=true` = he auto-creates tools and applies prompt evolutions immediately.

## Tools JARVIS Can Call Himself

He has 5 new tools in `TOOL_MAP`:

- `improve_self(instruction="")` - Trigger evolution manually: "improve yourself to be more concise"
- `create_new_tool(tool_name, description, purpose)` - Forge new capability when lacks one
- `analyze_performance()` - Self-analysis report
- `get_evolution_history(limit)` - History of improvements
- `self_reflect()` - Deep reflection

User can say: "JARVIS, improve yourself" or "JARVIS, analyze your performance" or "JARVIS, you need a Spotify tool" and he will.

## API

```bash
GET  /api/evolution/status      # evolution_count, avg_critic, should_evolve, stats, capabilities
GET  /api/evolution/history?limit=20
POST /api/evolution/improve {instruction: "be more concise"}
```

WebSocket:
```js
ws.send(JSON.stringify({type: "evolve", instruction: "learn Spotify"}))
// → type: evolution
// → type: evolved toast
```

## UI

Minimal UI shows:

- Top bar: 🧬 3 (evolution count) next to ◐ learnings
- Drawer: stats: evolutions, critic /10, trend
- Buttons: "🧬 Improve yourself", "Evolution history", "Analyze performance"
- Toast: "🧬 Evolved: Prompt evolved: Be more concise..."
- Modal: Evolution history with timestamps, type, description

## Example Evolutions

**Prompt Evolution:**
```json
{
  "timestamp": "2026-07-31T10:00:00",
  "prompt": "When user asks short questions, be extremely concise. No fluff.",
  "reason": "Low self-critique score 5.2: Too verbose",
  "active": true
}
```

**Tool Forge:**
```json
{
  "timestamp": "2026-07-31T10:05:00",
  "tool_name": "spotify_control",
  "reason": "User asked to play music, no tool exists",
  "schema": {...}
}
```
Then file `jarvis/tools/spotify_control.py` exists:
```python
def spotify_control(action: str, query: str = "") -> str:
    """Control Spotify - play, pause..."""
    ...
```

## How to Use

```bash
# Automatic - just chat, he evolves when needed
python web/server.py
# Check evolution status
curl http://localhost:8000/api/evolution/status | jq

# Manual
# In UI: click "Improve yourself"
# Or say: "JARVIS, improve yourself to be funnier"
# Or via API:
curl -X POST http://localhost:8000/api/evolution/improve -H "Content-Type: application/json" -d '{"instruction":"be more concise"}'

# View history
curl http://localhost:8000/api/evolution/history?limit=10
```

## Safety

- All edits backed up to `data/backups/` with timestamp
- Prompt evolutions are additive, not replacing core personality - you can delete `data/evolution/prompt_additions.json` to reset
- Tool forge code is syntax-checked with `compile()` before saving
- Evolution log is full audit trail
- Set `EVOLUTION_ENABLED=false` to disable completely

## Future: Full Self-Code Evolution

Current: prompt + tools evolve automatically, core brain edits require approval.

Next: JARVIS could propose edits to `brain.py` itself via diff, run tests, and if tests pass, auto-merge. This is guarded behind `SELF_EDIT_ENABLED=true` and would be full AGI self-improvement.

For now, he makes himself better within safe bounds.

---

"He doesn't just learn about you, Sir. He learns about himself." - JARVIS on Evolution
