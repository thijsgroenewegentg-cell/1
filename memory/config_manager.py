"""Persistent local settings for MARK.

The original project stored a Gemini API key here.  This Ollama build never
needs a cloud credential: the file contains only local server/model choices,
assistant customisation and optional plugin settings.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"  # historical filename; no secrets

DEFAULT_LLM_URL      = "http://localhost:11434"
DEFAULT_LLM_MODEL   = "qwen2.5:14b"
DEFAULT_VISION_MODEL = "qwen2.5vl:7b"


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_api_keys() -> dict:
    """Load local settings. Kept named load_api_keys for action compatibility."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[Config] Failed to load api_keys.json: {e}")
        return {}


def _patch_config(**fields) -> None:
    """Read-modify-write settings without losing another feature's fields."""
    ensure_config_dir()
    data = load_api_keys()
    data.update(fields)
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def config_exists() -> bool:
    return CONFIG_FILE.exists()


def save_api_keys(value: str = "") -> None:
    """Compatibility helper: initialise a local config; value is ignored."""
    _patch_config(
        llm_url=load_api_keys().get("llm_url", DEFAULT_LLM_URL),
        llm_model=load_api_keys().get("llm_model", DEFAULT_LLM_MODEL),
        vision_model=load_api_keys().get("vision_model", DEFAULT_VISION_MODEL),
    )


def get_gemini_key() -> None:
    """Cloud credentials are intentionally unsupported in the Ollama build."""
    return None


def is_configured() -> bool:
    cfg = load_api_keys()
    return bool(cfg.get("llm_url") and cfg.get("llm_model"))


def get_assistant_name() -> str:
    return load_api_keys().get("assistant_name", "JARVIS") or "JARVIS"


def get_user_name() -> str:
    return load_api_keys().get("user_name", "") or ""


def save_assistant_config(assistant_name: str, user_name: str) -> None:
    _patch_config(
        assistant_name=assistant_name.strip() or "JARVIS",
        user_name=user_name.strip(),
    )


# ── Text-to-speech voice ─────────────────────────────────────────────────────
# These are friendly labels. core.tts maps them to Microsoft Edge neural voices.
AVAILABLE_VOICES = ["Guy", "Jenny", "Aria", "Sonia", "Ryan"]
DEFAULT_VOICE    = "Guy"


def get_voice() -> str:
    value = load_api_keys().get("voice_name", DEFAULT_VOICE) or DEFAULT_VOICE
    return value if value in AVAILABLE_VOICES else DEFAULT_VOICE


def save_voice(voice_name: str) -> None:
    value = (voice_name or "").strip()
    _patch_config(voice_name=value if value in AVAILABLE_VOICES else DEFAULT_VOICE)


def get_wake_word_enabled() -> bool:
    return bool(load_api_keys().get("wake_word_enabled", False))


def save_wake_word_enabled(enabled: bool) -> None:
    _patch_config(wake_word_enabled=bool(enabled))


def get_brief_enabled() -> bool:
    return bool(load_api_keys().get("morning_brief_enabled", True))


def save_brief_enabled(enabled: bool) -> None:
    _patch_config(morning_brief_enabled=bool(enabled))


# ── Audio devices ────────────────────────────────────────────────────────────
def get_input_device() -> str:
    return (load_api_keys().get("input_device", "") or "").strip()


def save_input_device(name: str) -> None:
    _patch_config(input_device=(name or "").strip())


def get_output_device() -> str:
    return (load_api_keys().get("output_device", "") or "").strip()


def save_output_device(name: str) -> None:
    _patch_config(output_device=(name or "").strip())


# ── Per-plugin settings ──────────────────────────────────────────────────────
def get_plugin_enabled(plugin_name: str) -> bool:
    return bool(load_api_keys().get("plugins_enabled", {}).get(plugin_name, True))


def get_plugin_config(namespace: str) -> dict:
    cfg = load_api_keys().get("plugin_config")
    value = cfg.get(namespace) if isinstance(cfg, dict) else None
    return dict(value) if isinstance(value, dict) else {}


def get_plugin_setting(namespace: str, key: str, default=None):
    return get_plugin_config(namespace).get(key, default)


def save_plugin_config(namespace: str, values: dict) -> None:
    data = load_api_keys()
    configs = data.get("plugin_config")
    if not isinstance(configs, dict):
        configs = {}
    current = configs.get(namespace)
    if not isinstance(current, dict):
        current = {}
    current.update(values)
    configs[namespace] = current
    data["plugin_config"] = configs
    ensure_config_dir()
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def save_plugin_enabled(plugin_name: str, enabled: bool) -> None:
    data = load_api_keys()
    enabled_cfg = data.get("plugins_enabled")
    if not isinstance(enabled_cfg, dict):
        enabled_cfg = {}
    enabled_cfg[plugin_name] = bool(enabled)
    data["plugins_enabled"] = enabled_cfg
    ensure_config_dir()
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_plugin_trust_required() -> bool:
    """Only load plugins approved by the local installer unless development
    mode has explicitly been enabled by the user."""
    value = load_api_keys().get("plugin_trust_required", True)
    return bool(value)


def save_plugin_trust_required(required: bool) -> None:
    _patch_config(plugin_trust_required=bool(required))
