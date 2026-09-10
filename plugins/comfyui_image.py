"""Local ComfyUI image-generation plugin.

The default workflow uses only ComfyUI's standard checkpoint, text-encode,
KSampler, latent, VAE and SaveImage nodes. MARK talks to a loopback ComfyUI
server only; it never accepts a remote URL, arbitrary shell command, or a
workflow supplied by the model. A user may explicitly select a local API-format
workflow in plugin settings for advanced models. Generated files are copied to
a user-home output folder and image generation/downloads require confirmation.

Non-secret settings can be saved in MARK's plugin settings. There are no API
credentials for a local ComfyUI server.
"""
from __future__ import annotations

import copy
import json
import os
import random
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from pathlib import Path

from core import confirm as confirm_gate


PLUGIN = {
    "name": "comfyui_image",
    "description": (
        "Generate images through a local ComfyUI server. Use this for requests "
        "such as create an image, concept art, a texture or a variation. It can "
        "check ComfyUI status and queue, submit a bounded prompt with size/steps, "
        "show history, download completed images to the configured MARK folder, "
        "open a saved result, or interrupt a queued job. Image generation and "
        "downloads require on-screen confirmation. The server must be loopback-only."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "status | queue | generate | history | download | open | interrupt",
            },
            "prompt": {
                "type": "STRING",
                "description": "Positive image prompt for generate",
            },
            "negative_prompt": {
                "type": "STRING",
                "description": "Optional negative prompt for generate",
            },
            "width": {
                "type": "INTEGER",
                "description": "Image width, bounded to 64-2048 and rounded to a multiple of 8",
            },
            "height": {
                "type": "INTEGER",
                "description": "Image height, bounded to 64-2048 and rounded to a multiple of 8",
            },
            "steps": {
                "type": "INTEGER",
                "description": "Sampling steps, bounded to 1-80",
            },
            "cfg": {
                "type": "NUMBER",
                "description": "Classifier-free guidance, bounded to 0-30",
            },
            "seed": {
                "type": "INTEGER",
                "description": "Optional seed; omit for a random seed",
            },
            "prompt_id": {
                "type": "STRING",
                "description": "ComfyUI prompt id returned by generate",
            },
            "wait": {
                "type": "BOOLEAN",
                "description": "Wait for generation and download the result; defaults to true",
            },
            "timeout": {
                "type": "INTEGER",
                "description": "Maximum wait in seconds, bounded to 1-300",
            },
        },
        "required": ["action"],
    },
}


_DEFAULT_OUTPUT = Path.home() / "Documents" / "MARK" / "comfyui"
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MAX_RESPONSE = 12 * 1024 * 1024
_MAX_IMAGE = 40 * 1024 * 1024
# Only standard, bounded image-generation nodes may be used from a custom API
# workflow. In particular, arbitrary/custom Python nodes are not a plugin escape
# hatch for MARK's computer-access policy.
_ALLOWED_WORKFLOW_NODES = {
    "CheckpointLoaderSimple", "CheckpointLoader", "UNETLoader", "CLIPLoader", "VAELoader",
    "LoraLoader", "LoraLoaderModelOnly", "ControlNetApply", "ControlNetApplyAdvanced",
    "CLIPTextEncode", "CLIPTextEncodeFlux", "CLIPTextEncodeSDXL", "CLIPTextEncodeSD3",
    "CLIPSetLastLayer", "KSampler", "KSamplerAdvanced", "SamplerCustom", "BasicScheduler",
    "RandomNoise", "CFGGuider", "EmptyLatentImage", "EmptySD3LatentImage",
    "VAEDecode", "VAEDecodeTiled", "VAEEncode", "SaveImage", "PreviewImage",
}
_MAX_WORKFLOW_NODES = 80


def _stored_settings() -> dict:
    try:
        from memory.config_manager import get_plugin_config
        value = get_plugin_config("comfyui_image")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _port(value, default: int = 8188) -> int:
    try:
        number = int(value)
        return number if 1 <= number <= 65535 else default
    except (TypeError, ValueError):
        return default


