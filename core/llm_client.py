"""
MARK — local LLM client (Ollama).

Every model call in the assistant goes through this file: the live voice turn,
the vision pass over a screenshot, the session summary, and the text helpers
used by the bundled actions (code_helper, dev_agent, file_processor, desktop,
computer_control, web_search).

There is no cloud API and no API key anywhere in this build — the only thing
the assistant talks to is the Ollama server, which defaults to

    http://localhost:11434

Configuration lives in  config/api_keys.json  (name kept for compatibility with
the action files; it now holds local settings only, never a secret):

    {
      "llm_url":      "http://localhost:11434",
      "llm_model":    "qwen2.5:14b",
      "vision_model": "qwen2.5vl:7b",
      "fast_model":   "qwen2.5:7b-instruct",
      "response_profile": "dual",
      "stt_model":    "base",
      "tts_engine":   "edgetts",
      "tts_voice":    "Guy"
    }

Install Ollama from https://ollama.com — `ollama serve` is started
automatically if it is not already running (see ensure_ollama_running).
"""

import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Generator

import requests

# Matches a sentence boundary: [.!?] followed by whitespace, or a blank line.
# Avoids splitting on decimals (3.5) because those have no space after the dot.
_SENT_END = re.compile(r'(?<=[.!?])\s+|(?<=\n)\s*\n')

# Strips the chat-markup some local models leak into their output even when
# they are driven through the /api/chat endpoint (<|im_start|>, <tool_call>, …).
_MARKUP = re.compile(
    r"<\|[a-z_]*?\|>|</?tool_call>|</?function_call>|</?antml:[a-z_]+>",
    re.IGNORECASE,
)


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR    = get_base_dir()
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

_DEFAULTS = {
    "llm_url":      "http://localhost:11434",
    "llm_model":    "qwen2.5:14b",
    "vision_model": "qwen2.5vl:7b",
    "stt_model":    "base",
    "tts_engine":   "edgetts",
    "tts_voice":    "Guy",
    # Fast router/reply model used for short requests when it is already pulled.
    # The quality model remains the fallback for complex prompts and Blender/code work.
    "fast_model":   "qwen2.5:7b-instruct",
    "response_profile": "dual",
    # Context window handed to Ollama. 8192 leaves room for the system prompt,
    # ~30 tool schemas, a screenshot description and a long conversation.
    "num_ctx":      8192,
    # Cap on a *spoken* reply. 320 tokens ≈ 240 words — well past any sentence
    # JARVIS should say out loud, and short enough to keep latency down.
    "num_predict":  320,
    "temperature":  0.7,
}

# Models offered by the setup screen, best first. Whatever Ollama already has
# pulled is listed ahead of these in the UI.
RECOMMENDED_MODELS = [
    "qwen2.5:14b",            # recommended on ≥12 GB VRAM
    "llama3.1:8b",            # fast, very reliable tool calling
    "qwen2.5:7b-instruct",    # light (≈5 GB)
    "qwen3:8b",
    "llama3.2:3b",            # smallest usable for tool calls
    "gpt-oss:20b",            # best quality on ≥16 GB
]

RECOMMENDED_VISION_MODELS = [
    "qwen2.5vl:7b",
    "llama3.2-vision:11b",
    "gemma3:12b",
    "llava:7b",
]


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_llm_settings() -> tuple[str, str]:
    """Returns (base_url, model_name)."""
    cfg   = _load_config()
    url   = str(cfg.get("llm_url",   _DEFAULTS["llm_url"])).rstrip("/")
    model = str(cfg.get("llm_model", _DEFAULTS["llm_model"]))
    return url, model


def get_fast_model() -> str:
    """Small model for short turns; never used if it is not already pulled."""
    return str(_load_config().get("fast_model") or _DEFAULTS["fast_model"])


def get_response_profile() -> str:
    value = str(_load_config().get("response_profile") or _DEFAULTS["response_profile"])
    return value.lower() if value.lower() in {"quality", "fast", "dual"} else "dual"


def get_vision_model() -> str:
    """Model used when a screenshot / webcam frame is in the messages."""
    return str(_load_config().get("vision_model") or _DEFAULTS["vision_model"])


def get_stt_model() -> str:
    return str(_load_config().get("stt_model") or _DEFAULTS["stt_model"])


