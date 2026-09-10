"""Authenticated local MCP client for the MARK Blender add-on.

MARK talks to the add-on through the Model Context Protocol (JSON-RPC over the
loopback Streamable HTTP endpoint ``POST /mcp``). The add-on still exposes only
named, allowlisted Blender operations; MCP does not grant arbitrary Python,
bpy, shell or remote-network access. A short legacy newline-JSON fallback is
kept so an older add-on can be upgraded without breaking an existing session.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid


_ALLOWED_ACTIONS = {
    "status", "list_objects", "inspect_object", "create_cube", "create_sphere",
    "create_cylinder", "create_camera", "create_light", "create_collection",
    "duplicate_object", "set_transform", "set_active_camera", "look_at",
    "set_material", "add_modifier", "delete_object", "set_render_settings",
    "render", "save_blend", "scene_checkpoint", "undo",
}
_MCP_PROTOCOL_VERSION = "2025-06-18"
_MAX_RESPONSE = 2_000_000


def _settings(overrides: dict | None = None) -> dict:
    try:
        from memory.config_manager import get_plugin_config
        stored = get_plugin_config("blender_control")
    except Exception:
        stored = {}
    stored = {**stored, **(overrides or {})}

    host = os.environ.get("MARK_BLENDER_HOST", "").strip() or str(
        stored.get("host", "127.0.0.1")
    ).strip()
    raw_port = os.environ.get("MARK_BLENDER_PORT", str(stored.get("port", 8765)))
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        port = 8765
    port = port if 1 <= port <= 65535 else 8765
    # The token is intentionally not read from MARK's regular JSON settings.
    token = os.environ.get("MARK_BLENDER_TOKEN", "").strip()
    return {"host": host or "127.0.0.1", "port": port, "token": token}


def configuration_error(settings: dict | None = None) -> str | None:
    value = settings or _settings()
    if not value.get("token"):
        return ("Blender is not configured: MARK_BLENDER_TOKEN is missing from this MARK process. "
                "Set the same token in Blender's MARK Bridge preferences and in MARK's launch environment, then restart MARK. "
                "The token is never stored in config files.")
    if value.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        return "For safety, the Blender bridge only permits a loopback host."
    return None


def _base_url(settings: dict) -> str:
    host = str(settings["host"]).strip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{settings['port']}"


def _post_mcp(settings: dict, message: dict, timeout: float) -> tuple[bool, object, bool]:
    """Return (success, decoded response/error, may_try_legacy)."""
    endpoint = _base_url(settings) + "/mcp"
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings['token']}",
            "MCP-Protocol-Version": _MCP_PROTOCOL_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(_MAX_RESPONSE + 1)
        if len(raw) > _MAX_RESPONSE:
            return False, "Blender MCP returned an oversized response.", False
        if not raw:
            return True, {}, False
        text = raw.decode("utf-8", errors="replace").strip()
        # Streamable HTTP servers may choose an SSE response even when the
        # request was a single JSON-RPC message. Accept its final data event.
        if text.startswith("data:"):
            text = next((line[5:].strip() for line in reversed(text.splitlines())
                         if line.startswith("data:")), "")
        return True, json.loads(text), False
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(2000).decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        # An old MARK add-on has no /mcp endpoint. Only that case may use the
        # legacy transport; authentication and protocol errors must not hide.
        return False, f"Blender MCP returned HTTP {exc.code}: {detail[:400]}", exc.code in {404, 405}
    except (urllib.error.URLError, ConnectionRefusedError, TimeoutError, socket.timeout) as exc:
        reason = getattr(exc, "reason", exc)
        return False, f"Could not reach Blender MCP: {reason}", True
    except http.client.HTTPException as exc:
        return False, f"Blender did not return an MCP HTTP response: {exc}", True
    except json.JSONDecodeError:
        return False, "Blender MCP returned malformed JSON.", True
    except OSError as exc:
        return False, f"Blender MCP connection failed: {exc}", True
    except Exception as exc:
        return False, f"Blender MCP failed: {exc}", False


def _jsonrpc_error(response: object) -> str | None:
    if not isinstance(response, dict):
        return "Blender MCP returned an invalid JSON-RPC response."
    error = response.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or "Blender MCP rejected the request.")
    return None


def _mcp_text(response: object) -> tuple[bool, str]:
    error = _jsonrpc_error(response)
    if error:
        return False, error
    if not isinstance(response, dict):
        return False, "Blender MCP returned an invalid response."
    result = response.get("result")
    if not isinstance(result, dict):
        return False, "Blender MCP returned no tool result."
    content = result.get("content")
    text = ""
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text += str(item.get("text", ""))
    if bool(result.get("isError")):
        return False, text or "Blender MCP reported a tool error."
    if text:
        return True, text
    structured = result.get("structuredContent")
    if structured is not None:
        return True, json.dumps(structured, ensure_ascii=False)
    return True, "Blender action completed."


def _mcp_call(settings: dict, action: str, parameters: dict,
              timeout: float) -> tuple[bool, str, bool]:
    """Call the Blender MCP server and return (ok, text, legacy_fallback)."""
    initialize = {
        "jsonrpc": "2.0",
        "id": f"mark-init-{uuid.uuid4().hex}",
        "method": "initialize",
        "params": {
            "protocolVersion": _MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "MARK", "version": "2.0.0"},
        },
    }
    ok, response, fallback = _post_mcp(settings, initialize, timeout)
    if not ok:
        return False, str(response), fallback
    error = _jsonrpc_error(response)
    if error:
        return False, error, False

    # Complete the MCP handshake. A notification has no response body, so a
    # server may return 202; failure here is not fatal for stateless servers.
    initialized = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    }
    _post_mcp(settings, initialized, timeout)

    call = {
        "jsonrpc": "2.0",
        "id": f"mark-call-{uuid.uuid4().hex}",
        "method": "tools/call",
        "params": {
            "name": "blender_control",
            "arguments": {"action": action, "parameters": dict(parameters or {})},
        },
    }
    ok, response, fallback = _post_mcp(settings, call, timeout)
    if not ok:
        return False, str(response), fallback
    ok, text = _mcp_text(response)
    return ok, text, False


def _legacy_call(settings: dict, action: str, parameters: dict,
                 timeout: float) -> tuple[bool, str]:
    request = {
        "token": settings["token"],
        "action": action,
        "parameters": dict(parameters or {}),
    }
    try:
        with socket.create_connection((settings["host"], settings["port"]), timeout=timeout) as conn:
            conn.settimeout(timeout)
            conn.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
            chunks: list[bytes] = []
            size = 0
            while size < _MAX_RESPONSE:
                chunk = conn.recv(min(65536, _MAX_RESPONSE - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if b"\n" in chunk:
                    break
        raw = b"".join(chunks).split(b"\n", 1)[0]
        response = json.loads(raw.decode("utf-8"))
        if not isinstance(response, dict):
            return False, "Blender returned an invalid bridge response."
        if not response.get("ok"):
            return False, str(response.get("error") or "Blender rejected the action.")
        return True, str(response.get("result") or "Blender action completed.")
    except (ConnectionRefusedError, TimeoutError, socket.timeout):
        return False, (f"Could not reach Blender at {settings['host']}:{settings['port']}. "
                       "Enable the MARK Bridge add-on, set its token, click Start MARK Bridge, "
                       "and confirm that MARK uses the same loopback port.")
    except json.JSONDecodeError:
        return False, "Blender returned malformed bridge data."
    except OSError as exc:
        return False, f"Blender bridge connection failed: {exc}"
    except Exception as exc:
        return False, f"Blender bridge failed: {exc}"


def call(action: str, parameters: dict | None = None,
         timeout: float = 5.0, overrides: dict | None = None) -> tuple[bool, str]:
    action = str(action or "").strip().lower().replace("-", "_")
    if action not in _ALLOWED_ACTIONS:
        return False, "Unknown Blender action."
    settings = _settings(overrides)
    error = configuration_error(settings)
    if error:
        return False, error

    ok, result, fallback = _mcp_call(settings, action, dict(parameters or {}), timeout)
    if ok:
        return True, result
    if fallback:
        legacy_ok, legacy_result = _legacy_call(settings, action, dict(parameters or {}), timeout)
        if legacy_ok:
            return legacy_ok, legacy_result
    return False, result


def test_connection(overrides: dict | None = None) -> tuple[bool, str]:
    ok, message = call("status", {}, timeout=3.0, overrides=overrides)
    return ok, (f"MCP connection succeeded. {message}" if ok else message)