def _settings(overrides: dict | None = None) -> dict:
    stored = {**_stored_settings(), **(overrides or {})}
    host = os.environ.get("MARK_COMFYUI_HOST", "").strip() or str(
        stored.get("host", "127.0.0.1")
    ).strip()
    raw_port = os.environ.get("MARK_COMFYUI_PORT", "")
    port = _port(raw_port or stored.get("port", 8188))
    checkpoint = os.environ.get("MARK_COMFYUI_CHECKPOINT", "").strip() or str(
        stored.get("checkpoint", "")
    ).strip()
    workflow_path = os.environ.get("MARK_COMFYUI_WORKFLOW", "").strip() or str(
        stored.get("workflow_path", "")
    ).strip()
    raw_output = os.environ.get("MARK_COMFYUI_OUTPUT_DIR", "").strip() or str(
        stored.get("output_dir", str(_DEFAULT_OUTPUT))
    ).strip()
    positive_node = str(stored.get("positive_node", "6") or "6").strip()
    negative_node = str(stored.get("negative_node", "7") or "7").strip()
    return {
        "host": host or "127.0.0.1",
        "port": port,
        "checkpoint": checkpoint,
        "workflow_path": workflow_path,
        "output_dir": raw_output or str(_DEFAULT_OUTPUT),
        "positive_node": positive_node,
        "negative_node": negative_node,
    }


def _under_home(raw: str, label: str, default: Path | None = None) -> tuple[Path | None, str | None]:
    value = str(raw or "").strip()
    path = Path(value).expanduser() if value else (default or Path.home())
    try:
        path = path.resolve()
        path.relative_to(Path.home().resolve())
    except (OSError, ValueError):
        return None, f"The ComfyUI {label} must stay inside the user home folder."
    return path, None


def _configuration_error(settings: dict, require_model: bool = False) -> str | None:
    host = str(settings.get("host", "")).strip().lower().strip("[]")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return "For safety, ComfyUI must use a loopback host: 127.0.0.1, localhost or ::1."
    workflow_path = None
    if str(settings.get("workflow_path", "")).strip():
        workflow_path, error = _under_home(settings.get("workflow_path", ""), "workflow path")
        if error:
            return error
        if workflow_path and workflow_path.exists() and not workflow_path.is_file():
            return f"The configured ComfyUI workflow is not a file: {workflow_path}"
    output_dir, error = _under_home(settings.get("output_dir", ""), "output directory", _DEFAULT_OUTPUT)
    if error:
        return error
    if output_dir is None:
        return "The ComfyUI output directory is invalid."
    if require_model and not workflow_path and not str(settings.get("checkpoint", "")).strip():
        return (
            "ComfyUI needs a checkpoint name in Plugin Settings, for example "
            "sd_xl_base_1.0.safetensors, or an API-format workflow file."
        )
    checkpoint = str(settings.get("checkpoint", "")).strip().replace("\\", "/")
    if checkpoint.startswith("/") or any(part == ".." for part in checkpoint.split("/")):
        return "The ComfyUI checkpoint must be a model name, not a path outside ComfyUI's model folder."
    if checkpoint and Path(checkpoint).suffix.lower() not in {".safetensors", ".ckpt", ".pt", ".pth"}:
        return "The ComfyUI checkpoint must be a .safetensors, .ckpt, .pt or .pth model name."
    return None


def _base_url(settings: dict) -> str:
    host = str(settings["host"]).strip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{settings['port']}"


def _request(settings: dict, method: str, path: str, payload=None,
             timeout: float = 10.0) -> tuple[bool, object]:
    error = _configuration_error(settings)
    if error:
        return False, error
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        _base_url(settings) + path,
        data=body,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(_MAX_RESPONSE + 1)
        if len(raw) > _MAX_RESPONSE:
            return False, "ComfyUI returned an oversized response."
        if not raw:
            return True, {}
        return True, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(4000).decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        return False, f"ComfyUI returned HTTP {exc.code}: {detail[:500]}"
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return False, (
            f"Could not reach ComfyUI at {settings['host']}:{settings['port']}: {reason}. "
            "Start ComfyUI with its local server enabled."
        )
    except TimeoutError:
        return False, "ComfyUI did not respond before the connection timed out."
    except json.JSONDecodeError:
        return False, "ComfyUI returned malformed JSON."
    except Exception as exc:
        return False, f"ComfyUI request failed: {exc}"


