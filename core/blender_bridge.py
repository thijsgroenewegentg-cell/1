"""Safe adapter from MARK to the user's existing Blender MCP server.

The Blender add-on shown in the Blender MCP panel is not itself the MCP
stdio process. MARK launches the fixed, well-known ``uvx blender-mcp`` server;
that server connects to the add-on's loopback socket (normally localhost:9876).
No arbitrary command or shell text is accepted. Only loopback hosts and the
allowlisted launcher forms are used, and dangerous code-execution MCP tools are
blocked before they can reach Blender.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path


_ALLOWED_ACTIONS = {
    "status", "list_objects", "inspect_object", "create_cube", "create_sphere",
    "create_cylinder", "create_camera", "create_light", "create_collection",
    "duplicate_object", "set_transform", "set_active_camera", "look_at",
    "set_material", "add_modifier", "delete_object", "set_render_settings",
    "render", "save_blend", "scene_checkpoint", "undo",
}

# The common Blender MCP server exposes this capability. MARK must not expose
# its arbitrary Python tool under the standing no-arbitrary-code policy.
_BLOCKED_TOOLS = {
    "execute_blender_code", "execute_python", "run_python", "run_code",
    "python", "shell", "command", "terminal", "eval",
}
_READ_ONLY_TOOL_NAMES = {
    "get_scene_info", "get_object_info", "get_viewport_screenshot",
    "get_polyhaven_status", "get_hyper3d_status", "get_hunyuan3d_status",
    "search_blender_docs", "list_objects", "inspect_object", "scene_info",
}
_MAX_LINE = 2_000_000


def _stored_settings() -> dict:
    try:
        from memory.config_manager import get_plugin_config
        value = get_plugin_config("blender_control")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _settings(overrides: dict | None = None) -> dict:
    stored = {**_stored_settings(), **(overrides or {})}
    host = (os.environ.get("BLENDER_HOST", "").strip()
            or os.environ.get("MARK_BLENDER_HOST", "").strip()
            or str(stored.get("host", "127.0.0.1"))).strip()
    raw_port = (os.environ.get("BLENDER_PORT", "").strip()
                or os.environ.get("MARK_BLENDER_PORT", "").strip()
                or str(stored.get("port", 9876)))
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        port = 9876
    port = port if 1 <= port <= 65535 else 9876
    launcher = (os.environ.get("MARK_BLENDER_MCP_LAUNCHER", "").strip()
                or str(stored.get("launcher", "uvx"))).strip()
    return {"host": host or "127.0.0.1", "port": port, "launcher": launcher or "uvx"}


def _launcher_argv(launcher: str) -> tuple[list[str] | None, str | None]:
    raw = str(launcher or "uvx").strip()
    name = Path(raw).name.lower()
    allowed = {"uvx", "uvx.exe", "python", "python3", "python.exe", "python3.exe"}
    if name not in allowed:
        return None, "The Blender MCP launcher must be uvx or a Python interpreter; arbitrary commands are not allowed."
    executable = raw
    if not Path(raw).is_absolute() and shutil.which(raw) is None:
        return None, f"The Blender MCP launcher was not found: {raw}. Install uv or choose a Python interpreter."
    if name.startswith("python"):
        return [executable, "-m", "blender_mcp"], None
    return [executable, "blender-mcp"], None


def configuration_error(settings: dict | None = None) -> str | None:
    value = settings or _settings()
    host = str(value.get("host", "")).strip().lower().strip("[]")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return "For safety, the Blender MCP connection only permits a loopback host."
    _, error = _launcher_argv(str(value.get("launcher", "uvx")))
    return error


class _MCPProcess:
    """One serialized JSON-RPC stdio session with the known Blender MCP server."""

    def __init__(self, settings: dict):
        self.settings = settings
        self.process: subprocess.Popen | None = None
        self.responses: queue.Queue[dict] = queue.Queue()
        self.unmatched: dict[str, dict] = {}
        self.lock = threading.RLock()
        self.reader: threading.Thread | None = None
        self.stderr_reader: threading.Thread | None = None
        self.stderr_tail: list[str] = []
        self.initialized = False
        self.tools_cache: list[dict] = []

    def _start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self.initialized = False
        self.tools_cache.clear()
        self.unmatched.clear()
        while True:
            try:
                self.responses.get_nowait()
            except queue.Empty:
                break
        argv, error = _launcher_argv(self.settings.get("launcher", "uvx"))
        if error or argv is None:
            raise RuntimeError(error or "Blender MCP launcher is unavailable.")
        env = os.environ.copy()
        env["BLENDER_HOST"] = str(self.settings["host"])
        env["BLENDER_PORT"] = str(self.settings["port"])
        # The upstream server supports this safety flag. It is harmless for an
        # older version and keeps MARK from opting into arbitrary code execution.
        env["BLENDER_MCP_SAFE_MODE"] = "1"
        try:
            self.process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                shell=False,
                env=env,
            )
        except Exception as exc:
            raise RuntimeError(f"Could not start Blender MCP with {' '.join(argv)}: {exc}") from exc
        self.reader = threading.Thread(target=self._read_stdout, daemon=True, name="mark-blender-mcp-reader")
        self.reader.start()
        self.stderr_reader = threading.Thread(target=self._read_stderr, daemon=True, name="mark-blender-mcp-stderr")
        self.stderr_reader.start()

    def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            if len(line) > _MAX_LINE:
                continue
            try:
                value = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                self.responses.put(value)

    def _read_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            text = line.strip()
            if text:
                self.stderr_tail.append(text[-500:])
                self.stderr_tail = self.stderr_tail[-20:]

    def _send(self, message: dict) -> None:
        if self.process is None or self.process.stdin is None or self.process.poll() is not None:
            raise RuntimeError("The Blender MCP process is not running.")
        raw = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        if len(raw) > _MAX_LINE:
            raise RuntimeError("The Blender MCP request is too large.")
        self.process.stdin.write(raw + "\n")
        self.process.stdin.flush()

    def _receive(self, request_id: str, timeout: float) -> dict:
        cached = self.unmatched.pop(request_id, None)
        if cached is not None:
            return cached
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                detail = self.stderr_tail[-1] if self.stderr_tail else "no diagnostic was returned"
                raise TimeoutError(f"Blender MCP did not answer in time ({detail}).")
            try:
                value = self.responses.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError("Blender MCP did not answer in time.") from exc
            value_id = str(value.get("id", ""))
            if value_id == request_id:
                return value
            if value_id:
                self.unmatched[value_id] = value

    def _request(self, method: str, params: dict | None, timeout: float) -> dict:
        request_id = f"mark-{uuid.uuid4().hex}"
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        response = self._receive(request_id, timeout)
        if isinstance(response.get("error"), dict):
            message = response["error"].get("message") or "Blender MCP rejected the request."
            raise RuntimeError(str(message))
        return response

    def _notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def ensure_initialized(self, timeout: float = 15.0) -> None:
        with self.lock:
            self._start()
            if self.initialized:
                return
            self._request(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "MARK", "version": "2.0.0"},
                },
                timeout,
            )
            self._notify("notifications/initialized")
            response = self._request("tools/list", {}, timeout)
            result = response.get("result") if isinstance(response, dict) else {}
            tools = result.get("tools") if isinstance(result, dict) else []
            self.tools_cache = [tool for tool in tools if isinstance(tool, dict) and self._safe_tool_name(tool.get("name"))]
            self.initialized = True

    @staticmethod
    def _safe_tool_name(name) -> bool:
        value = str(name or "").strip().lower()
        if not value:
            return False
        if value in _BLOCKED_TOOLS:
            return False
        return not any(part in value for part in ("execute_blender_code", "execute_python", "run_python", "shell", "terminal", "eval"))

    def list_tools(self, timeout: float = 15.0) -> list[dict]:
        self.ensure_initialized(timeout)
        return list(self.tools_cache)

    def call_tool(self, name: str, arguments: dict | None = None,
                  timeout: float = 90.0) -> tuple[bool, str]:
        tool = str(name or "").strip()
        if not self._safe_tool_name(tool):
            return False, "That Blender MCP tool is blocked because it can execute arbitrary code or commands."
        with self.lock:
            self.ensure_initialized(timeout=min(timeout, 30.0))
            available = {str(item.get("name")) for item in self.tools_cache}
            if available and tool not in available:
                return False, f"Blender MCP tool '{tool}' was not advertised by the connected server."
            response = self._request(
                "tools/call",
                {"name": tool, "arguments": dict(arguments or {})},
                timeout,
            )
            result = response.get("result") if isinstance(response, dict) else {}
            if not isinstance(result, dict):
                return False, "Blender MCP returned no tool result."
            content = result.get("content") or []
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                    elif item.get("type") == "image":
                        parts.append("[Blender MCP returned an image]")
            text = "\n".join(part for part in parts if part)
            if result.get("isError"):
                return False, text or "Blender MCP reported a tool error."
            structured = result.get("structuredContent")
            if not text and structured is not None:
                text = json.dumps(structured, ensure_ascii=False)
            return True, text or "Blender MCP action completed."

    def close(self) -> None:
        with self.lock:
            if self.process is None:
                return
            try:
                if self.process.stdin:
                    self.process.stdin.close()
            except Exception:
                pass
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
            self.initialized = False
            self.tools_cache.clear()


_client_lock = threading.RLock()
_client: _MCPProcess | None = None
_client_signature: tuple | None = None


def _get_client(settings: dict) -> _MCPProcess:
    global _client, _client_signature
    signature = (settings.get("host"), settings.get("port"), settings.get("launcher"))
    with _client_lock:
        if _client is None or _client_signature != signature:
            if _client is not None:
                _client.close()
            _client = _MCPProcess(settings)
            _client_signature = signature
        return _client


def list_tools(overrides: dict | None = None) -> tuple[bool, str]:
    settings = _settings(overrides)
    error = configuration_error(settings)
    if error:
        return False, error
    try:
        tools = _get_client(settings).list_tools()
        rows = []
        for tool in tools:
            name = str(tool.get("name", "")).strip()
            description = " ".join(str(tool.get("description", "")).split())
            schema = tool.get("inputSchema") or tool.get("input_schema")
            schema_text = ""
            if isinstance(schema, dict):
                schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))[:1200]
            row = f"- {name}"
            if description:
                row += f": {description[:260]}"
            if schema_text:
                row += f"\n  arguments: {schema_text}"
            rows.append(row)
        return True, "Blender MCP tools:\n" + ("\n".join(rows) if rows else "(none)")
    except Exception as exc:
        return False, _explain_connection_error(settings, exc)


def call_tool(name: str, arguments: dict | None = None,
              timeout: float = 90.0, overrides: dict | None = None) -> tuple[bool, str]:
    settings = _settings(overrides)
    error = configuration_error(settings)
    if error:
        return False, error
    try:
        return _get_client(settings).call_tool(name, arguments, timeout=timeout)
    except Exception as exc:
        return False, _explain_connection_error(settings, exc)


def _explain_connection_error(settings: dict, exc: Exception) -> str:
    text = str(exc)
    lower = text.lower()
    if "connect" in lower or "refused" in lower or "9876" in lower:
        return (
            f"Could not connect to Blender MCP at {settings['host']}:{settings['port']}. "
            "Open Blender's Blender MCP panel, keep port 9876, click 'Connect to MCP server', "
            "and make sure uvx/blender-mcp is available to MARK. " + text
        )
    return f"Blender MCP failed: {text}"


def _mapped_action(action: str, parameters: dict) -> tuple[str | None, dict]:
    """Map MARK's existing safe actions to common blender-mcp tool names."""
    params = dict(parameters or {})
    object_name = str(params.get("object_name", "")).strip()
    common = {
        "status": ("get_scene_info", {}),
        "inspect_object": ("get_object_info", {"object_name": object_name, "name": object_name}),
        "list_objects": ("get_scene_info", {}),
    }
    if action in common:
        return common[action]
    # Mutating actions are intentionally not guessed across incompatible MCP
    # schemas. The model can use list_tools + call_tool with exact arguments.
    return None, params


def call(action: str, parameters: dict | None = None,
         timeout: float = 90.0, overrides: dict | None = None) -> tuple[bool, str]:
    action = str(action or "").strip().lower().replace("-", "_")
    if action not in _ALLOWED_ACTIONS:
        return False, "Unknown Blender action."
    mapped, args = _mapped_action(action, dict(parameters or {}))
    if mapped:
        ok, result = call_tool(mapped, args, timeout=timeout, overrides=overrides)
        if ok and action == "list_objects":
            return True, result
        return ok, result
    return False, (
        f"The existing Blender MCP server does not expose a standard mapping for '{action}'. "
        "Use blender_control action list_tools, then call the advertised tool by name."
    )


def test_connection(overrides: dict | None = None) -> tuple[bool, str]:
    ok, result = list_tools(overrides)
    if not ok:
        return False, result
    return True, "Blender MCP connection succeeded.\n" + result


def close() -> None:
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
            _client = None
