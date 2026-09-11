# jarvis × Ollama

**Short answer: it worked everywhere except the one place that matters — and that place is now fixed.**

`vierisid/jarvis` already ships Ollama support in every layer (provider class, config binding, dashboard,
onboarding wizard, doctor). What it never did was tell Ollama **how much context to load**. So Ollama used
its default window of 4096 tokens, and when jarvis's prompt did not fit, Ollama **silently threw away the
front of it** and answered anyway. Jarvis leads every request with its system prompt and tool schemas, so
the first thing to go was jarvis's own instructions. The model looked broken; it was reading a stub.

That is a one-constant fix, and it is in [`patches/0001-ollama-context-window.patch`](patches/0001-ollama-context-window.patch).

---

## Why this was happening

| Fact | Value |
| --- | --- |
| Ollama's default context window | **4096 tokens** (4k on machines under 24 GiB VRAM) |
| What Ollama does when a prompt is longer | warns **only in its own log** and *drops the front of the prompt*, keeping the tail |
| Jarvis's 28 built-in tool schemas | 17,002 bytes ≈ **4,251 tokens** |
| Jarvis's largest role prompt (`roles/dev-lead.yaml`) | 7,633 bytes ≈ **1,908 tokens** |
| Total before a single word of conversation | **≈ 6,159 tokens** |
| `num_ctx` set anywhere in jarvis's Ollama provider | **nowhere** |

Jarvis builds its requests instructions-first, which is exactly the part Ollama discards first. Worse, the
tool schemas alone (4,251 tokens) already overflow the default window — something to check before assuming
a local model is "too small" or "not good at tools".

## Proof

The harness in [`verify/`](verify/) drives jarvis's *real* provider factory, `LLMManager` and tool
definitions against a stand-in that reproduces Ollama's documented behaviour, then reads the server-side
request log to see what the model actually received:

| | `num_ctx` sent | window | prompt | dropped | system prompt |
| --- | --- | --- | --- | --- | --- |
| **before** | *(missing)* | 4096 | 7509 tokens | **7499** | **gone** |
| **after** | 32000 | 32000 | 7509 tokens | 0 | intact |

The stand-in prints the same warning a real Ollama server would, in its own format:

```
level=WARN source=runner.go msg="truncating input prompt" limit=4096 prompt=7509 keep=10
```

Full transcript: [`docs/verification-log.txt`](docs/verification-log.txt).

## What the patch changes

Only `src/llm/ollama.ts` (plus its test file) — nothing else in jarvis is touched:

- adds one constant, `CONTEXT_TOKENS = 32000`, and sends it as `options.num_ctx` on **every** `/api/chat`
  call, streaming and non-streaming;
- the history-compaction budget now uses that same constant instead of a second hardcoded `32000`, so the
  window jarvis asks for and the window it budgets for can no longer drift apart.

`src/llm/ollama.test.ts` gains three tests asserting `num_ctx` rides on the chat call, on the streaming
call, and alongside `temperature` / `num_predict`.

## Using it

```bash
git clone https://github.com/vierisid/jarvis
cd jarvis
git checkout 9f8738df7184a9e3e5f9163ffffdb999824e72d4     # the commit this patch is cut against
git apply /path/to/patches/0001-ollama-context-window.patch
bun install
```

Then point jarvis at your Ollama: **Settings → LLM → add provider → Ollama**, base URL
`http://localhost:11434`, pick a model from the installed list (the wizard queries your Ollama for real
model tags), and set the default/tiers to `ollama:<model>`.

### Reproduce the verification

```bash
bash scripts/verify-ollama.sh        # deterministic: checks out the pinned commit, proves before vs after
```

Against **your own** Ollama instead of the stand-in:

```bash
OLLAMA_BASE_URL=http://localhost:11434 OLLAMA_MODEL=qwen2.5:3b \
  bash scripts/verify-ollama.sh --real-only
```

Why a stand-in at all: the machine this was prepared on has no GPU, no `ollama` binary and no access to
`registry.ollama.ai`, so no model could be pulled. The stand-in implements the parts of Ollama that decide
this bug — the 4096 default, the silent front-truncation, `options.num_ctx`, NDJSON streaming, and tool
calls with object arguments — while the jarvis side of every request is real, unmodified jarvis code.

## Notes and caveats

- **A 32k window costs VRAM** for the KV cache. On a small GPU, lower `CONTEXT_TOKENS` in `ollama.ts` (it is
  one constant). On machines where Ollama's VRAM-tiered default is already ≥32k, the patch changes nothing
  in practice — it just stops the client and server from disagreeing.
- **Prefer not to patch?** You can bake the window into the server instead:
  `OLLAMA_CONTEXT_LENGTH=32768 ollama serve`, or a Modelfile with `PARAMETER num_ctx 32768`. That is a
  machine-wide workaround; the patch is what makes jarvis correct by default for everyone using it.
- Ollama's **OpenAI-compatible `/v1` endpoint has no way to pass `num_ctx`** at all. Jarvis talks to the
  native `/api/chat`, which is why this fix is possible in the client.
- **Models without tool support** will still reject jarvis's tool-bearing requests; that is a model
  limitation, not a jarvis bug. Restrict tools per role if you hit it.
- **Upstream is untouched.** This repository holds the patch and the harness, not a vendored copy of jarvis
  (its licence is source-available, RSALv2-based). The harness clones jarvis at a pinned commit on demand.

## Layout

```
patches/0001-ollama-context-window.patch   the fix (src/llm/ollama.ts + its test)
verify/ollama-stand-in.ts                  Ollama API stand-in with faithful truncation semantics
verify/live-check.ts                       drives real jarvis code (provider factory, manager, tools)
scripts/verify-ollama.sh                   before/after runner, or --real-only against your Ollama
docs/verification-log.txt                  captured output of a full run
```
