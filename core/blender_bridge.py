"""Small authenticated localhost client for the MARK Blender add-on.

The bridge deliberately exposes JSON actions, not Python or Blender expressions.
It binds to loopback, uses a user-supplied token, and gives the plugin a bounded
socket timeout so an unavailable Blender instance never blocks MARK's model loop.
"""
from __future__ import annotations

import json
import os
import socket


_ALLOWED_ACTIONS = {
    "status", "list_objects", "inspect_object", "create_cube", "create_sphere",
    "create_cylinder", "create_camera", "create_light", "set_transform",
    "set_material", "add_modifier", "delete_object", "render", "save_blend",
}


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
        return "Blender is not configured: set MARK_BLENDER_TOKEN in MARK's launch environment."
    if value.get("host") not in {"127.0.0.1", "localhost"}:
        return "For safety, the Blender bridge only permits a loopback host."
    return None


def call(action: str, parameters: dict | None = None,
         timeout: float = 5.0, overrides: dict | None = None) -> tuple[bool, str]:
    action = str(action or "").strip().lower().replace("-", "_")
    if action not in _ALLOWED_ACTIONS:
        return False, "Unknown Blender action."
    settings = _settings(overrides)
    error = configuration_error(settings)
    if error:
        return False, error

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
            while size < 2_000_000:
                chunk = conn.recv(min(65536, 2_000_000 - size))
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
        return False, "Could not reach Blender. Enable the MARK Bridge add-on and start its local server."
    except json.JSONDecodeError:
        return False, "Blender returned malformed bridge data."
    except OSError as exc:
        return False, f"Blender bridge connection failed: {exc}"
    except Exception as exc:
        return False, f"Blender bridge failed: {exc}"


def test_connection(overrides: dict | None = None) -> tuple[bool, str]:
    return call("status", {}, timeout=3.0, overrides=overrides)
