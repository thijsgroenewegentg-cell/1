# /core/config.py
"""YAML configuration with sane defaults, dot-path access and hot reload."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import yaml
except Exception:  # pragma: no cover - yaml is a hard requirement in practice
    yaml = None  # type: ignore[assignment]


DEFAULT_CONFIG: Dict[str, Any] = {
    "user": {"name": "Sir", "title": "sir", "location": "auto", "units": "metric"},
    "assistant": {
        "name": "JARVIS",
        "personality": "witty",
        "sarcasm": 0.35,
        "greet_on_start": True,
        "proactive": True,
    },
    "llm": {
        "provider": "ollama",
        "host": "http://localhost:11434",
        "model": "llama3.2",
        "fallback_models": ["mistral", "llama3", "llama3.1", "phi3", "qwen2.5"],
        "temperature": 0.7,
        "top_p": 0.9,
        "num_ctx": 4096,
        "max_tokens": 700,
        "timeout": 180,
        "keep_alive": "10m",
        "router_model": "",
        "stream": True,
    },
    "memory": {
        "enabled": True,
        "short_term_limit": 20,
        "long_term": True,
        "path": "data/chroma",
        "collection": "jarvis_memory",
        "embedding_model": "nomic-embed-text",
        "top_k": 4,
        "min_relevance": 0.20,
        "autosave": True,
        "auto_extract_facts": True,
        "summarize": True,
        "summary_trigger": 12,
        "context_char_budget": 9000,
    },
    "database": {"path": "data/jarvis.db"},
    "voice": {
        "enabled": True,
        "wake_word": "jarvis",
        "engine": "auto",
        "porcupine_access_key": "",
        "porcupine_keyword": "jarvis",
        "sensitivity": 0.6,
        "interrupt": True,
        "chime": True,
        "stream_speech": True,
        "conversation_mode": True,
        "conversation_timeout": 20,
        "openwakeword": {"model": "hey_jarvis", "threshold": 0.5, "inference_framework": "onnx"},
        "stt": {
            "model": "base.en",
            "device": "auto",
            "compute_type": "auto",
            "language": "en",
            "beam_size": 1,
            "vad_filter": True,
        },
        "tts": {
            "voice": "en-GB-RyanNeural",
            "rate": "+8%",
            "volume": "+0%",
            "pitch": "+0Hz",
            "cache": True,
        },
        "vad": {
            "sample_rate": 16000,
            "frame_ms": 30,
            "energy_threshold": 0.014,
            "silence_ms": 900,
            "min_speech_ms": 250,
            "max_command_seconds": 15,
            "listen_timeout": 8,
        },
    },
    "modules": {
        "system_control": True,
        "web_search": True,
        "productivity": True,
        "code_assistant": True,
        "file_manager": True,
        "smart_assistant": True,
        "knowledge": True,
        "vision": True,
        "communications": True,
    },
    "knowledge": {
        "paths": ["~/Documents"],
        "store_path": "data/knowledge",
        "collection": "jarvis_documents",
        "chunk_size": 1200,
        "chunk_overlap": 150,
        "max_file_mb": 25,
        "max_files": 5000,
        "top_k": 5,
        "min_relevance": 0.05,
        "auto_index_on_start": False,
    },
    "vision": {
        "model": "llava",
        "fallback_models": ["llava:7b", "bakllava", "moondream", "llama3.2-vision"],
        "max_tokens": 400,
        "temperature": 0.2,
    },
    "email": {
        "enabled": False,
        "imap_host": "",
        "imap_port": 993,
        "smtp_host": "",
        "smtp_port": 587,
        "user": "",
        "password_env": "JARVIS_EMAIL_PASSWORD",
        "mailbox": "INBOX",
        "fetch_limit": 10,
        "allow_send": False,
    },
    "calendar": {
        "enabled": True,
        "files": [],
        "urls": [],
        "local_file": "data/jarvis.ics",
        "look_ahead_days": 7,
    },
    "web_ui": {
        "enabled": False,
        "host": "0.0.0.0",
        "port": 8765,
        "token": "",
        "allow_tts": True,
        "title": "JARVIS",
    },
    "security": {
        "confirm_dangerous": True,
        "allow_shell": True,
        "shell_timeout": 60,
        "sandbox_timeout": 20,
        "blocked_patterns": [],
        "allowed_roots": [],
    },
    "web": {
        "max_results": 5,
        "timeout": 20,
        "scrape_chars": 6000,
        "user_agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "news_feeds": [
            "http://feeds.bbci.co.uk/news/world/rss.xml",
            "https://feeds.arstechnica.com/arstechnica/index",
            "https://hnrss.org/frontpage",
        ],
        "cache_ttl": 900,
        "cache_path": "data/cache.db",
    },
    "paths": {
        "data": "data",
        "logs": "logs",
        "notes": "data/notes",
        "code": "data/code",
        "screenshots": "data/screenshots",
        "downloads": "data/downloads",
        "tts_cache": "data/tts",
        "knowledge": "data/knowledge",
    },
    "logging": {
        "level": "INFO",
        "file": "logs/jarvis.log",
        "max_bytes": 2_000_000,
        "backups": 3,
        "color": True,
        "quiet_libraries": True,
    },
}

# Environment overrides: JARVIS_<SECTION>_<KEY> (double underscore for nesting)
_ENV_PREFIX = "JARVIS_"


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``."""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _coerce(value: str) -> Any:
    """Convert an environment string into bool/int/float when possible."""
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none", ""}:
        return None
    try:
        return int(lowered)
    except ValueError:
        pass
    try:
        return float(lowered)
    except ValueError:
        pass
    return value


