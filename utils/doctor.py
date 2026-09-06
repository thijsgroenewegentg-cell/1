# /utils/doctor.py
"""``python main.py --doctor`` — find out why JARVIS is unhappy.

Everything in here is deliberately defensive: the doctor has to run when the
brain will not start, when half the dependencies are missing and when Ollama
was never installed. It never imports the brain, never touches the network
unless asked, and turns every failure into a diagnosis rather than a
traceback.

Each check produces a :class:`Finding` with a state, a one-line result and —
when something is wrong — the exact command that fixes it.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import platform
import shutil
import socket
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.helpers import human_bytes, run_blocking, ssl_verify, which

#: The three states a check can end in.
OK = "ok"
WARN = "warn"
FAIL = "fail"


@dataclass
class Finding:
    """The result of a single diagnostic check.

    Attributes:
        name: Short label, e.g. ``"Ollama"``.
        state: One of :data:`OK`, :data:`WARN`, :data:`FAIL`.
        detail: What was actually found.
        fix: The command or action that resolves it, when there is one.
    """

    name: str
    state: str
    detail: str
    fix: str = ""

    @property
    def symbol(self) -> str:
        """A single character summarising the state."""
        return {OK: "✓", WARN: "!", FAIL: "✗"}.get(self.state, "?")


@dataclass
class Report:
    """Every finding from one run of the doctor.

    Attributes:
        findings: The checks, in the order they ran.
    """

    findings: List[Finding] = field(default_factory=list)

    def add(self, name: str, state: str, detail: str, fix: str = "") -> Finding:
        """Record a finding and return it.

        Args:
            name: Short label.
            state: :data:`OK`, :data:`WARN` or :data:`FAIL`.
            detail: What was found.
            fix: Optional remedy.

        Returns:
            The stored :class:`Finding`.
        """
        finding = Finding(name, state, detail, fix)
        self.findings.append(finding)
        return finding

    @property
    def failures(self) -> List[Finding]:
        """Findings that stop JARVIS from working."""
        return [f for f in self.findings if f.state == FAIL]

    @property
    def warnings(self) -> List[Finding]:
        """Findings that only cost you a feature."""
        return [f for f in self.findings if f.state == WARN]

    @property
    def healthy(self) -> bool:
        """True when nothing is broken."""
        return not self.failures

    def summary(self) -> str:
        """A one-line verdict, in character."""
        if self.healthy and not self.warnings:
            return "Everything checks out. Disappointingly little to complain about, sir."
        if self.healthy:
            return (
                f"Operational, with {len(self.warnings)} thing(s) degraded. "
                "Nothing fatal, sir."
            )
        return (
            f"{len(self.failures)} problem(s) will stop me working, "
            f"plus {len(self.warnings)} minor complaint(s)."
        )

    def as_dict(self) -> Dict[str, Any]:
        """A JSON-friendly view, for the web UI and tests."""
        return {
            "healthy": self.healthy,
            "failures": len(self.failures),
            "warnings": len(self.warnings),
            "summary": self.summary(),
            "findings": [
                {"name": f.name, "state": f.state, "detail": f.detail, "fix": f.fix}
                for f in self.findings
            ],
        }


#: ``import name`` → (pip name, what breaks without it). Required first.
REQUIRED_PACKAGES: List[Tuple[str, str, str]] = [
    ("yaml", "PyYAML", "reading config.yaml"),
    ("httpx", "httpx", "talking to Ollama"),
    ("rich", "rich", "the terminal UI"),
]

OPTIONAL_PACKAGES: List[Tuple[str, str, str]] = [
    ("chromadb", "chromadb", "long-term memory (falls back to SQLite)"),
    ("ddgs", "ddgs", "web search"),
    ("bs4", "beautifulsoup4", "reading web pages"),
    ("feedparser", "feedparser", "news headlines"),
    ("faster_whisper", "faster-whisper", "speech to text"),
    ("edge_tts", "edge-tts", "speech out loud"),
    ("sounddevice", "sounddevice", "the microphone"),
    ("numpy", "numpy", "audio buffers"),
    ("soundfile", "soundfile", "reading and writing wav"),
    ("psutil", "psutil", "system stats"),
    ("fastapi", "fastapi", "the phone/web interface"),
    ("uvicorn", "uvicorn", "serving the web interface"),
    ("pypdf", "pypdf", "reading PDFs"),
    ("docx", "python-docx", "reading Word documents"),
    ("pandas", "pandas", "CSV analysis"),
    ("pyautogui", "pyautogui", "desktop control"),
    ("PIL", "Pillow", "screenshots"),
    ("dateutil", "python-dateutil", "parsing dates in reminders"),
]


def _import_ok(module: str) -> bool:
    """Report whether a module imports, without letting it crash us."""
    try:
        importlib.import_module(module)
        return True
    except BaseException:  # a broken C extension can raise anything at all
        return False


def check_python(report: Report) -> None:
    """Check the interpreter version and whether a venv is active."""
    version = platform.python_version()
    if sys.version_info < (3, 9):  # noqa: UP036 — the point is to catch old runtimes
        report.add(
            "Python", FAIL, f"{version} — too old",
            "Install Python 3.9 or newer and recreate the venv.",
        )
    else:
        report.add("Python", OK, f"{version} on {platform.system()} {platform.machine()}")

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if in_venv:
        report.add("Virtual environment", OK, sys.prefix)
    else:
        report.add(
            "Virtual environment", WARN, "running against the system Python",
            "source .venv/bin/activate   (Windows: .venv\\Scripts\\activate)",
        )


def check_packages(report: Report) -> None:
    """Check that the required and optional dependencies import."""
    missing_required = [
        (pip_name, why) for module, pip_name, why in REQUIRED_PACKAGES
        if not _import_ok(module)
    ]
    if missing_required:
        report.add(
            "Core packages", FAIL,
            "missing " + ", ".join(name for name, _ in missing_required),
            "pip install -r requirements.txt",
        )
    else:
        report.add("Core packages", OK, "PyYAML, httpx and rich are installed")

    missing_optional = [
        (pip_name, why) for module, pip_name, why in OPTIONAL_PACKAGES
        if not _import_ok(module)
    ]
    if not missing_optional:
        report.add(
            "Optional packages", OK,
            f"all {len(OPTIONAL_PACKAGES)} present — every feature is available",
        )
    else:
        listed = ", ".join(f"{name} ({why})" for name, why in missing_optional[:4])
        if len(missing_optional) > 4:
            listed += f", and {len(missing_optional) - 4} more"
        report.add(
            "Optional packages", WARN, f"missing {listed}",
            "pip install " + " ".join(name for name, _ in missing_optional),
        )


async def check_ollama(report: Report, config: Any) -> None:
    """Check that Ollama answers and has the configured model."""
    host = str(config.get("llm.host", "http://localhost:11434")).rstrip("/")
    model = str(config.get("llm.model", "llama3.2"))
    binary = which("ollama")

    try:
        import httpx
    except Exception:
        report.add("Ollama", FAIL, "cannot check — httpx is not installed",
                   "pip install -r requirements.txt")
        return

    try:
        async with httpx.AsyncClient(timeout=5.0, verify=ssl_verify()) as client:
            response = await client.get(f"{host}/api/tags")
            response.raise_for_status()
            payload = response.json()
    except Exception as error:
        detail = f"not answering at {host} ({type(error).__name__})"
        fix = "ollama serve" if binary else (
            "Install it from https://ollama.com/download, then: ollama serve"
        )
        report.add("Ollama", FAIL, detail, fix)
        return

    names = [str(item.get("name", "")) for item in payload.get("models", [])]
    report.add("Ollama", OK, f"online at {host} with {len(names)} model(s)")

    stem = model.split(":")[0]
    if any(name == model or name.split(":")[0] == stem for name in names):
        report.add("Chat model", OK, f"'{model}' is installed")
    else:
        report.add(
            "Chat model", FAIL, f"'{model}' is not installed",
            f"ollama pull {model}",
        )

    router = str(config.get("llm.router_model", "") or "")
    if router and not any(
        name == router or name.split(":")[0] == router.split(":")[0] for name in names
    ):
        report.add(
            "Router model", WARN, f"'{router}' is not installed",
            f"ollama pull {router}   (or clear llm.router_model)",
        )


def check_storage(report: Report, root: Path, config: Any) -> None:
    """Check that the data directories exist, are writable and have room."""
    resolve = getattr(config, "resolve", None)
    data_dir = (
        config.path_for("data") if hasattr(config, "path_for")
        else Path(str(config.get("paths.data", root / "data"))).expanduser()
    )
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        report.add("Data directory", OK, f"{data_dir} is writable")
    except Exception as error:
        report.add(
            "Data directory", FAIL, f"{data_dir} is not writable ({error})",
            "Fix the permissions, or point paths.data somewhere you own.",
        )
        return

    # Every other configured folder matters too: logs, backups, screenshots
    # and the knowledge base each break something different when missing.
    broken: List[Path] = list(getattr(config, "unwritable_paths", lambda: [])())
    if broken:
        report.add(
            "Configured folders", FAIL,
            "could not be created: " + ", ".join(str(path) for path in broken),
            "Check the paths section of config.yaml, and the permissions on those "
            "directories.",
        )
    else:
        report.add("Configured folders", OK, "all present and writable")

    try:
        usage = shutil.disk_usage(str(data_dir))
        free = usage.free
        if free < 2 * 1024**3:
            report.add(
                "Disk space", WARN, f"{human_bytes(free)} free where the models live",
                "Models want a few GB. Delete something, or 'ollama rm' an unused model.",
            )
        else:
            report.add("Disk space", OK, f"{human_bytes(free)} free")
    except Exception:
        report.add("Disk space", WARN, "could not be measured")

    configured = str(config.get("database.path", "data/jarvis.db"))
    database = (
        resolve(configured) if callable(resolve)
        else Path(configured).expanduser()
    )
    if not database.is_absolute():
        database = data_dir / database
    try:
        connection = sqlite3.connect(str(database))
        try:
            state = connection.execute("PRAGMA integrity_check").fetchone()
        finally:
            connection.close()
        if state and state[0] == "ok":
            size = database.stat().st_size if database.exists() else 0
            report.add("Database", OK, f"{database.name} healthy ({human_bytes(size)})")
        else:
            report.add(
                "Database", FAIL, f"{database} fails its integrity check",
                "python main.py --backup, then move the broken file aside.",
            )
    except Exception as error:
        report.add(
            "Database", FAIL, f"{database} cannot be opened ({error})",
            "Check the permissions on the data directory.",
        )


def check_memory_ram(report: Report, config: Any) -> None:
    """Check that there is enough free RAM for the configured model."""
    try:
        import psutil
    except Exception:
        report.add("Memory", WARN, "psutil is not installed, so RAM was not checked",
                   "pip install psutil")
        return
    try:
        available = int(psutil.virtual_memory().available)
    except Exception:
        report.add("Memory", WARN, "RAM could not be measured")
        return

    model = str(config.get("llm.model", "llama3.2")).lower()
    # Rough resident sizes for the usual 4-bit quantised builds.
    needed = 4 * 1024**3
    for marker, bytes_needed in (
        ("70b", 40 * 1024**3), ("34b", 20 * 1024**3), ("13b", 9 * 1024**3),
        ("8b", 6 * 1024**3), ("7b", 5 * 1024**3), ("3b", 3 * 1024**3),
        ("1b", 2 * 1024**3), ("mini", 3 * 1024**3),
    ):
        if marker in model:
            needed = bytes_needed
            break

    if available >= needed:
        report.add("Memory", OK, f"{human_bytes(available)} free, enough for '{model}'")
    else:
        report.add(
            "Memory", WARN,
            f"{human_bytes(available)} free; '{model}' usually wants "
            f"{human_bytes(needed)}",
            "Ask me to 'recommend a smaller model', or close something heavy.",
        )


def check_audio(report: Report, config: Any) -> None:
    """Check the microphone, the audio player and the wake-word engine."""
    if not config.get("voice.enabled", True):
        report.add("Voice", OK, "disabled in config.yaml — skipping audio checks")
        return

    try:
        import sounddevice
        devices = sounddevice.query_devices()
        inputs = [d for d in devices if int(d.get("max_input_channels", 0)) > 0]
        if inputs:
            default = sounddevice.query_devices(kind="input")
            report.add("Microphone", OK, f"{len(inputs)} input(s), default: {default['name']}")
        else:
            report.add(
                "Microphone", WARN, "no input device found",
                "Plug a microphone in, or run with --no-voice.",
            )
    except Exception as error:
        report.add(
            "Microphone", WARN, f"sounddevice unavailable ({type(error).__name__})",
            "pip install sounddevice   (Linux also needs: sudo apt install libportaudio2)",
        )

    player = next((name for name in ("ffplay", "afplay", "mpv", "aplay", "paplay",
                                     "mpg123", "cvlc") if which(name)), "")
    if player or platform.system() == "Windows":
        report.add("Audio playback", OK, player or "winsound (built in)")
    else:
        report.add(
            "Audio playback", WARN, "no player found, so speech will be silent",
            "sudo apt install ffmpeg   (macOS: brew install ffmpeg)",
        )

    engine = str(config.get("voice.engine", "auto"))
    if engine.strip().lower() in {"none", "off", "false", "disabled"} or not str(
        config.get("voice.wake_word", "jarvis")
    ).strip():
        report.add("Wake word", OK, "off by choice — JARVIS answers anything it hears")
        return
    key = str(config.get("voice.porcupine_access_key", "") or "")
    if engine == "porcupine" and not key:
        report.add(
            "Wake word", WARN, "engine is 'porcupine' but no access key is set",
            "Get a free key at console.picovoice.ai, or set voice.engine: auto",
        )
    else:
        report.add("Wake word", OK, f"engine '{engine}'")


async def check_network(report: Report) -> None:
    """Check the free services JARVIS uses, without needing any of them."""
    try:
        import httpx
    except Exception:
        return

    targets = [
        ("Web search", "https://duckduckgo.com", "search and news"),
        ("Weather", "https://wttr.in", "the weather report"),
        ("Speech service", "https://speech.platform.bing.com", "edge-tts voices"),
    ]
    reachable: List[str] = []
    unreachable: List[str] = []
    async with httpx.AsyncClient(timeout=4.0, verify=ssl_verify(),
                                 follow_redirects=True) as client:
        async def probe(name: str, url: str, why: str) -> None:
            """Record whether one endpoint answers at all."""
            try:
                await client.head(url)
                reachable.append(name)
            except Exception:
                unreachable.append(f"{name} ({why})")

        await asyncio.gather(*(probe(*target) for target in targets))

    if not unreachable:
        report.add("Internet", OK, "search, weather and online voices all reachable")
    elif len(unreachable) == len(targets):
        report.add(
            "Internet", WARN, "no internet — local features still work",
            "Everything offline keeps working: the model, memory, files, timers.",
        )
    else:
        report.add("Internet", WARN, "cannot reach " + ", ".join(unreachable))


def check_web_port(report: Report, config: Any) -> None:
    """Check whether the web UI's port is free."""
    port = int(config.get("web_ui.port", 8765))
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(1.0)
    try:
        probe.bind(("0.0.0.0", port))
        report.add("Web UI port", OK, f"{port} is free")
    except OSError:
        report.add(
            "Web UI port", WARN, f"{port} is already in use",
            f"Use another: python main.py --web --port {port + 1}",
        )
    finally:
        probe.close()