def get_tts_engine() -> str:
    return str(_load_config().get("tts_engine") or _DEFAULTS["tts_engine"]).lower()


def get_tts_voice() -> str:
    return str(_load_config().get("tts_voice") or _DEFAULTS["tts_voice"])


def get_num_ctx() -> int:
    try:
        return int(_load_config().get("num_ctx", _DEFAULTS["num_ctx"]))
    except Exception:
        return int(_DEFAULTS["num_ctx"])


def get_num_predict() -> int:
    try:
        return int(_load_config().get("num_predict", _DEFAULTS["num_predict"]))
    except Exception:
        return int(_DEFAULTS["num_predict"])


def get_temperature() -> float:
    try:
        return float(_load_config().get("temperature", _DEFAULTS["temperature"]))
    except Exception:
        return float(_DEFAULTS["temperature"])


def save_llm_settings(url: str | None = None, model: str | None = None,
                      vision_model: str | None = None,
                      fast_model: str | None = None,
                      response_profile: str | None = None) -> None:
    """Persist local Ollama endpoint, model and response-profile choices."""
    from memory.config_manager import _patch_config
    fields: dict = {}
    if url:
        fields["llm_url"] = url.strip().rstrip("/")
    if model:
        fields["llm_model"] = model.strip()
    if vision_model:
        fields["vision_model"] = vision_model.strip()
    if fast_model:
        fields["fast_model"] = fast_model.strip()
    if response_profile and response_profile.lower() in {"quality", "fast", "dual"}:
        fields["response_profile"] = response_profile.lower()
    if fields:
        _patch_config(**fields)


# ── Server management ────────────────────────────────────────────────────────

def _is_up(url: str) -> bool:
    try:
        return requests.get(f"{url}/api/tags", timeout=3).status_code == 200
    except Exception:
        return False


def ensure_ollama_running(timeout: int = 15) -> bool:
    """
    Ping /api/tags; if the server is down, launch 'ollama serve' and wait for
    it to come up. Returns True when the server answers.
    """
    url, _ = get_llm_settings()

    if _is_up(url):
        return True

    print("[LLM] Ollama not running — launching 'ollama serve'…")
    try:
        kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(["ollama", "serve"], **kwargs)
    except FileNotFoundError:
        print("[LLM] 'ollama' command not found. Install Ollama from https://ollama.com")
        return False
    except Exception as e:
        print(f"[LLM] Could not launch Ollama: {e}")
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1.0)
        if _is_up(url):
            print("[LLM] Ollama started successfully.")
            return True

    print("[LLM] Ollama did not respond within the timeout.")
    return False


