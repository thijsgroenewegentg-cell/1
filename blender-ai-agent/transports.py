# SPDX-License-Identifier: MIT
"""
Transports connecting the agent to Blender. Three backends:

1. BridgeTransport  - our own addon.py / bridge_standalone.py (JSON lines,
   rich typed commands: exec / render / save / export / undo ...).
2. BlenderMCPTransport - talks DIRECTLY to the BlenderMCP add-on
   (github.com/ahujasid/blender-mcp) that many people already have installed:
   raw JSON {"type": cmd, "params": {...}} on port 9876. No extra process.
3. MCPStdioTransport - a generic Model Context Protocol client that spawns
   any MCP server (e.g. `uvx blender-mcp`, `npx -y @modelcontextprotocol/...`)
   over stdio and calls its tools through JSON-RPC.

All expose the same small interface used by agent.py:
    ping() -> dict
    scene_info() -> dict
    exec_code(code) -> {"stdout": str, "error": str|None, "extra": {...}}
    render(filepath) -> filepath
    viewport_screenshot(filepath) -> filepath
    save(filepath) -> filepath
    export(filepath, fmt) -> filepath
    undo() -> None
    close()
"""

import io
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
import contextlib


# --------------------------------------------------------------------------
# 1. Our own bridge (JSON lines, request ids)
# --------------------------------------------------------------------------

class BridgeTransport:
    name = "bridge (AI Agent Bridge addon)"

    def __init__(self, host="127.0.0.1", port=9876, timeout=300):
        self.host, self.port = host, port
        self.sock = socket.create_connection((host, port), timeout=10)
        self.sock.settimeout(timeout)
        self._buf = b""
        self._id = 0

    def _call(self, cmd, **args):
        self._id += 1
        rid = self._id
        self.sock.sendall((json.dumps({"id": rid, "cmd": cmd, "args": args}) + "\n").encode())
        while True:
            while b"\n" not in self._buf:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("Blender closed the connection")
                self._buf += chunk
            line, self._buf = self._buf.split(b"\n", 1)
            reply = json.loads(line.decode("utf-8"))
            if reply.get("id") == rid:
                return reply

    def ping(self):
        r = self._call("ping")
        return r.get("result", {}) if r.get("ok") else {}

    def scene_info(self):
        r = self._call("scene_info")
        if not r.get("ok"):
            raise RuntimeError(r.get("error", "scene_info failed"))
        return r["result"]

    def exec_code(self, code):
        r = self._call("exec", code=code)
        if not r.get("ok"):
            return {"stdout": "", "error": r.get("error", "exec failed"), "extra": {}}
        res = r.get("result") or {}
        return {"stdout": res.get("stdout", ""), "error": res.get("error"), "extra": {}}

    def render(self, filepath=None):
        r = self._call("render", filepath=filepath)
        res = r.get("result") or {}
        if not r.get("ok") or res.get("error"):
            raise RuntimeError(res.get("error") or r.get("error") or "render failed")
        return res.get("filepath", filepath)

    def viewport_screenshot(self, filepath=None):
        # Our bridge does not have a separate viewport screenshot; use render.
        return self.render(filepath)

    def save(self, filepath):
        r = self._call("save", filepath=filepath)
        res = r.get("result") or {}
        if not r.get("ok") or res.get("error"):
            raise RuntimeError(res.get("error") or "save failed")
        return res.get("filepath", filepath)

    def export(self, filepath, fmt):
        r = self._call("export", filepath=filepath, format=fmt)
        res = r.get("result") or {}
        if not r.get("ok") or res.get("error"):
            raise RuntimeError(res.get("error") or "export failed")
        return res.get("filepath", filepath)

    def undo(self):
        self._call("undo")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# --------------------------------------------------------------------------
# 2. Direct BlenderMCP add-on socket (raw JSON, no framing)
# --------------------------------------------------------------------------