def check_config(report: Report, config: Any, path: Optional[Path]) -> None:
    """Check the config file itself, and the settings people get wrong."""
    if path is not None and path.exists():
        report.add("Config file", OK, str(path))
    else:
        report.add(
            "Config file", WARN, "not found — running on built-in defaults",
            "Copy the shipped config.yaml next to main.py.",
        )

    from utils.language import resolve as resolve_language

    raw = str(config.get("assistant.language", "en"))
    language = resolve_language(raw)
    if language is None:
        report.add(
            "Language", FAIL, f"assistant.language '{raw}' is not one I have a voice for",
            "Run 'python main.py --cli' and type /languages for the list.",
        )
    else:
        report.add("Language", OK, f"{language.english_name} ({language.native_name})")

    roots = config.get("security.allowed_roots", []) or []
    missing = [str(item) for item in roots if not Path(str(item)).expanduser().exists()]
    if missing:
        report.add(
            "Allowed folders", WARN, "these do not exist: " + ", ".join(missing[:3]),
            "Fix security.allowed_roots, or create the folders.",
        )
    else:
        report.add("Allowed folders", OK, f"{len(roots) or 'default'} root(s) configured")


def check_temp(report: Report) -> None:
    """Check that the temp directory works — audio and sandboxing need it."""
    try:
        with tempfile.NamedTemporaryFile(prefix="jarvis-doctor-", delete=True) as handle:
            handle.write(b"ok")
        report.add("Temp directory", OK, tempfile.gettempdir())
    except Exception as error:
        report.add(
            "Temp directory", FAIL, f"{tempfile.gettempdir()} is unusable ({error})",
            "Set TMPDIR to somewhere writable.",
        )


