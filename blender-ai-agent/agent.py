#!/usr/bin/env python3
"""
Free AI agent that builds things in Blender.

Talks to Blender over one of three transports (auto-detected):
  - the BlenderMCP add-on you may already have (direct socket, port 9876)
  - the AI Agent Bridge add-on / bridge_standalone.py (this project)
  - any generic MCP server via stdio (e.g. `uvx blender-mcp`)

Free by default: Ollama locally; free cloud options (Groq, Gemini) built in,
with automatic fallback. Vision mode lets the agent render and inspect its
own work. Stdlib only.

Examples:
    python agent.py "build a red sports car"
    python agent.py --vision "a cozy cabin; check your work"
    python agent.py --transport blendermcp "low-poly windmill"
    python agent.py --mcp-cmd "uvx blender-mcp" "chess set"
    python agent.py --preset product "a sneaker on a pedestal"
    python agent.py --watch tasks.txt          # continuous build queue
    python webui.py                            # browser chat UI
"""

import argparse
import base64
import datetime
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request

import transports
from blender_helpers import HELPERS_SOURCE, HELPER_NAMES
from presets import PRESETS, list_presets, preset_code

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
MAX_OUTPUT_CHARS = 6000
DEFAULT_OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

PROVIDERS = {
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5-coder:7b",
        "vision_model": "llama3.2-vision:11b",
        "api_key": "ollama",
        "hint": "Install Ollama from https://ollama.com and run: ollama pull qwen2.5-coder:7b",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "vision_model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "key_env": "GROQ_API_KEY",
        "hint": "Free key at https://console.groq.com/keys then set GROQ_API_KEY",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.0-flash",
        "vision_model": "gemini-2.0-flash",
        "key_env": "GEMINI_API_KEY",
        "hint": "Free key at https://aistudio.google.com/apikey then set GEMINI_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "vision_model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
        "hint": "Set OPENAI_API_KEY (paid; convenience only)",
    },
}

SYSTEM_PROMPT = """You are BlenderBot, an AI agent that builds 3D scenes in a \
LIVE Blender session by writing Python with the `bpy` API.

HOW YOU WORK
- You have tools - use them. Always start with get_scene_info.
- Build incrementally: geometry, materials, lighting/camera, then verify.
- Use print() to inspect; stdout is returned to you. Read tracebacks and fix \
errors; never repeat failing code. If things get messy, call undo_blender.
- Make sensible assumptions; name objects and materials descriptively.
- Finish with save_blend, a visual check (render_and_inspect if available, \
else render_preview), then task_complete.

IMPORTANT: PYTHON VARIABLES DO NOT PERSIST BETWEEN CALLS ON MCP BACKENDS.
After creating an object, give it a name and fetch it again later by name:
    bpy.ops.mesh.primitive_cube_add(); bpy.context.active_object.name = "Body"
    ...later...
    body = bpy.data.objects["Body"]
Do not rely on variables from previous calls.

HELPER FUNCTIONS (always defined at the top of your environment):
{helpers}
Use them - they handle Blender version differences for you. Examples:
    clear_scene()
    ground = add_primitive("plane", "Ground", size=20)
    mat = make_material("RedPaint", (0.6, 0.05, 0.05), roughness=0.3)
    body = add_primitive("cube", "Body", location=(0,0,1), material=mat)
    add_bevel(bpy.data.objects["Body"], width=0.1)
    add_light('AREA', location=(4,-4,6), energy=700, target=(0,0,1))
    add_camera(location=(7,-7,5), target=(0,0,1))
    set_world((0.05,0.07,0.1), 0.4); use_eevee()
    quick_setup()  # camera + 3-point light + world in one call

PRESETS (apply_preset tool): {presets}
Apply a preset when it matches the request instead of building lighting from \
scratch - e.g. product shots, architecture, outdoor scenes.

VISION: render_and_inspect attaches the actual screenshot for you to study. \
Use it after major milestones and fix anything that looks wrong (floating \
parts, bad framing, wrong colors). Do not trust code that merely ran.

RULES: no blocking code (sleep/infinite loops/file dialogs); prefer bpy.data \
and bpy.context.active_object over context-dependent UI ops; write complete \
runnable code each call; keep each call focused on one logical change.
""".format(helpers=", ".join(HELPER_NAMES),
           presets=", ".join(sorted(PRESETS)))

