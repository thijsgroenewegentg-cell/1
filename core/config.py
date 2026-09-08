# /core/config.py
"""YAML configuration with sane defaults, dot-path access and hot reload."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from utils.logger import get_logger

try:
    import yaml
except Exception:  # pragma: no cover - yaml is a hard requirement in practice
    yaml = None  # type: ignore[assignment]


logger = get_logger("core.config")

DEFAULT_CONFIG: Dict[str, Any] = {
    "user": {"name": "Sir", "title": "sir", "location": "auto", "units": "metric"},
    "assistant": {
        "name": "JARVIS",
        "language": "en",          # one setting for STT, TTS and the persona
        "personality": "witty",
        "sarcasm": 0.35,
        "greet_on_start": True,
        "proactive": True,
        #: Speak a one-line systems report (model, memory, modules, Blender)
        #: when JARVIS boots in voice mode, so a silent audio pipeline is
        #: obvious the moment it starts.
        "say_status_on_start": True,
        #: When enabled, the start-up announcement includes the daily briefing
        #: (tasks, calendar, reminders, weather) from the productivity module.
        "morning_brief_on_start": False,
        #: Ask before the first tool call of a turn when the chosen plan looks
        #: like a guess (e.g. the model invented a file name the user never
        #: said). Fixes the "he does something else than I asked" feeling.
        "confirm_plan": True,
        #: A global shortcut that summons the assistant from anywhere
        #: (e.g. "ctrl+alt+j"). Needs the optional 'keyboard' package on
        #: Windows/Linux; opens the web UI when one is running.
        "global_hotkey": "",
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
        #: Tiered models: routine chat goes to the small/fast ``fast_model``,
        #: and a hard plan step that already failed gets one retry on the
        #: big/slow ``deep_model``. Blank entries reuse the main model, so
        #: leaving all three the same name costs nothing.
        "fast_model": "",
        "deep_model": "",
        "tiered_models": True,  # master switch for the fast/deep split above
        "instant_chat": True,   # skip the classifier model for keyword-silent small talk
        "stream": True,
        "retries": 2,              # extra attempts when Ollama hiccups
        "retry_backoff": 0.75,     # seconds, doubled on each further attempt
        "warm_up": True,           # load the model at start-up, not mid-question
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
        #: Durable store of habits learned from completed interactions
        #: (e.g. "renders at 50% for previews"). Survives restarts.
        "preferences_file": "data/preferences.json",
        "summarize": True,
        "summary_trigger": 12,
        "context_char_budget": 9000,
    },
    "database": {"path": "data/jarvis.db"},
    "productivity": {
        "catch_up_on_start": True,
        "scheduler_interval": 15,
        "quiet_hours": "",
    },
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
            "language": "auto",        # auto = follow assistant.language
            "beam_size": 1,
            "vad_filter": True,
        },
        "tts": {
            "engine": "auto",          # auto | piper | edge | elevenlabs
            "piper_voice": "",
            "piper_speed": 1.0,
            "voice": "",               # blank = the default voice for the language
            "rate": "+8%",
            "volume": "+0%",
            "pitch": "+0Hz",
            "cache": True,
            "elevenlabs_api_key": "",
            "elevenlabs_voice_id": "21m00Tcm4TlvDq8ikWAM",
            "elevenlabs_model": "eleven_turbo_v2",
            "elevenlabs_stability": 0.5,
            "elevenlabs_similarity_boost": 0.75,
            "elevenlabs_style": 0.0,
            "elevenlabs_use_speaker_boost": True,
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
        "blender": True,
        "communications": True,
        "models": True,
        "self_improve": True,
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
        "screenshot_dir": "",        # blank = paths.screenshots
        "keep_screenshots": 10,
        "max_pixels": 1600000,
        "timeout": 180,
    },
    "blender": {
        "executable": "",            # blank = look on PATH and the usual places
        "output_dir": "data/renders",
        "engine": "",                # blank = whatever the .blend specifies
        "samples": 0,                # 0 = leave the scene's own sample count
        "timeout": 300,              # seconds for a script
        "render_timeout": 1800,      # seconds for a render
        "memory_mb": 0,              # 0 = no ceiling; renders are memory-hungry
        "allow_scripts": True,
        "allow_bpy_module": True,    # accept "pip install bpy" as a runtime
        #: Remembers the last-used .blend (per name and overall) and the
        #: render settings you last chose, so "render the animation" just
        #: works after a restart.
        "state_file": "data/blender_state.json",
        #: Open the first rendered frame in the OS image viewer whenever a
        #: render finishes. Off by default: "render and show me" opens it
        #: for that one call regardless.
        "show_after_render": False,
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
    "self_improve": {
        "root": "",  # blank = the directory JARVIS is installed in
        "enabled": True,
        "allow_code_edit": True,
        "allow_plugin_install": True,
        "review_plugins": True,
        "allow_pip_install": False,
        "run_tests_after_edit": True,
        "test_command": "tests/test_smoke.py",
        "test_timeout": 900,
        "git_commit": True,
        "auto_reload": True,
        "plugins_dir": "plugins",
        "repos_dir": "data/repos",
        "backup_dir": "data/backups",
        "keep_backups": 40,
        "max_file_bytes": 400000,
        "max_search_results": 8,
        "github_token_env": "GITHUB_TOKEN",
        "protected": [
            "utils/security.py",
            "modules/self_improve.py",
            "config.yaml",
        ],
    },
    "web_ui": {
        "enabled": False,
        "host": "0.0.0.0",
        "port": 8765,
        "token": "",
        "require_token": True,
        "rate_limit_per_minute": 40,
        "allow_tts": True,
        "max_audio_mb": 25,
        "title": "JARVIS",
    },
    "security": {
        "confirm_dangerous": True,
        "allow_shell": True,
        "shell_timeout": 60,
        "sandbox_memory_mb": 1024,
        "sandbox_timeout": 20,
        "audit_log": "data/audit.log",   # blank keeps the trail in memory only
        "audit_limit": 500,
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

def _load_secrets_env(root: Path) -> None:
    """Load ``data/secrets.env`` into ``os.environ`` without overwriting."""
    candidates = [root / "data" / "secrets.env", Path.cwd() / "data" / "secrets.env"]
    seen: set[Path] = set()
    for cand in candidates:
        try:
            cand = cand.resolve()
        except Exception:
            continue
        if cand in seen or not cand.is_file():
            continue
        seen.add(cand)
        try:
            for raw in cand.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if not key or key in os.environ:
                    continue
                # Only allow the known secret keys so a stray file cannot inject arbitrary env.
                if (key in {"ELEVENLABS_API_KEY", "GITHUB_TOKEN",
                           "JARVIS_EMAIL_PASSWORD"} or key.startswith("JARVIS_")):
                    os.environ[key] = value
        except Exception:
            continue



#: Older / alternative spellings mapped onto the keys JARVIS actually reads.
#: Anyone hand-writing a config (or following a spec sheet) tends to reach for
#: the left-hand form; both work, and the right-hand one wins if both appear.
KEY_ALIASES: Dict[str, str] = {
    "llm.base_url": "llm.host",
    "llm.url": "llm.host",
    "llm.provider": "llm.provider",          # accepted and ignored: always ollama
    "llm.vision_model": "vision.model",
    "voice.stt_model": "voice.stt.model",
    "voice.stt_language": "voice.stt.language",
    "voice.tts_voice": "voice.tts.voice",
    "voice.tts_speed": "voice.tts.rate",
    "voice.tts_rate": "voice.tts.rate",
    "voice.wake_word_sensitivity": "voice.sensitivity",
    "voice.speak_while_generating": "voice.stream_speech",
    "voice.interrupt_enabled": "voice.interrupt",
    "language": "assistant.language",
    "assistant.persona": "assistant.personality",
    "paths.data_dir": "paths.data",
    "paths.logs_dir": "paths.logs",
    "paths.backup_dir": "paths.backups",
    "paths.screenshots_dir": "paths.screenshots",
    "paths.knowledge_dir": "paths.knowledge",
    "paths.plugins_dir": "self_improve.plugins_dir",
    "database.file": "database.path",
    "web_ui.enabled": "web_ui.enabled",
    "security.confirm_destructive": "security.confirm_dangerous",
    "security.max_shell_timeout": "security.shell_timeout",
    "security.blacklist": "security.shell_blacklist",
    "self_improve.can_modify_code": "self_improve.allow_code_edit",
    "self_improve.can_install_packages": "self_improve.allow_pip",
    "self_improve.can_clone_repos": "self_improve.allow_clone",
    "self_improve.require_approval": "self_improve.review_plugins",
    "communications.email": "email",
    "quiet_hours": "productivity.quiet_hours",
}


def _normalise_aliases(data: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrite alias keys onto their canonical names.

    ``quiet_hours`` is special: the spec writes it as a block with
    ``enabled``/``start``/``end``, while JARVIS stores the compact
    ``"23:00-07:00"`` string, so the block is folded into one.

    Args:
        data: Raw settings straight out of the YAML file.

    Returns:
        The same settings with every alias moved to its real key. The input is
        not modified.
    """
    if not isinstance(data, dict):
        return {}
    result = copy.deepcopy(data)

    quiet = result.get("quiet_hours")
    if isinstance(quiet, str) and quiet.strip():
        result.setdefault("productivity", {})
        if isinstance(result["productivity"], dict):
            result["productivity"].setdefault("quiet_hours", quiet.strip())
        result.pop("quiet_hours", None)
    elif isinstance(quiet, dict):
        start = str(quiet.get("start", "") or "")
        end = str(quiet.get("end", "") or "")
        window = f"{start}-{end}" if start and end else ""
        if (start or end) and not window:
            logger.warning(
                "config.yaml: quiet_hours needs both 'start' and 'end' — ignoring it."
            )
        if not quiet.get("enabled", True):
            window = ""
        result.setdefault("productivity", {})
        if isinstance(result["productivity"], dict):
            result["productivity"].setdefault("quiet_hours", window)
        result.pop("quiet_hours", None)

    for alias, canonical in KEY_ALIASES.items():
        if alias == canonical or alias == "quiet_hours":
            continue
        value = _dig(result, alias.split("."))
        if value is _ABSENT:
            continue
        _drop(result, alias.split("."))
        if _dig(result, canonical.split(".")) is _ABSENT:
            _plant(result, canonical.split("."), value)
    return result