class Config:
    """Loads, validates and exposes JARVIS settings.

    Access values with dot paths::

        cfg = Config.load("config.yaml")
        cfg.get("llm.model")            # -> "llama3.2"
        cfg.set("voice.enabled", False)
        cfg.save()
    """

    def __init__(
        self, data: Optional[Dict[str, Any]] = None, path: Optional[str | Path] = None
    ) -> None:
        """Create a config object from an already-parsed mapping.

        Args:
            data: Raw settings (merged over the built-in defaults).
            path: Where the config lives on disk, used by :meth:`save`.
        """
        self.path: Optional[Path] = Path(path).expanduser() if path else None
        self.root: Path = self.path.parent.resolve() if self.path else Path.cwd()
        self._data: Dict[str, Any] = _deep_merge(DEFAULT_CONFIG, data or {})
        self._apply_env_overrides()

    # -- construction -------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path = "config.yaml") -> "Config":
        """Load a YAML config, creating it with defaults if it does not exist.

        Args:
            path: Path to ``config.yaml``.

        Returns:
            A ready-to-use :class:`Config`.
        """
        config_path = Path(path).expanduser()
        data: Dict[str, Any] = {}
        if config_path.exists() and yaml is not None:
            try:
                loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = {}
        config = cls(data, path=config_path)
        if not config_path.exists():
            config.save()
        config.ensure_directories()
        return config

    def reload(self) -> "Config":
        """Re-read the YAML file from disk, keeping the same object identity."""
        if self.path and self.path.exists() and yaml is not None:
            try:
                loaded = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
                self._data = _deep_merge(DEFAULT_CONFIG, loaded)
                self._apply_env_overrides()
            except Exception:
                pass
        return self

    def save(self) -> bool:
        """Write the current settings back to ``self.path``.

        Returns:
            True on success.
        """
        if not self.path or yaml is None:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                yaml.safe_dump(self._data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            return True
        except Exception:
            return False

    # -- access -------------------------------------------------------------
    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Fetch a value by dot path, e.g. ``"voice.tts.voice"``."""
        node: Any = self._data
        for part in dotted_key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def set(self, dotted_key: str, value: Any) -> None:
        """Set a value by dot path, creating intermediate dicts as needed."""
        parts = dotted_key.split(".")
        node = self._data
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value

    def section(self, name: str) -> Dict[str, Any]:
        """Return a whole section as a plain dict (empty dict if missing)."""
        value = self.get(name, {})
        return value if isinstance(value, dict) else {}

    def as_dict(self) -> Dict[str, Any]:
        """Return a deep copy of every setting."""
        return copy.deepcopy(self._data)

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __contains__(self, key: str) -> bool:
        return self.get(key, _MISSING) is not _MISSING

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Config path={self.path} model={self.get('llm.model')!r}>"

    # -- paths --------------------------------------------------------------
    def resolve(self, relative: str | Path) -> Path:
        """Resolve a possibly-relative path against the project root."""
        candidate = Path(str(relative)).expanduser()
        if candidate.is_absolute():
            return candidate
        return (self.root / candidate).resolve()

    def path_for(self, key: str) -> Path:
        """Resolve one of the ``paths.*`` entries to an absolute path."""
        return self.resolve(self.get(f"paths.{key}", key))

    def ensure_directories(self) -> List[Path]:
        """Create every configured directory. Returns the created paths."""
        created: List[Path] = []
        candidates: Iterable[str] = list(self.section("paths").values())
        for entry in candidates:
            try:
                directory = self.resolve(entry)
                directory.mkdir(parents=True, exist_ok=True)
                created.append(directory)
            except Exception:
                continue
        for file_key in ("logging.file", "database.path", "memory.path"):
            value = self.get(file_key)
            if not value:
                continue
            try:
                target = self.resolve(value)
                parent = target if file_key == "memory.path" else target.parent
                parent.mkdir(parents=True, exist_ok=True)
                created.append(parent)
            except Exception:
                continue
        return created

    # -- helpers ------------------------------------------------------------
    def enabled_modules(self) -> List[str]:
        """Names of every module toggled on in config."""
        return [name for name, on in self.section("modules").items() if on]

    def user_address(self) -> str:
        """How JARVIS should address the user in speech."""
        title = str(self.get("user.title", "") or "").strip()
        name = str(self.get("user.name", "") or "").strip()
        return title or name or "sir"

    def _apply_env_overrides(self) -> None:
        """Apply ``JARVIS_SECTION__KEY`` environment variable overrides."""
        for env_key, raw_value in os.environ.items():
            if not env_key.startswith(_ENV_PREFIX):
                continue
            dotted = env_key[len(_ENV_PREFIX) :].lower().replace("__", ".")
            if not dotted:
                continue
            self.set(dotted, _coerce(raw_value))


class _Missing:
    """Sentinel type for ``__contains__`` checks."""


_MISSING = _Missing()


def load_config(path: str | Path = "config.yaml") -> Config:
    """Convenience wrapper around :meth:`Config.load`."""
    return Config.load(path)