async def diagnose(config: Any, root: Optional[Path] = None) -> Report:
    """Run every check and collect the findings.

    Args:
        config: A loaded :class:`core.config.Config` (or anything with ``get``).
        root: The project directory, used to locate ``data/``.

    Returns:
        A :class:`Report`. It never raises: a check that explodes becomes a
        warning about itself.
    """
    project_root = root or Path(__file__).resolve().parent.parent
    report = Report()
    config_path = getattr(config, "path", None)

    steps: List[Tuple[str, Any]] = [
        ("Python", lambda: check_python(report)),
        ("Packages", lambda: check_packages(report)),
        ("Config", lambda: check_config(report, config, config_path)),
        ("Ollama", lambda: check_ollama(report, config)),
        ("Memory", lambda: check_memory_ram(report, config)),
        ("Storage", lambda: check_storage(report, project_root, config)),
        ("Temp", lambda: check_temp(report)),
        ("Audio", lambda: check_audio(report, config)),
        ("Network", lambda: check_network(report)),
        ("Web port", lambda: check_web_port(report, config)),
    ]

    for label, step in steps:
        try:
            outcome = step()
            if asyncio.iscoroutine(outcome):
                await outcome
        except Exception as error:  # a diagnostic must never be the thing that crashes
            report.add(label, WARN, f"check failed: {type(error).__name__}: {error}")

    return report