TOOL_DEFS = {
    "get_scene_info": {
        "description": "Current Blender scene: objects, transforms, materials, "
                       "camera, render settings. Call first.",
        "parameters": {"type": "object", "properties": {}},
    },
    "execute_blender_code": {
        "description": "Run bpy Python in the live Blender session. Returns "
                       "stdout and tracebacks. NOTE: Python variables do not "
                       "persist - name objects and re-fetch by name.",
        "parameters": {"type": "object",
                       "properties": {"code": {"type": "string",
                                               "description": "Python/bpy code."}},
                       "required": ["code"]},
    },
    "apply_preset": {
        "description": "Apply a scene-template preset (lighting/camera/world).",
        "parameters": {"type": "object",
                       "properties": {"name": {"type": "string",
                                               "enum": sorted(PRESETS)}},
                       "required": ["name"]},
    },
    "render_and_inspect": {
        "description": "Capture a fast viewport screenshot and analyze the "
                       "IMAGE attached to the result. Use to visually verify.",
        "parameters": {"type": "object",
                       "properties": {"note": {"type": "string",
                                               "description": "What to check."}}},
    },
    "render_preview": {
        "description": "Render a final image to PNG for the USER (slower, "
                       "camera render).",
        "parameters": {"type": "object",
                       "properties": {"filepath": {"type": "string"}}},
    },
    "save_blend": {
        "description": "Save the project as a .blend file.",
        "parameters": {"type": "object",
                       "properties": {"filepath": {"type": "string"}}},
    },
    "export_model": {
        "description": "Export mesh for games/3D printing.",
        "parameters": {"type": "object",
                       "properties": {"format": {"type": "string",
                                                 "enum": ["GLB", "GLTF", "STL", "FBX", "OBJ"]},
                                       "filepath": {"type": "string"}},
                       "required": ["format"]},
    },
    "undo_blender": {
        "description": "Undo the last Blender change.",
        "parameters": {"type": "object", "properties": {}},
    },
    "task_complete": {
        "description": "The request is fully built and verified. Stops the loop.",
        "parameters": {"type": "object",
                       "properties": {"summary": {"type": "string"}},
                       "required": ["summary"]},
    },
}
TEXT_TOOL_ORDER = ["get_scene_info", "execute_blender_code", "apply_preset",
                   "render_preview", "save_blend", "export_model",
                   "undo_blender", "task_complete"]
VISION_TOOL_ORDER = ["get_scene_info", "execute_blender_code", "apply_preset",
                     "render_and_inspect", "render_preview", "save_blend",
                     "export_model", "undo_blender", "task_complete"]


def build_tools(vision):
    order = VISION_TOOL_ORDER if vision else TEXT_TOOL_ORDER
    return [{"type": "function",
             "function": {"name": n, "description": TOOL_DEFS[n]["description"],
                          "parameters": TOOL_DEFS[n]["parameters"]}}
            for n in order]


# --------------------------------------------------------------------------
# LLM client
# --------------------------------------------------------------------------

def detect_provider(explicit):
    if explicit:
        return explicit
    for env, name in (("GROQ_API_KEY", "groq"), ("GEMINI_API_KEY", "gemini"),
                      ("OPENAI_API_KEY", "openai")):
        if os.environ.get(env):
            return name
    return "ollama"