class BlenderMCPTransport:
    name = "BlenderMCP addon (direct socket)"

    def __init__(self, host="127.0.0.1", port=9876, timeout=300):
        self.host, self.port = host, port
        self.sock = socket.create_connection((host, port), timeout=10)
        self.sock.settimeout(timeout)
        self._lock = threading.Lock()

    def _call(self, cmd_type, **params):
        """Send {"type", "params"}; read until a full JSON object arrives."""
        with self._lock:
            request = json.dumps({"type": cmd_type, "params": params})
            self.sock.sendall(request.encode("utf-8"))
            buf = b""
            # The addon replies with one JSON object per command. Decode with
            # raw_decode so we can tolerate pipelined / trailing data.
            while True:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("BlenderMCP closed the connection")
                buf += chunk
                text = buf.decode("utf-8", "replace").lstrip()
                try:
                    obj, _idx = json.JSONDecoder().raw_decode(text)
                    return obj
                except json.JSONDecodeError:
                    continue  # wait for the rest of the response

    def _expect_success(self, r, what):
        if r.get("status") == "success":
            return r.get("result", {})
        raise RuntimeError("BlenderMCP %s: %s" % (what, r.get("message", r)))

    def ping(self):
        return self._expect_success(self._call("ping"), "ping")

    def scene_info(self):
        return self._expect_success(self._call("get_scene_info"), "get_scene_info")

    PERSISTENT_NAMESPACE = False  # BlenderMCP uses a fresh namespace per call

    def exec_code(self, code):
        r = self._call("execute_code", code=code)
        if r.get("status") != "success":
            return {"stdout": "", "error": r.get("message", "execute_code failed"), "extra": {}}
        res = r.get("result", {})
        # BlenderMCP captures stdout into result["result"]; exceptions come
        # back as {"status": "error", "message": ...}.
        stdout = res.get("result", "") if isinstance(res, dict) else str(res)
        return {"stdout": stdout or "", "error": None, "extra": res if isinstance(res, dict) else {}}

    def _data_url_to_file(self, data_url, filepath):
        m = re.match(r"data:image/(\w+);base64,(.*)", data_url, re.DOTALL)
        if not m:
            raise RuntimeError("unexpected screenshot payload")
        import base64
        data = base64.b64decode(m.group(2))
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "wb") as fh:
            fh.write(data)
        return filepath

    def viewport_screenshot(self, filepath):
        # The add-on writes the PNG to `filepath` itself; agent and Blender are
        # on the same host, so we read it straight from disk.
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        r = self._call("get_viewport_screenshot",
                       filepath=os.path.abspath(filepath), max_size=1280, format="png")
        res = self._expect_success(r, "get_viewport_screenshot")
        if res.get("data_url"):  # future/protocol variants
            return self._data_url_to_file(res["data_url"], filepath)
        path = res.get("filepath") or filepath
        if not os.path.exists(path):
            raise RuntimeError("viewport screenshot was not written to %s" % path)
        return path

    def render(self, filepath=None):
        # BlenderMCP has no dedicated camera-render command; viewport screenshot
        # is the fast visual feedback path. For a "real" render the agent can
        # run bpy.ops.render.render via execute_code and read the file itself.
        return self.viewport_screenshot(filepath)

    def save(self, filepath):
        filepath = os.path.abspath(filepath)
        code = "import bpy\nbpy.ops.wm.save_as_mainfile(filepath=%r)" % filepath
        out = self.exec_code(code)
        if out["error"]:
            raise RuntimeError(out["error"])
        return filepath

    def export(self, filepath, fmt):
        fmt = fmt.upper()
        ops = {
            "GLB": "bpy.ops.export_scene.gltf(filepath=%r, export_format='GLB')",
            "GLTF": "bpy.ops.export_scene.gltf(filepath=%r)",
            "STL": "bpy.ops.export_mesh.stl(filepath=%r)",
            "FBX": "bpy.ops.export_scene.fbx(filepath=%r)",
            "OBJ": "bpy.ops.wm.obj_export(filepath=%r)",
        }
        if fmt not in ops:
            raise RuntimeError("unsupported export format %r" % fmt)
        filepath = os.path.abspath(filepath)
        out = self.exec_code("import bpy\n" + ops[fmt] % filepath)
        if out["error"]:
            raise RuntimeError(out["error"])
        return filepath

    def undo(self):
        self.exec_code("import bpy\nbpy.ops.ed.undo()")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# --------------------------------------------------------------------------