async def diagnose_config_path(path: Optional[str] = None) -> Report:
    """Load the config from disk and diagnose it.

    Args:
        path: Optional path to ``config.yaml``.

    Returns:
        The finished :class:`Report`.
    """
    from core.config import Config

    root = Path(__file__).resolve().parent.parent
    target = root / (path or "config.yaml")
    config = await run_blocking(Config.load, target)
    return await diagnose(config, root=root)


def render(report: Report, use_colour: bool = True) -> str:
    """Format a report for a terminal.

    Args:
        report: The finished report.
        use_colour: Whether to include ANSI colour.

    Returns:
        The printable text.
    """
    colours = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m"}
    reset = "\033[0m"
    width = max((len(f.name) for f in report.findings), default=10)
    lines: List[str] = []
    for finding in report.findings:
        prefix = colours.get(finding.state, "") if use_colour else ""
        suffix = reset if use_colour and prefix else ""
        lines.append(f"{prefix}{finding.symbol}{suffix} {finding.name:<{width}}  {finding.detail}")
        if finding.fix:
            lines.append(f"  {'':<{width}}  → {finding.fix}")
    lines.append("")
    lines.append(report.summary())
    return "\n".join(lines)


async def main(path: Optional[str] = None) -> int:
    """Run the doctor from the command line.

    Args:
        path: Optional config path.

    Returns:
        ``0`` when nothing is broken, ``1`` otherwise.
    """
    report = await diagnose_config_path(path)
    print(render(report, use_colour=os.environ.get("NO_COLOR") is None))
    return 0 if report.healthy else 1


__all__ = [
    "FAIL",
    "OK",
    "WARN",
    "Finding",
    "Report",
    "diagnose",
    "diagnose_config_path",
    "main",
    "render",
]