class LLMClient:
    def __init__(self, provider="ollama", model=None, base_url=None,
                 api_key=None, vision=False, temperature=0.2, log=print):
        cfg = PROVIDERS[provider]
        self.provider = provider
        self.base_url = (base_url or cfg["base_url"]).rstrip("/")
        self.model = model or (cfg.get("vision_model") if vision else None) or cfg["model"]
        key = api_key or (os.environ.get(cfg["key_env"]) if cfg.get("key_env") else "")
        self.api_key = key or cfg.get("api_key", "")
        self.vision = vision
        self.temperature = temperature
        self.hint = cfg.get("hint", "")
        self.log = log

    def chat(self, messages, tools=None, retries=3):
        payload = {"model": self.model, "messages": messages,
                   "temperature": self.temperature}
        if tools:
            payload["tools"] = tools
        data = json.dumps(payload).encode("utf-8")
        for attempt in range(retries):
            req = urllib.request.Request(
                self.base_url + "/chat/completions", data=data,
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + self.api_key})
            try:
                with urllib.request.urlopen(req, timeout=600) as resp:
                    return json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:500]
                if exc.code in (429, 500, 502, 503) and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError("LLM HTTP %s for %s (%s): %s\nHint: %s"
                                   % (exc.code, self.base_url, self.model, detail, self.hint))
            except urllib.error.URLError as exc:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError("Cannot reach LLM at %s: %s\nHint: %s"
                                   % (self.base_url, exc.reason, self.hint))


def _chain(primary, args, vision):
    names = [primary]
    if not args.no_fallback:
        for name in ("ollama", "groq", "gemini"):
            if name not in names:
                names.append(name)
    clients = []
    for name in names:
        cfg = PROVIDERS[name]
        if cfg.get("key_env") and not os.environ.get(cfg["key_env"]) and not args.api_key:
            continue
        clients.append(LLMClient(
            provider=name,
            model=args.model if name == primary else None,
            base_url=args.base_url if name == primary else None,
            api_key=args.api_key if name == primary else None,
            vision=vision))
    return clients or [LLMClient(provider=primary, vision=vision)]


def chat_route(text_clients, vision_clients, messages, tools, vision_enabled, log):
    """Route to vision models when an image is in context, else fast models."""
    needs_vision = vision_enabled and any(
        isinstance(m.get("content"), list) and
        any(p.get("type") == "image_url" for p in m["content"])
        for m in messages)
    clients = vision_clients if needs_vision else text_clients
    last = None
    for i, llm in enumerate(clients):
        try:
            return llm.chat(messages, tools)
        except RuntimeError as exc:
            last = exc
            log("[%s model '%s' failed: %s]"
                % ("vision" if needs_vision else "text", llm.provider,
                   str(exc).splitlines()[0][:160]))
            if i < len(clients) - 1:
                log("[falling back to %s]" % clients[i + 1].provider)
    raise last


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _truncate(text):
    text = "" if text is None else str(text)
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + "\n...[truncated]"


def _repair_json(raw):
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    candidate = (m.group(0) if m else raw).replace("\n", " ")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    for key in ("code", "summary", "filepath", "format", "note", "name"):
        mm = re.search(r"['\"]?%s['\"]?\s*:\s*\"(.*)\"\s*[,})\]]*$" % key, candidate, re.DOTALL)
        if not mm:
            mm = re.search(r"['\"]?%s['\"]?\s*:\s*'(.*)'\s*[,})\]]*$" % key, candidate, re.DOTALL)
        if mm:
            return {key: mm.group(1)}
    return {}


def _out(prefix, ext):
    os.makedirs(DEFAULT_OUT_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(DEFAULT_OUT_DIR, "%s_%s.%s" % (prefix, stamp, ext))


def _data_uri(path):
    with open(path, "rb") as fh:
        return "data:image/png;base64," + base64.b64encode(fh.read()).decode("ascii")


def _encode_image(path):
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
            "webp": "webp", "gif": "gif"}.get(ext, "png")
    with open(path, "rb") as fh:
        return "data:image/%s;base64,%s" % (mime, base64.b64encode(fh.read()).decode("ascii"))