# 3. Generic MCP stdio transport (JSON-RPC 2.0 over newline-delimited JSON)
# --------------------------------------------------------------------------

class MCPStdioTransport:
    name = "MCP server (stdio)"

    def __init__(self, command, timeout=300, cwd=None):
        # command may be a string (parsed with shlex) or a list.
        argv = shlex.split(command) if isinstance(command, str) else list(command)
        self.proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=cwd, bufsize=0,
        )
        self.timeout = timeout
        self._id = 0
        self._lock = threading.Lock()
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        self.tools = self._initialize()

    def _drain_stderr(self):
        try:
            for line in iter(self.proc.stderr.readline, b""):
                sys.stderr.write("[mcp] " + line.decode("utf-8", "replace"))
        except Exception:
            pass

    def _rpc(self, method, params=None, notification=False, timeout=None):
        with self._lock:
            if not notification:
                self._id += 1
                rid = self._id
            msg = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                msg["params"] = params
            if not notification:
                msg["id"] = rid
            self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
            self.proc.stdin.flush()

            if notification:
                return None

            deadline = time.time() + (timeout or self.timeout)
            while time.time() < deadline:
                line = self.proc.stdout.readline()
                if not line:
                    raise ConnectionError("MCP server exited")
                try:
                    resp = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                if "id" in resp and resp.get("id") == rid:
                    if "error" in resp:
                        raise RuntimeError("MCP error: %s" % resp["error"])
                    return resp.get("result")
                # server-initiated requests/notifications: ignore for our purposes
            raise TimeoutError("MCP call %r timed out" % method)

    def _initialize(self):
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "blender-ai-agent", "version": "2.0"},
        }, timeout=60)
        self._rpc("notifications/initialized", notification=True)
        result = self._rpc("tools/list", {})
        return {t["name"]: t for t in result.get("tools", [])}

    def call_tool(self, tool_name, arguments):
        result = self._rpc("tools/call",
                           {"name": tool_name, "arguments": arguments or {}})
        # MCP content is a list of items; concatenate text and collect images.
        texts, images = [], []
        structured = result.get("structuredContent")
        for item in result.get("content", []):
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
            elif item.get("type") == "image":
                data = item.get("data") or item.get("data_url") or ""
                if data and not data.startswith("data:"):
                    mime = item.get("mimeType", "image/png")
                    data = "data:%s;base64,%s" % (mime, data)
                images.append(data)
        if images:
            if structured is None:
                structured = {}
            structured.setdefault("images", images)
            structured.setdefault("data_url", images[0])
        return "\n".join(texts), structured, result.get("isError", False)

    def _find_tool(self, *candidates):
        for name in candidates:
            if name in self.tools:
                return name
        return None

    def ping(self):
        return {"transport": self.name, "tools": sorted(self.tools)}

    def scene_info(self):
        tool = self._find_tool("get_scene_info", "scene_info", "get_scene")
        if not tool:
            return {"note": "server has no scene-info tool"}
        text, structured, err = self.call_tool(tool, {})
        if structured:
            return structured
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}

    def exec_code(self, code):
        tool = self._find_tool("execute_code", "execute_blender_code", "run_code")
        if not tool:
            return {"stdout": "", "error": "MCP server has no code-execution tool", "extra": {}}
        text, structured, err = self.call_tool(tool, {"code": code})
        if structured:
            return {"stdout": structured.get("stdout", "") or text,
                    "error": structured.get("error") or (text if err else None),
                    "extra": structured}
        return {"stdout": text if not err else "", "error": text if err else None, "extra": {}}

    def viewport_screenshot(self, filepath):
        tool = self._find_tool("get_viewport_screenshot", "screenshot", "capture_viewport")
        if not tool:
            raise RuntimeError("MCP server has no viewport screenshot tool")
        text, structured, err = self.call_tool(tool, {"max_size": 1280})
        data_url = None
        if structured:
            data_url = structured.get("data_url") or structured.get("screenshot")
        if not data_url:
            m = re.search(r"data:image/\w+;base64,[A-Za-z0-9+/=\s]+", text or "")
            data_url = m.group(0) if m else None
        if not data_url:
            raise RuntimeError("no image data from MCP screenshot tool")
        m = re.match(r"data:image/(\w+);base64,(.*)", data_url, re.DOTALL)
        import base64
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "wb") as fh:
            fh.write(base64.b64decode(m.group(2)))
        return filepath

    def render(self, filepath=None):
        tool = self._find_tool("render_scene", "render")
        if tool:
            text, structured, err = self.call_tool(tool, {"filepath": filepath} if filepath else {})
            path = (structured or {}).get("filepath") or filepath
            if path:
                return path
        return self.viewport_screenshot(filepath)

    def save(self, filepath):
        tool = self._find_tool("save_blend", "save_file")
        if tool:
            self.call_tool(tool, {"filepath": os.path.abspath(filepath)})
            return filepath
        out = self.exec_code("import bpy\nbpy.ops.wm.save_as_mainfile(filepath=%r)"
                             % os.path.abspath(filepath))
        if out["error"]:
            raise RuntimeError(out["error"])
        return filepath

    def export(self, filepath, fmt):
        out = self.exec_code(
            "import bpy\nfmt=%r\npath=%r\n"
            "ops={'GLB':lambda:bpy.ops.export_scene.gltf(filepath=path,export_format='GLB'),"
            "'STL':lambda:bpy.ops.export_mesh.stl(filepath=path),"
            "'FBX':lambda:bpy.ops.export_scene.fbx(filepath=path),"
            "'OBJ':lambda:bpy.ops.wm.obj_export(filepath=path)}\n"
            "ops[fmt]()" % (fmt.upper(), os.path.abspath(filepath)))
        if out["error"]:
            raise RuntimeError(out["error"])
        return filepath

    def undo(self):
        tool = self._find_tool("undo")
        if tool:
            self.call_tool(tool, {})
        else:
            self.exec_code("import bpy\nbpy.ops.ed.undo()")

    def close(self):
        try:
            self._rpc("exit", notification=True)
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