def _request_bytes(settings: dict, path: str, timeout: float = 20.0) -> tuple[bool, bytes | str]:
    error = _configuration_error(settings)
    if error:
        return False, error
    request = urllib.request.Request(_base_url(settings) + path, headers={"Accept": "image/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(_MAX_IMAGE + 1)
        if len(raw) > _MAX_IMAGE:
            return False, "ComfyUI returned an oversized image."
        return True, raw
    except urllib.error.HTTPError as exc:
        return False, f"ComfyUI image request returned HTTP {exc.code}."
    except urllib.error.URLError as exc:
        return False, f"Could not download the ComfyUI image: {getattr(exc, 'reason', exc)}"
    except Exception as exc:
        return False, f"ComfyUI image download failed: {exc}"


def _test_connection(values: dict) -> tuple[bool, str]:
    settings = _settings(values)
    ok, result = _request(settings, "GET", "/system_stats", timeout=3.0)
    if not ok:
        return False, str(result)
    return True, f"ComfyUI is responding at {settings['host']}:{settings['port']}."


PLUGIN_SETTINGS = {
    "namespace": "comfyui_image",
    "title": "COMFYUI — LOCAL IMAGE GENERATION",
    "note": (
        "ComfyUI is contacted only over loopback. Host, port, model and paths are "
        "local settings; no cloud credential is used. Leave workflow blank for the "
        "built-in standard-node workflow."
    ),
    "fields": [
        {"key": "host", "label": "ComfyUI host", "default": "127.0.0.1"},
        {"key": "port", "label": "ComfyUI port", "default": 8188},
        {"key": "checkpoint", "label": "Checkpoint name", "placeholder": "sd_xl_base_1.0.safetensors"},
        {"key": "workflow_path", "label": "Optional API workflow", "placeholder": "~/ComfyUI/user/default/workflows/mark_api.json"},
        {"key": "output_dir", "label": "MARK output folder", "default": str(_DEFAULT_OUTPUT)},
        {"key": "positive_node", "label": "Custom positive node", "default": "6"},
        {"key": "negative_node", "label": "Custom negative node", "default": "7"},
    ],
    "action": {"label": "TEST COMFYUI CONNECTION", "run": _test_connection},
}


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _dimensions(params: dict) -> tuple[int, int]:
    width = _bounded_int(params.get("width", 1024), 1024, 64, 2048)
    height = _bounded_int(params.get("height", 1024), 1024, 64, 2048)
    return max(64, (width // 8) * 8), max(64, (height // 8) * 8)


def _seed(value) -> int:
    if value is None or str(value).strip() == "":
        return random.randint(0, 2**63 - 1)
    try:
        return max(0, min(2**63 - 1, int(value)))
    except (TypeError, ValueError):
        return random.randint(0, 2**63 - 1)


def _default_workflow(settings: dict, params: dict) -> dict:
    width, height = _dimensions(params)
    steps = _bounded_int(params.get("steps", 24), 24, 1, 80)
    try:
        cfg = max(0.0, min(30.0, float(params.get("cfg", 7.0))))
    except (TypeError, ValueError):
        cfg = 7.0
    positive = str(params.get("prompt", "")).strip()[:6000]
    negative = str(params.get("negative_prompt", "")).strip()[:3000]
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": _seed(params.get("seed")),
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": settings["checkpoint"]},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["4", 1]},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "MARK", "images": ["8", 0]},
        },
    }


def _load_workflow(settings: dict, params: dict) -> tuple[dict | None, str | None]:
    configured = str(settings.get("workflow_path", "")).strip()
    if not configured:
        return _default_workflow(settings, params), None
    path, error = _under_home(configured, "workflow path")
    if error:
        return None, error
    if path is None or not path.is_file():
        return None, f"The configured ComfyUI workflow file does not exist: {path}"
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            return None, "The ComfyUI workflow file is too large."
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"Could not read the ComfyUI workflow: {exc}"
    if isinstance(data, dict) and isinstance(data.get("prompt"), dict):
        data = data["prompt"]
    if not isinstance(data, dict) or not data:
        return None, "The workflow must be a non-empty ComfyUI API-format JSON object."
    if len(data) > _MAX_WORKFLOW_NODES:
        return None, f"The workflow is limited to {_MAX_WORKFLOW_NODES} nodes."
    unsupported = sorted({
        str(node.get("class_type", ""))
        for node in data.values()
        if not isinstance(node, dict) or str(node.get("class_type", "")) not in _ALLOWED_WORKFLOW_NODES
    })
    if unsupported:
        names = ", ".join(name or "(missing class_type)" for name in unsupported[:8])
        return None, f"The workflow contains unsupported or unsafe node types: {names}."
    return copy.deepcopy(data), None


def _node_title(node: dict) -> str:
    meta = node.get("_meta") if isinstance(node, dict) else {}
    return str((meta or {}).get("title", "")).lower()


def _apply_workflow_inputs(workflow: dict, settings: dict, params: dict) -> str | None:
    positive = str(params.get("prompt", "")).strip()[:6000]
    negative = str(params.get("negative_prompt", "")).strip()[:3000]
    if not positive:
        return "Tell me what image to generate."
    clip_nodes = []
    sampler_nodes = []
    latent_nodes = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        class_type = str(node.get("class_type", ""))
        if class_type == "CLIPTextEncode":
            clip_nodes.append((str(node_id), node))
        elif class_type == "KSampler":
            sampler_nodes.append(node)
        elif class_type == "EmptyLatentImage":
            latent_nodes.append(node)
        elif class_type == "CheckpointLoaderSimple" and settings.get("checkpoint"):
            node["inputs"]["ckpt_name"] = settings["checkpoint"]
        elif class_type == "SaveImage":
            # Keep custom workflows from choosing an output path or prefix.
            node["inputs"]["filename_prefix"] = "MARK"

    if not clip_nodes:
        return "The selected workflow has no CLIPTextEncode nodes for MARK's prompt."
    positive_id = str(settings.get("positive_node", "6"))
    negative_id = str(settings.get("negative_node", "7"))
    by_id = {node_id: node for node_id, node in clip_nodes}
    if positive_id not in by_id or negative_id not in by_id or positive_id == negative_id:
        titled_positive = next((item for item in clip_nodes if "positive" in _node_title(item[1])), None)
        titled_negative = next((item for item in clip_nodes if "negative" in _node_title(item[1])), None)
        if titled_positive and titled_negative:
            positive_id, negative_id = titled_positive[0], titled_negative[0]
        elif len(clip_nodes) >= 2:
            positive_id, negative_id = clip_nodes[0][0], clip_nodes[1][0]
        else:
            return "The selected workflow needs separate positive and negative CLIP text nodes."
    by_id[positive_id]["inputs"]["text"] = positive
    by_id[negative_id]["inputs"]["text"] = negative

    if latent_nodes:
        width, height = _dimensions(params)
        latent_nodes[0]["inputs"].update(width=width, height=height, batch_size=1)
    if sampler_nodes:
        sampler = sampler_nodes[0]["inputs"]
        sampler.update(
            seed=_seed(params.get("seed")),
            steps=_bounded_int(params.get("steps", 24), 24, 1, 80),
        )
        try:
            sampler["cfg"] = max(0.0, min(30.0, float(params.get("cfg", 7.0))))
        except (TypeError, ValueError):
            sampler["cfg"] = 7.0
    return None


def _submit(settings: dict, workflow: dict) -> tuple[str | None, str | None]:
    payload = {"prompt": workflow, "client_id": str(uuid.uuid4())}
    ok, result = _request(settings, "POST", "/prompt", payload, timeout=15.0)
    if not ok:
        return None, str(result)
    if not isinstance(result, dict) or not result.get("prompt_id"):
        return None, f"ComfyUI did not return a prompt id: {result}"
    node_errors = result.get("node_errors")
    if node_errors:
        return None, f"ComfyUI rejected the workflow: {str(node_errors)[:1000]}"
    return str(result["prompt_id"]), None


def _history(settings: dict, prompt_id: str = "") -> tuple[bool, object]:
    suffix = "/history/" + urllib.parse.quote(prompt_id, safe="") if prompt_id else "/history"
    return _request(settings, "GET", suffix, timeout=10.0)


def _history_entry(data, prompt_id: str) -> dict | None:
    if not isinstance(data, dict):
        return None
    value = data.get(prompt_id)
    return value if isinstance(value, dict) else None


def _wait_for_history(settings: dict, prompt_id: str, timeout: int) -> tuple[dict | None, str | None]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ok, data = _history(settings, prompt_id)
        if not ok:
            return None, str(data)
        entry = _history_entry(data, prompt_id)
        if entry and isinstance(entry.get("outputs"), dict):
            return entry, None
        time.sleep(1.0)
    return None, f"Image generation is still running. Prompt id: {prompt_id}"


def _image_records(entry: dict) -> list[dict]:
    rows: list[dict] = []
    outputs = entry.get("outputs") if isinstance(entry, dict) else None
    if not isinstance(outputs, dict):
        return rows
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        images = node_output.get("images")
        if not isinstance(images, list):
            continue
        for item in images:
            if isinstance(item, dict) and item.get("filename"):
                rows.append(item)
    return rows[:8]


def _download_images(settings: dict, prompt_id: str, entry: dict) -> tuple[list[Path], str | None]:
    output_dir, error = _under_home(settings.get("output_dir", ""), "output directory", _DEFAULT_OUTPUT)
    if error or output_dir is None:
        return [], error or "Invalid output directory."
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for index, item in enumerate(_image_records(entry)):
        filename = Path(str(item.get("filename", ""))).name
        suffix = Path(filename).suffix.lower()
        if not filename or suffix not in _IMAGE_SUFFIXES:
            continue
        query = urllib.parse.urlencode({
            "filename": filename,
            "subfolder": str(item.get("subfolder", "")),
            "type": str(item.get("type", "output")),
        })
        ok, raw = _request_bytes(settings, "/view?" + query)
        if not ok:
            return saved, str(raw)
        destination = output_dir / f"{prompt_id[:16]}-{index + 1}-{filename}"
        fd, temporary = tempfile.mkstemp(prefix="mark-comfy-", suffix=suffix, dir=str(output_dir))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
            os.replace(temporary, destination)
        finally:
            try:
                Path(temporary).unlink(missing_ok=True)
            except Exception:
                pass
        saved.append(destination)
    if not saved:
        return [], "ComfyUI completed the job but returned no supported image output."
    return saved, None


def _format_saved(paths: list[Path]) -> str:
    return "\n".join(f"{index}. {path}" for index, path in enumerate(paths, 1))


def _generate(params: dict, settings: dict, player=None) -> str:
    configuration = _configuration_error(settings, require_model=True)
    if configuration:
        return configuration
    workflow, error = _load_workflow(settings, params)
    if error or workflow is None:
        return error or "Could not load the ComfyUI workflow."
    error = _apply_workflow_inputs(workflow, settings, params)
    if error:
        return error
    prompt_id, error = _submit(settings, workflow)
    if error or not prompt_id:
        return error or "ComfyUI did not accept the image job."

    wait = bool(params.get("wait", True))
    if not wait:
        return f"ComfyUI image job queued. Prompt id: {prompt_id}"
    timeout = _bounded_int(params.get("timeout", 180), 180, 1, 300)
    entry, error = _wait_for_history(settings, prompt_id, timeout)
    if error or entry is None:
        return str(error or f"ComfyUI job queued. Prompt id: {prompt_id}")
    paths, error = _download_images(settings, prompt_id, entry)
    if error:
        return f"ComfyUI finished prompt {prompt_id}, but the image could not be downloaded: {error}"
    result = f"ComfyUI generated image(s) for prompt {prompt_id}:\n{_format_saved(paths)}"
    if player:
        try:
            player.show_content("COMFYUI — GENERATED IMAGE", result)
        except Exception:
            pass
    return result


def _history_text(settings: dict, prompt_id: str = "") -> str:
    ok, data = _history(settings, prompt_id)
    if not ok:
        return str(data)
    if prompt_id:
        entry = _history_entry(data, prompt_id)
        if not entry:
            return f"No ComfyUI history entry was found for {prompt_id}."
        images = _image_records(entry)
        return f"Prompt {prompt_id}: {len(images)} image output(s) available."
    if not isinstance(data, dict) or not data:
        return "ComfyUI history is empty."
    rows = []
    for item_id, entry in list(data.items())[-10:]:
        rows.append(f"{item_id}: {len(_image_records(entry if isinstance(entry, dict) else {}))} image output(s)")
    return "Recent ComfyUI jobs:\n" + "\n".join(rows)


def _download_for_prompt(settings: dict, prompt_id: str, player=None, open_after: bool = False) -> str:
    if not prompt_id:
        return "Provide the ComfyUI prompt_id returned by generate."
    ok, data = _history(settings, prompt_id)
    if not ok:
        return str(data)
    entry = _history_entry(data, prompt_id)
    if not entry:
        return f"No completed ComfyUI history entry was found for {prompt_id}."
    paths, error = _download_images(settings, prompt_id, entry)
    if error:
        return error
    if open_after:
        try:
            webbrowser.open(paths[0].as_uri())
        except Exception:
            pass
    result = _format_saved(paths)
    if player:
        try:
            player.show_content("COMFYUI — IMAGE OUTPUT", result)
        except Exception:
            pass
    return result


def _queue_text(settings: dict) -> str:
    ok, data = _request(settings, "GET", "/queue", timeout=5.0)
    if not ok:
        return str(data)
    if not isinstance(data, dict):
        return "ComfyUI returned an invalid queue."
    running = data.get("queue_running") or []
    pending = data.get("queue_pending") or []
    return f"ComfyUI queue: {len(running)} running, {len(pending)} pending."


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = dict(parameters or {})
    action = str(params.get("action", "status")).strip().lower().replace("-", "_")
    approved = bool(params.pop("_approved", False))
    settings = _settings()

    if action == "status":
        ok, data = _request(settings, "GET", "/system_stats", timeout=5.0)
        result = str(data) if not ok else f"ComfyUI is online at {settings['host']}:{settings['port']}."
    elif action == "queue":
        result = _queue_text(settings)
    elif action == "history":
        result = _history_text(settings, str(params.get("prompt_id", "")).strip())
    elif action == "interrupt":
        ok, data = _request(settings, "POST", "/interrupt", {}, timeout=5.0)
        result = "ComfyUI generation interrupt requested." if ok else str(data)
    elif action in {"generate", "download", "open"}:
        if not approved:
            if confirm_gate.pending_title():
                return "There is already a confirmation waiting on screen. Answer it before another ComfyUI file operation."
            if action == "generate":
                prompt = str(params.get("prompt", "")).strip()
                if not prompt:
                    return "Tell me what image to generate."
                configuration = _configuration_error(settings, require_model=True)
                if configuration:
                    return configuration
                detail = (
                    f"Generate a local ComfyUI image using the prompt '{prompt[:180]}'? "
                    "This will use GPU time and save an image under the configured MARK output folder."
                )
            else:
                detail = f"Allow MARK to {action} the completed ComfyUI image for prompt {params.get('prompt_id', '')}?"
            return confirm_gate.request(
                "comfyui_image_operation",
                f"ComfyUI: {action}",
                detail,
                lambda: run({**params, "_approved": True}, player=player, session_memory=session_memory),
            )
        if action == "generate":
            result = _generate(params, settings, player=player)
        else:
            result = _download_for_prompt(
                settings,
                str(params.get("prompt_id", "")).strip(),
                player=player,
                open_after=action == "open",
            )
    else:
        return "Unknown ComfyUI action. Use status, queue, generate, history, download, open or interrupt."

    if player:
        try:
            player.write_log(f"[ComfyUI] {action}: {str(result)[:180]}")
        except Exception:
            pass
    return str(result)