def _ask_approval(code):
    print("\n--- code to run in Blender ---")
    print(code)
    print("------------------------------")
    try:
        ans = input("Approve? [Enter=run, s=skip, q=quit] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return "run"
    return "quit" if ans in ("q", "quit") else ("skip" if ans in ("s", "n", "no") else "run")


# --------------------------------------------------------------------------
# Agent
# --------------------------------------------------------------------------

class BlenderAgent:
    def __init__(self, transport, text_clients, vision_clients,
                 vision=False, approve=False, log=print):
        self.t = transport
        self.text_clients = text_clients
        self.vision_clients = vision_clients
        self.vision = vision
        self.approve = approve
        self.log = log
        self.helpers_installed = False

    def install_helpers(self):
        """Make the helper toolkit available in the exec environment."""
        if self.helpers_installed:
            return
        # On our bridge the namespace persists: install once. On BlenderMCP
        # the namespace is fresh per call, so helpers are prepended each time.
        if not getattr(self.t, "PERSISTENT_NAMESPACE", True):
            self.helpers_installed = True
            return
        out = self.t.exec_code(HELPERS_SOURCE)
        if not out.get("error"):
            self.helpers_installed = True

    def _exec(self, code):
        if not getattr(self.t, "PERSISTENT_NAMESPACE", True):
            code = HELPERS_SOURCE + "\n" + code
        return self.t.exec_code(code)

    def dispatch(self, name, args):
        """Returns (text, extra_messages)."""
        if name == "get_scene_info":
            try:
                return json.dumps(self.t.scene_info(), indent=2), []
            except Exception as exc:
                return "ERROR getting scene info: %s" % exc, []

        if name == "execute_blender_code":
            code = args.get("code", "")
            self.log("\n--- Blender code ---\n" + code.strip() + "\n--------------------")
            if self.approve:
                decision = _ask_approval(code)
                if decision == "quit":
                    raise KeyboardInterrupt
                if decision == "skip":
                    return "Skipped by user.", []
            out = self._exec(code)
            parts = []
            if (out.get("stdout") or "").strip():
                parts.append("stdout:\n" + out["stdout"].strip())
            if out.get("error"):
                parts.append("Python error (fix it):\n" + out["error"])
            return _truncate("\n\n".join(parts) or "Code ran with no output."), []

        if name == "apply_preset":
            pname = args.get("name", "")
            if pname not in PRESETS:
                return "Unknown preset %r. Available: %s" % (pname, ", ".join(sorted(PRESETS))), []
            self.log("[applying preset: %s]" % pname)
            out = self._exec(preset_code(pname))
            if out.get("error"):
                return "Preset failed:\n" + out["error"], []
            return "Preset '%s' applied (%s)." % (pname, PRESETS[pname]["label"]), []

        if name in ("render_and_inspect", "render_preview"):
            inspect = name == "render_and_inspect"
            path = _out("viewport" if inspect else "render", "png")
            try:
                if inspect:
                    out_path = self.t.viewport_screenshot(path)
                    self.log("[viewport screenshot: %s]" % out_path)
                else:
                    out_path = self.t.render(path)
                    self.log("[render: %s]" % out_path)
            except Exception as exc:
                return "Capture failed: %s" % exc, []
            text = "Image saved to: %s" % out_path
            extra = []
            if inspect:
                try:
                    extra.append({"role": "user", "content": [
                        {"type": "text", "text":
                            "This is a screenshot of the current Blender viewport "
                            "(note: it reflects the viewport camera if no scene "
                            "camera is active). Inspect it for problems - floating "
                            "or intersecting parts, missing objects, wrong colors, "
                            "bad framing/lighting - and fix them with code."
                            + ((" Focus: " + args["note"]) if args.get("note") else "")},
                        {"type": "image_url", "image_url": {"url": _data_uri(out_path)}},
                    ]})
                except Exception as exc:
                    text += "\n(warning: could not attach image: %s)" % exc
            return text, extra

        if name == "save_blend":
            path = args.get("filepath") or _out("scene", "blend")
            if not path.endswith(".blend"):
                path += ".blend"
            try:
                return "Saved: %s" % self.t.save(path), []
            except Exception as exc:
                return "Save failed: %s" % exc, []

        if name == "export_model":
            fmt = (args.get("format") or "").upper()
            path = args.get("filepath") or _out("export", fmt.lower())
            try:
                return "Exported %s: %s" % (fmt, self.t.export(path, fmt)), []
            except Exception as exc:
                return "Export failed: %s" % exc, []

        if name == "undo_blender":
            try:
                self.t.undo()
                return "Undid last step.", []
            except Exception as exc:
                return "Undo failed: %s" % exc, []

        return "ERROR: unknown tool %r" % name, []

    def run_task(self, task, max_iters=30, reference_image=None):
        self.install_helpers()
        tools = build_tools(self.vision)
        content = task
        if reference_image:
            self.log("[reference image: %s]" % reference_image)
            content = [{"type": "text",
                        "text": task + "\n(Attached reference image - build something based on it.)"},
                       {"type": "image_url", "image_url": {"url": _encode_image(reference_image)}}]
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content}]

        for step in range(1, max_iters + 1):
            self.log("\n[step %d] thinking..." % step)
            message = chat_route(self.text_clients, self.vision_clients,
                                 messages, tools, self.vision, self.log)
            messages.append(message)
            if (message.get("content") or "").strip():
                self.log("AI: " + message["content"].strip())
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return message.get("content") or "Finished (no task_complete)."
            done = None
            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                args = _repair_json(fn.get("arguments") or "{}")
                if name == "task_complete":
                    done = args.get("summary", "Task complete.")
                    messages.append({"role": "tool", "tool_call_id": call.get("id", "0"),
                                     "content": "done"})
                    continue
                try:
                    text, extra = self.dispatch(name, args)
                except KeyboardInterrupt:
                    return "Stopped by user."
                except (ConnectionError, OSError) as exc:
                    raise RuntimeError("Lost connection to Blender: %s" % exc)
                messages.append({"role": "tool", "tool_call_id": call.get("id", "0"),
                                 "content": text})
                messages.extend(extra)
            if done:
                self.log("\n=== Done: %s ===" % done)
                self.log("[files in: %s]" % DEFAULT_OUT_DIR)
                return done
        return "Stopped after %d steps." % max_iters


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def connect_blender(args):
    if args.mcp_cmd:
        t = transports.connect("mcp-stdio", mcp_command=args.mcp_cmd)
    else:
        t = transports.connect(args.transport, args.host, args.port)
    print("Connected via: %s" % t.name)
    try:
        info = t.ping()
        if info:
            self_note = ""
            if isinstance(info, dict) and info.get("blender"):
                self_note = "Blender %s" % info["blender"]
            elif isinstance(info, dict) and info.get("pong"):
                self_note = "BlenderMCP addon"
            if self_note:
                print("  -> %s" % self_note)
    except Exception:
        pass
    return t