# --------------------------------------------------------------------------
# Auto-detection / factory
# --------------------------------------------------------------------------

def _can_connect(host, port, timeout=1.0):
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False


def _probe_blendermcp(host, port):
    """BlenderMCP answers raw-JSON ping with {"status":"success"}."""
    try:
        t = BlenderMCPTransport(host, port, timeout=5)
        r = t._call("ping")
        if r.get("status") == "success" and "pong" in (r.get("result") or {}):
            return t
        t.close()
    except Exception:
        pass
    return None


def _probe_bridge(host, port):
    try:
        t = BridgeTransport(host, port, timeout=5)
        r = t._call("ping")
        if r.get("ok") and "blender" in (r.get("result") or {}):
            return t
        t.close()
    except Exception:
        pass
    return None


def connect(transport="auto", host="127.0.0.1", port=9876, mcp_command=None):
    """Create a transport.

    transport: "auto" | "bridge" | "blendermcp" | "mcp-stdio"
    For auto: BlenderMCP addon is probed first (that's what most users have),
    then our own bridge. mcp-stdio spawns `mcp_command` (default `uvx blender-mcp`).
    """
    if transport == "mcp-stdio":
        return MCPStdioTransport(mcp_command or "uvx blender-mcp")
    if transport == "bridge":
        return BridgeTransport(host, port)
    if transport == "blendermcp":
        return BlenderMCPTransport(host, port)

    # auto
    if not _can_connect(host, port):
        raise RuntimeError(
            "Nothing listening on %s:%d. Start the bridge in Blender "
            "(AI Agent tab > Start, or: blender --python bridge_standalone.py) "
            "or start the BlenderMCP addon server." % (host, port))
    t = _probe_blendermcp(host, port)
    if t:
        return t
    t = _probe_bridge(host, port)
    if t:
        return t
    raise RuntimeError("Something is listening on %s:%d but it is neither the "
                       "BlenderMCP addon nor the AI Agent Bridge." % (host, port))