_ABSENT = object()
"""Sentinel for "this key was not present at all"."""


def _dig(data: Any, parts: List[str]) -> Any:
    """Read a nested key, returning :data:`_ABSENT` when it is not there."""
    node = data
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return _ABSENT
        node = node[part]
    return node


def _plant(data: Dict[str, Any], parts: List[str], value: Any) -> None:
    """Write a nested key, creating the intermediate dictionaries."""
    node = data
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


def _drop(data: Dict[str, Any], parts: List[str]) -> None:
    """Delete a nested key if it is there, pruning nothing else."""
    node: Any = data
    for part in parts[:-1]:
        node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return
    if isinstance(node, dict):
        node.pop(parts[-1], None)


#: Written at the top of a config file JARVIS creates from scratch.
_CONFIG_HEADER = """# =============================================================================
# /config.yaml
# JARVIS configuration. Every key is optional: delete one and the built-in
# default in core/config.py applies. Every setting is listed, with what it
# does, in docs/CONFIGURATION.md.
# =============================================================================

"""


def _format_scalar(value: Any) -> Optional[str]:
    """Render a scalar the way YAML expects, or ``None`` if it is not scalar.

    Args:
        value: The value to render.

    Returns:
        The text to write after ``key:``, or ``None`` for lists and dicts,
        which the line editor leaves alone.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "''"
    if isinstance(value, str):
        if value == "":
            return "''"
        risky = value[0] in "&*!|>%@`{[\"'" or value.strip() != value
        if risky or any(token in value for token in (": ", " #")):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return value
    return None


def _rewrite_yaml(text: str, data: Dict[str, Any]) -> Optional[str]:
    """Update the values in a YAML document without disturbing anything else.

    Walks the file line by line, tracking the current section from the
    indentation, and rewrites only the scalars whose value has changed.
    Comments, ordering, spacing and unknown keys are left exactly as they are.

    Args:
        text: The current file contents.
        data: The settings to write.

    Returns:
        The updated text, or ``None`` when the file cannot be edited safely
        (in which case the caller falls back to a full dump).
    """
    lines = text.splitlines(keepends=True)
    output: List[str] = []
    stack: List[Tuple[int, str]] = []   # (indent, key) for each open section
    seen: Set[str] = set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("- "):
            output.append(line)
            continue
        if ":" not in stripped:
            output.append(line)
            continue

        indent = len(line) - len(line.lstrip(" "))
        key = stripped.split(":", 1)[0].strip().strip("'\"")
        remainder = stripped.split(":", 1)[1]
        comment = ""
        body = remainder
        if " #" in remainder:
            body, _, trailing = remainder.partition(" #")
            comment = f"  #{trailing}"

        while stack and stack[-1][0] >= indent:
            stack.pop()
        dotted = ".".join([name for _, name in stack] + [key])

        if not body.strip():          # a section header, e.g. "voice:"
            stack.append((indent, key))
            output.append(line)
            continue

        seen.add(dotted)
        node: Any = data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                node = _ABSENT
                break
            node = node[part]
        if node is _ABSENT:
            output.append(line)
            continue

        rendered = _format_scalar(node)
        if rendered is None:          # a list or a nested mapping: leave it
            output.append(line)
            continue

        # Only touch a line whose value actually changed. Rewriting every
        # line would strip the author's quoting and comment alignment for no
        # reason, turning a one-setting change into a whole-file diff.
        try:
            existing = yaml.safe_load(body) if yaml is not None else object()
        except Exception:
            existing = object()
        if existing == node and type(existing) is type(node):
            output.append(line)
            continue
        output.append(f"{' ' * indent}{key}: {rendered}{comment}\n")

    return "".join(output)


def _deep_merge(
    base: Dict[str, Any], override: Dict[str, Any], path: str = ""
) -> Dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``.

    A typo that turns a section into a list or a scalar (``voice: yes``) used
    to replace the whole section, leaving every setting under it as ``None``
    and producing baffling failures much later. Such a value is refused and
    the defaults kept, with a warning naming the key.

    Args:
        base: The defaults.
        override: The user's settings.
        path: Dotted prefix used in warnings.

    Returns:
        A new merged dictionary.
    """
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        dotted = f"{path}.{key}" if path else key
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value, dotted)
        elif isinstance(result.get(key), dict) and not isinstance(value, dict):
            logger.warning(
                "config.yaml: '%s' should be a section, not %s — keeping the defaults.",
                dotted, type(value).__name__,
            )
        elif value is None and result.get(key) is not None:
            logger.warning(
                "config.yaml: '%s' is empty — keeping the default (%r).",
                dotted, result.get(key),
            )
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
        self._data: Dict[str, Any] = _deep_merge(
            DEFAULT_CONFIG, _normalise_aliases(data or {})
        )
        _load_secrets_env(self.root)
        # Mirror ELEVENLABS_API_KEY from env/secrets.env into the config view so
        # callers that only read config.get("voice.tts.elevenlabs_api_key") see it.
        _eleven = os.getenv("ELEVENLABS_API_KEY", "").strip()
        if _eleven and not str(self.get("voice.tts.elevenlabs_api_key", "") or "").strip():
            self.set("voice.tts.elevenlabs_api_key", _eleven)
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
        if not config_path.exists() and not config.save():
            # A mistyped --config path (or a read-only disk) must produce a
            # sentence, not a traceback from three frames deeper.
            logger.warning(
                "Could not write %s — running with defaults held in memory only.",
                config_path,
            )
        config.ensure_directories()
        return config

    def reload(self) -> "Config":
        """Re-read the YAML file from disk, keeping the same object identity."""
        if self.path and self.path.exists() and yaml is not None:
            try:
                loaded = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
                self._data = _deep_merge(DEFAULT_CONFIG, _normalise_aliases(loaded))
                _load_secrets_env(self.root)
                _eleven = os.getenv("ELEVENLABS_API_KEY", "").strip()
                if _eleven and not str(self.get("voice.tts.elevenlabs_api_key", "") or "").strip():
                    self.set("voice.tts.elevenlabs_api_key", _eleven)
                self._apply_env_overrides()
            except Exception:
                pass
        return self

    def save(self) -> bool:
        """Write the current settings back to ``self.path``.

        Existing files are edited in place, line by line, so comments, blank
        lines, ordering and anything the user wrote themselves all survive.
        Dumping the parsed data instead — which is what this used to do —
        quietly deleted every explanatory comment in the file the first time
        JARVIS changed a setting.

        Returns:
            True on success.
        """
        if not self.path or yaml is None:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                text = self.path.read_text(encoding="utf-8")
                updated = _rewrite_yaml(text, self._data)
                if updated is not None:
                    self.path.write_text(updated, encoding="utf-8")
                    return True
            self.path.write_text(
                _CONFIG_HEADER
                + yaml.safe_dump(self._data, sort_keys=False, allow_unicode=True),
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
        """Return a dotted key, so ``config["llm.model"]`` works."""
        return self.get(key)

    def __contains__(self, key: str) -> bool:
        """Report whether a dotted key is present."""
        return self.get(key, _MISSING) is not _MISSING

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        """Return a short, log-friendly description of the configuration."""
        return f"<Config path={self.path} model={self.get('llm.model')!r}>"

    def unwritable_paths(self) -> List[Path]:
        """Configured directories that could not be created.

        Returns:
            The paths that are missing after :meth:`ensure_directories` has
            tried; empty when everything is in order.
        """
        broken: List[Path] = []
        for entry in list(self.section("paths").values()):
            try:
                directory = self.resolve(entry)
            except Exception:
                continue
            if not directory.is_dir():
                broken.append(directory)
        return broken

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
            # JARVIS_LLM__MODEL is the documented form, but JARVIS_LLM_MODEL is
            # what people type. Resolve the single-underscore spelling against
            # the keys that actually exist rather than inventing a new one.
            if "." not in dotted and "_" in dotted and dotted not in self:
                for candidate in _underscore_variants(dotted):
                    if candidate in self:
                        dotted = candidate
                        break
            self.set(dotted, _coerce(raw_value))


def _underscore_variants(name: str) -> List[str]:
    """Every way an underscored env-var name could map onto dotted keys.

    ``llm_model`` yields ``llm.model``; ``voice_tts_voice`` yields
    ``voice.tts_voice`` and ``voice.tts.voice``, longest prefix first.

    Args:
        name: The lower-cased name with underscores.

    Returns:
        Candidate dotted keys, most specific first.
    """
    parts = name.split("_")
    variants: List[str] = []
    for split in range(1, len(parts)):
        variants.append(".".join(parts[:split]) + "." + "_".join(parts[split:]))
    variants.append(".".join(parts))
    return variants


class _Missing:
    """Sentinel type for ``__contains__`` checks."""


_MISSING = _Missing()


def load_config(path: str | Path = "config.yaml") -> Config:
    """Convenience wrapper around :meth:`Config.load`."""
    return Config.load(path)