def list_models() -> list[str]:
    """Names of the models Ollama has pulled. Empty list if unreachable."""
    url, _ = get_llm_settings()
    try:
        resp = requests.get(f"{url}/api/tags", timeout=5)
        resp.raise_for_status()
        return [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
    except Exception:
        return []


def pull_model(name: str, log: Callable[[str], None] | None = None,
               timeout: int = 3600) -> bool:
    """
    `ollama pull <name>`, streaming progress to `log`. Blocking.

    Uses the HTTP API so it works on every OS without shelling out, and reports
    the same percentage lines the CLI prints.
    """
    url, _ = get_llm_settings()
    try:
        with requests.post(f"{url}/api/pull",
                           json={"name": name, "stream": True},
                           stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            last_pct = -1
            for raw in resp.iter_lines():
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if data.get("error"):
                    if log:
                        log(f"ERR: {data['error']}")
                    return False
                status = data.get("status", "")
                total   = data.get("total") or 0
                compl   = data.get("completed") or 0
                if total and compl:
                    pct = int(compl * 100 / total)
                    # only log every 5 % — progress lines arrive constantly
                    if pct != last_pct and pct % 5 == 0:
                        last_pct = pct
                        if log:
                            log(f"{status} {pct}%")
                elif status and log:
                    log(status)
            if log:
                log(f"Model '{name}' ready.")
            return True
    except Exception as e:
        if log:
            log(f"ERR: pull failed: {e}")
        return False


def check_model_available(log: Callable[[str], None] | None = None) -> bool:
    """
    True if the configured model is already pulled. Logs an actionable warning
    (console + optional UI callback) when it is not.
    """
    url, model = get_llm_settings()
    try:
        resp = requests.get(f"{url}/api/tags", timeout=5)
        resp.raise_for_status()
        pulled = [m.get("name", "") for m in resp.json().get("models", [])]
    except Exception:
        return True   # server may still be starting; never block boot on this

    if _matches(model, pulled):
        return True

    available = ", ".join(pulled) if pulled else "none"
    warn = (
        f"WRN: Model '{model}' is not pulled in Ollama.\n"
        f"     Available: {available}\n"
        f"     Fix: ollama pull {model}"
    )
    print(warn)
    if log:
        log(f"WRN: '{model}' not found — run: ollama pull {model}")
    return False


def _matches(model: str, pulled: list[str]) -> bool:
    model = str(model or "").strip()
    if not model:
        return False
    # A specifically tagged model must be present exactly; only an untagged
    # request may resolve to any pulled tag in that family.
    if ":" in model:
        return model in pulled
    return any(m == model or m.startswith(model + ":") for m in pulled)


def model_is_available(model: str) -> bool:
    return bool(model) and _matches(model, list_models())


def warmup_model(system_prompt: str | None = None, model: str | None = None) -> bool:
    """
    Load the model AND prime Ollama's KV prefix cache.

    Ollama caches the KV attention state of a prompt prefix across requests, so
    warming up with the same system prompt the real turns will use means those
    tokens are evaluated once at startup instead of on every turn — first-token
    latency drops from seconds to well under a second.
    """
    url, default_model = get_llm_settings()
    model = model or default_model
    print(f"[LLM] Warming up '{model}'…")

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": "hi"})

    payload = {
        "model":      model,
        "messages":   messages,
        "stream":     False,
        "keep_alive": -1,
        "options":    _options(num_predict=1),
    }
    try:
        resp = requests.post(f"{url}/api/chat", json=payload, timeout=180)
        resp.raise_for_status()
        print(f"[LLM] '{model}' loaded and KV cache primed.")
        return True
    except Exception as e:
        print(f"[LLM] Warmup failed (non-fatal): {e}")
        return False


def _options(num_predict: int | None = None,
             temperature: float | None = None,
             num_ctx: int | None = None) -> dict:
    return {
        "num_predict": num_predict if num_predict is not None else get_num_predict(),
        "num_ctx":     num_ctx if num_ctx is not None else get_num_ctx(),
        "temperature": get_temperature() if temperature is None else temperature,
        # 99 → push every transformer layer to the GPU when one is available.
        # Harmless on CPU-only boxes: Ollama clamps to what it has.
        "num_gpu":     99,
    }


# ── Tool schemas ─────────────────────────────────────────────────────────────

_TYPE_MAP = {
    "STRING":  "string",
    "NUMBER":  "number",
    "INTEGER": "integer",
    "BOOLEAN": "boolean",
    "ARRAY":   "array",
    "OBJECT":  "object",
}


def _convert_schema(node: dict) -> dict:
    """Tool declaration → JSON Schema understood by Ollama."""
    if not isinstance(node, dict):
        return {}
    out: dict = {}
    t = _TYPE_MAP.get(str(node.get("type", "")).upper(), node.get("type"))
    if t:
        out["type"] = t
    for key in ("description", "enum", "format", "default"):
        if key in node and node[key] is not None:
            out[key] = node[key]
    if "properties" in node and isinstance(node["properties"], dict):
        out["properties"] = {k: _convert_schema(v)
                             for k, v in node["properties"].items()}
    if "items" in node and isinstance(node["items"], dict):
        out["items"] = _convert_schema(node["items"])
    if "required" in node:
        req = node["required"]
        out["required"] = list(req) if isinstance(req, (list, tuple)) else [req]
    return out


def to_ollama_tools(declarations: list[dict]) -> list[dict]:
    """
    Convert this project's tool declarations (actions/*.py TOOL dicts) into the
    OpenAI-style tool list Ollama's /api/chat expects.
    """
    tools: list[dict] = []
    for decl in declarations or []:
        if not isinstance(decl, dict):
            continue
        name = decl.get("name")
        if not name:
            continue
        params = _convert_schema(decl.get("parameters") or {"type": "OBJECT"})
        tools.append({
            "type": "function",
            "function": {
                "name":        name,
                "description": decl.get("description", ""),
                "parameters":  params or {"type": "object", "properties": {}},
            },
        })
    return tools


# ── Fallback tool-call parsing ───────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Strip chat markup a local model may leak, and trim."""
    if not text:
        return ""
    return _MARKUP.sub("", text).strip()


def _json_blobs(text: str) -> list[dict]:
    """Every {...} in `text` that parses as a dict (fenced blocks first)."""
    out: list[dict] = []
    candidates: list[str] = []
    for block in re.findall(r"```(?:json)?\s*(.*?)```", text or "", re.DOTALL):
        candidates.append(block.strip())
    # bare objects, balanced-brace scan
    depth, start = 0, None
    for i, ch in enumerate(text or ""):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    candidates.append(text[start:i + 1])
                    start = None
    for raw in candidates:
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
        elif isinstance(obj, list):
            out.extend(o for o in obj if isinstance(o, dict))
    return out


def parse_tool_calls(text: str, known_names) -> list[dict]:
    """
    Rescue tool calls that a model wrote as JSON in its prose instead of
    emitting real tool_calls. Returns Ollama-shaped tool-call dicts.

    Recognised shapes:
        {"name": "volume", "arguments": {...}}
        {"tool": "volume", "arguments": {...}}
        {"function": "volume", "parameters": {...}}
        {"tool_calls": [{"name": ..., "arguments": {...}}]}
        {"action": "volume", ...}   (remaining keys become the arguments)
    """
    names = set(known_names or ())
    if not names or not text:
        return []

    for obj in _json_blobs(text):
        if "tool_calls" in obj and isinstance(obj["tool_calls"], list):
            parsed = []
            for sub in obj["tool_calls"]:
                parsed.extend(_one_tool_call(sub, names))
            if parsed:
                return parsed
        parsed = _one_tool_call(obj, names)
        if parsed:
            return parsed
    return []


def _one_tool_call(obj: dict, names: set) -> list[dict]:
    for key in ("name", "tool", "function", "tool_name"):
        cand = obj.get(key)
        if isinstance(cand, str) and cand.strip() in names:
            name = cand.strip()
            args = None
            for akey in ("arguments", "parameters", "args", "params"):
                if isinstance(obj.get(akey), dict):
                    args = obj[akey]
                    break
                if isinstance(obj.get(akey), str):
                    try:
                        args = json.loads(obj[akey])
                    except Exception:
                        args = None
                    break
            if args is None:
                args = {k: v for k, v in obj.items()
                        if k not in (key, "arguments", "parameters", "args", "params")}
            return [{"function": {"name": name, "arguments": args or {}}}]

    # {"volume": {...}} / {"volume": null}
    for key, val in obj.items():
        if key in names:
            args = val if isinstance(val, dict) else {}
            return [{"function": {"name": key, "arguments": args}}]
    return []


# ── Images ───────────────────────────────────────────────────────────────────

def _to_b64(image) -> str | None:
    """PIL Image | path | bytes | base64-str  →  raw base64 string."""
    try:
        # PIL Image
        if hasattr(image, "save"):
            import io
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("ascii")

        if isinstance(image, (str, Path)):
            p = Path(image)
            if p.exists():
                return base64.b64encode(p.read_bytes()).decode("ascii")
            # already base64?
            s = str(image)
            if len(s) > 64 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", s):
                return "".join(s.split())
            return None

        if isinstance(image, (bytes, bytearray)):
            return base64.b64encode(bytes(image)).decode("ascii")

        # multimodal attachment style {"mime_type": ..., "data": ...}
        if isinstance(image, dict):
            data = image.get("data")
            if isinstance(data, (bytes, bytearray)):
                return base64.b64encode(bytes(data)).decode("ascii")
            if isinstance(data, str):
                return data.split(",")[-1]
    except Exception as e:
        print(f"[LLM] Could not encode image: {e}")
    return None


def encode_images(images) -> list[str]:
    return [b for b in (_to_b64(i) for i in (images or [])) if b]


# ── Chat ─────────────────────────────────────────────────────────────────────

def call_llm(
    messages: list,
    tools:    list | None = None,
    timeout:  int = 120,
    model:    str | None = None,
) -> dict:
    """
    Non-streaming chat completion.

    Returns {"content": str, "tool_calls": list}.
    """
    url, default_model = get_llm_settings()
    endpoint = f"{url}/api/chat"
    payload = {
        "model":      model or default_model,
        "messages":   messages,
        "stream":     False,
        "keep_alive": -1,
        "options":    _options(),
    }
    if tools:
        payload["tools"] = tools

    try:
        resp = requests.post(endpoint, json=payload, timeout=timeout)
        resp.raise_for_status()
        msg = resp.json().get("message", {})
        content = clean_text(msg.get("content") or "")
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls and tools:
            names = [t.get("function", {}).get("name") for t in tools]
            tool_calls = parse_tool_calls(content, names)
            if tool_calls:
                content = ""
        return {"content": content, "tool_calls": tool_calls}
    except requests.exceptions.ConnectionError as e:
        print(f"[LLM] ConnectionError — trying to restart Ollama… ({e})")
        if ensure_ollama_running():
            try:
                resp = requests.post(endpoint, json=payload, timeout=timeout)
                resp.raise_for_status()
                msg = resp.json().get("message", {})
                content = clean_text(msg.get("content") or "")
                tool_calls = msg.get("tool_calls") or []
                if not tool_calls and tools:
                    names = [t.get("function", {}).get("name") for t in tools]
                    tool_calls = parse_tool_calls(content, names)
                    if tool_calls:
                        content = ""
                return {"content": content, "tool_calls": tool_calls}
            except Exception:
                pass
        raise RuntimeError(
            f"Cannot connect to Ollama at {url}. "
            "Make sure Ollama is installed and run: ollama serve"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(f"Ollama request timed out after {timeout}s.")
    except requests.exceptions.HTTPError as e:
        print(f"[LLM] HTTPError: {e.response.status_code} — {e.response.text[:200]}")
        raise RuntimeError(f"Ollama HTTP error: {e.response.status_code}")
    except Exception as e:
        print(f"[LLM] Unexpected error: {type(e).__name__}: {e}")
        raise RuntimeError(f"LLM call failed: {e}")


def call_llm_stream(
    messages: list,
    tools:    list | None = None,
    timeout:  int = 180,
    model:    str | None = None,
) -> Generator[dict, None, None]:
    """
    Streaming chat completion.

    Yields
        {"type": "sentence", "text": str}  — each finished sentence, for TTS
        {"type": "done", "content": str, "tool_calls": list}

    Tool calls (real or rescued from the text) always arrive in "done".
    """
    url, default_model = get_llm_settings()
    endpoint = f"{url}/api/chat"

    payload: dict = {
        "model":      model or default_model,
        "messages":   messages,
        "stream":     True,
        "keep_alive": -1,
        "options":    _options(),
    }
    if tools:
        payload["tools"] = tools

    tool_names = [t["function"]["name"] for t in (tools or [])
                  if isinstance(t, dict) and "function" in t]

    def _do_stream() -> Generator[dict, None, None]:
        with requests.post(endpoint, json=payload, timeout=timeout, stream=True) as resp:
            resp.raise_for_status()
            full_content = ""
            tool_calls:  list = []
            buf          = ""

            for raw in resp.iter_lines():
                if not raw:
                    continue
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg   = chunk.get("message", {})
                delta = msg.get("content") or ""

                full_content += delta
                buf          += delta

                while True:
                    m = _SENT_END.search(buf)
                    if not m:
                        break
                    sentence = clean_text(buf[: m.start() + 1])
                    buf      = buf[m.end():]
                    if sentence:
                        yield {"type": "sentence", "text": sentence}

                tc = msg.get("tool_calls")
                if tc:
                    tool_calls.extend(tc)

                if chunk.get("done"):
                    if buf.strip():
                        tail = clean_text(buf)
                        if tail:
                            yield {"type": "sentence", "text": tail}
                    if not tool_calls:
                        tool_calls = parse_tool_calls(full_content, tool_names)
                        if tool_calls:
                            # the text was the model's way of asking for a tool —
                            # don't speak the JSON it wrapped the call in.
                            full_content = ""
                    yield {
                        "type":       "done",
                        "content":    clean_text(full_content),
                        "tool_calls": tool_calls,
                    }
                    return

    try:
        yield from _do_stream()
    except requests.exceptions.ConnectionError as e:
        print(f"[LLM] Stream ConnectionError — trying to restart Ollama… ({e})")
        if ensure_ollama_running():
            yield from _do_stream()
            return
        raise RuntimeError(
            f"Cannot connect to Ollama at {url}. "
            "Make sure Ollama is installed and run: ollama serve"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama stream timed out.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Ollama HTTP error: {e.response.status_code}")
    except Exception as e:
        print(f"[LLM] Stream error: {type(e).__name__}: {e}")
        raise RuntimeError(f"LLM stream failed: {e}")


def call_llm_text(
    prompt:      str,
    system:      str | None = None,
    model:       str | None = None,
    images:      list | None = None,
    num_predict: int = 1024,
    temperature: float | None = None,
    timeout:     int = 300,
) -> str:
    """
    One-shot text generation — no tools, no streaming.

    Used by the planner/summariser paths and by the bundled actions
    (code writing, file analysis, session summary…).

    `images` accepts PIL Images, file paths, raw bytes or base64 strings; when
    present the request is routed to the configured vision model.
    """
    url, default_model = get_llm_settings()
    endpoint = f"{url}/api/chat"

    b64_images = encode_images(images)
    chosen = model or (get_vision_model() if b64_images else None) or default_model

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    user_message: dict = {"role": "user", "content": prompt}
    if b64_images:
        user_message["images"] = b64_images
    messages.append(user_message)

    payload = {
        "model":      chosen,
        "messages":   messages,
        "stream":     False,
        "keep_alive": -1,
        "options":    _options(num_predict=num_predict, temperature=temperature),
    }

    try:
        resp = requests.post(endpoint, json=payload, timeout=timeout)
        resp.raise_for_status()
        return clean_text(resp.json().get("message", {}).get("content") or "")
    except requests.exceptions.ConnectionError:
        if ensure_ollama_running():
            try:
                resp = requests.post(endpoint, json=payload, timeout=timeout)
                resp.raise_for_status()
                return clean_text(resp.json().get("message", {}).get("content") or "")
            except Exception:
                pass
        raise RuntimeError(
            f"Cannot connect to Ollama at {url}. "
            "Make sure Ollama is installed and run: ollama serve"
        )
    except Exception as e:
        raise RuntimeError(f"LLM text call failed: {e}")


# ── Drop-in shim for the old `model.generate_content(...)` call sites ─────────

class _Response:
    def __init__(self, text: str):
        self.text = text

    def __str__(self) -> str:          # pragma: no cover - convenience
        return self.text


class Model:
    """
    Minimal stand-in for the old model object the action files used:

        model  = Model()
        result = model.generate_content(prompt).text
        result = model.generate_content([prompt, pil_image]).text

    Keeping the shape means the action files keep their existing prompts and
    only the import changes.
    """

    def __init__(self, model: str | None = None, system: str | None = None,
                 num_predict: int = 4096, temperature: float | None = None):
        self.model       = model
        self.system      = system
        self.num_predict = num_predict
        self.temperature = temperature

    def generate_content(self, contents) -> _Response:
        prompt, images = _split_contents(contents)
        text = call_llm_text(
            prompt,
            system=self.system,
            model=self.model,
            images=images,
            num_predict=self.num_predict,
            temperature=self.temperature,
        )
        return _Response(text)


def _split_contents(contents) -> tuple[str, list]:
    """mixed `contents` (str or mixed list) → (prompt, images)."""
    if isinstance(contents, str):
        return contents, []
    if isinstance(contents, dict):
        # {"mime_type": "image/png", "data": b"..."} / {"text": "..."}
        if "text" in contents:
            return str(contents["text"]), []
        return "", [contents]
    if isinstance(contents, (list, tuple)):
        parts:  list[str] = []
        images: list = []
        for item in contents:
            text, imgs = _split_contents(item)
            if text:
                parts.append(text)
            images.extend(imgs)
            if text or imgs:
                continue
            # a PIL image / path we couldn't split — keep it as an image
            images.append(item)
        return "\n\n".join(parts), images
    # PIL images and anything else are treated as attachments
    return "", [contents]