def watch_loop(path, agent, max_iters, log=print):
    """Continuous mode: run each line appended to `path` as a task (or stdin)."""
    log("[watch] reading tasks from %s - one request per line, Ctrl+C to stop"
        % ("stdin" if path in (None, "-") else path))
    if path in (None, "-"):
        for line in sys.stdin:
            task = line.strip()
            if task and not task.startswith("#"):
                agent.run_task(task, max_iters=max_iters)
        return
    # tail a file
    seen = 0
    if os.path.exists(path):
        seen = os.path.getsize(path)
    while True:
        try:
            size = os.path.getsize(path) if os.path.exists(path) else 0
            if size < seen:
                seen = 0  # file truncated/rotated
            if size > seen:
                with open(path, "r", encoding="utf-8") as fh:
                    fh.seek(seen)
                    for line in fh:
                        task = line.strip()
                        if task and not task.startswith("#"):
                            log("\n[watch] task: %s" % task)
                            agent.run_task(task, max_iters=max_iters)
                    seen = fh.tell()
            time.sleep(1.0)
        except KeyboardInterrupt:
            log("\n[watch] stopped")
            return


def main(argv=None):
    p = argparse.ArgumentParser(description="Free AI agent that builds things in Blender.")
    p.add_argument("task", nargs="?", help="What to build. Omit for interactive chat.")
    p.add_argument("--transport", default="auto",
                   choices=["auto", "bridge", "blendermcp", "mcp-stdio"],
                   help="How to reach Blender (default: auto-detect).")
    p.add_argument("--mcp-cmd", default=None,
                   help="MCP server command for --transport mcp-stdio (default: 'uvx blender-mcp').")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--provider", default=os.environ.get("LLM_PROVIDER"),
                   choices=sorted(PROVIDERS.keys()))
    p.add_argument("--model", default=os.environ.get("LLM_MODEL"))
    p.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL"))
    p.add_argument("--api-key", default=None)
    p.add_argument("--vision", action="store_true",
                   help="Agent renders/screenshots and inspects its own work.")
    p.add_argument("--image", metavar="PATH", help="Reference image to build from.")
    p.add_argument("--preset", choices=sorted(PRESETS),
                   help="Apply a scene preset before starting.")
    p.add_argument("--no-fallback", action="store_true")
    p.add_argument("--approve", action="store_true")
    p.add_argument("--max-iters", type=int, default=30)
    p.add_argument("--watch", nargs="?", const="-", metavar="FILE",
                   help="Continuous mode: run tasks line-by-line from FILE (or stdin).")
    p.add_argument("--exec", metavar="FILE", help="Run a .py file in Blender, no LLM.")
    args = p.parse_args(argv)

    if args.image and not args.vision:
        args.vision = True

    try:
        t = connect_blender(args)
    except RuntimeError as exc:
        print("\n[connection error] %s" % exc)
        sys.exit(1)

    if args.exec:
        with open(args.exec, "r", encoding="utf-8") as fh:
            out = t.exec_code(fh.read())
        if out.get("stdout"):
            print(out["stdout"], end="")
        if out.get("error"):
            print(out["error"], file=sys.stderr)
            sys.exit(1)
        return

    primary = detect_provider(args.provider)
    text_clients = _chain(primary, args, vision=False)
    vision_clients = _chain(primary, args, vision=True) if args.vision else text_clients
    agent = BlenderAgent(t, text_clients, vision_clients,
                         vision=args.vision, approve=args.approve)

    print("LLMs: text=%s | vision=%s"
          % (" -> ".join(c.provider + ":" + c.model for c in text_clients),
             " -> ".join(c.provider + ":" + c.model for c in vision_clients) if args.vision else "off"))

    if args.preset:
        agent.install_helpers()
        out = agent._exec(preset_code(args.preset))
        print("[preset %s] %s" % (args.preset, (out.get("stdout") or out.get("error") or "").strip()))

    try:
        if args.watch is not None:
            watch_loop(None if args.watch == "-" else args.watch, agent, args.max_iters)
        elif args.task:
            agent.run_task(args.task, max_iters=args.max_iters,
                           reference_image=args.image)
        else:
            print("\nInteractive mode. Commands: /scene /undo /render /save "
                  "/preset <name> /quit\nPresets: %s\n" % ", ".join(sorted(PRESETS)))
            while True:
                try:
                    line = input("you > ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if not line:
                    continue
                if line in ("/quit", "/exit"):
                    break
                if line == "/scene":
                    print(json.dumps(t.scene_info(), indent=2))
                elif line == "/undo":
                    t.undo()
                elif line == "/render":
                    print(t.render(_out("render", "png")))
                elif line == "/save":
                    print(t.save(_out("scene", "blend")))
                elif line.startswith("/preset"):
                    name = line.split(maxsplit=1)[1] if len(line.split()) > 1 else ""
                    agent.install_helpers()
                    out = agent._exec(preset_code(name))
                    print(out.get("stdout") or out.get("error"))
                else:
                    try:
                        agent.run_task(line, max_iters=args.max_iters)
                    except RuntimeError as exc:
                        print("[error] %s" % exc)
    except RuntimeError as exc:
        print("\n[agent error] %s" % exc)
        if "11434" in str(exc) or "ollama" in str(exc).lower():
            print("\nOllama quick start:\n  1. https://ollama.com\n"
                  "  2. ollama pull qwen2.5-coder:7b"
                  + ("\n     ollama pull llama3.2-vision:11b" if args.vision else ""))
        sys.exit(1)
    finally:
        t.close()


if __name__ == "__main__":
    main()
