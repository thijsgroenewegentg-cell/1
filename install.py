# /install.py
"""JARVIS — one-command installer.

Run it with any Python 3.9+ interpreter::

    python3 install.py          # macOS / Linux
    py install.py               # Windows

…or just double-click ``install.bat`` (Windows) / ``install.command`` (macOS).

It does the whole job:

1. checks Python, disk space, RAM and internet
2. creates the ``.venv`` virtual environment
3. installs the packages for the profile you choose (full / standard / minimal)
4. installs Ollama if it is missing, starts it, and pulls the language model
5. creates the data folders and personalises ``config.yaml``
6. offers a desktop / Start-menu shortcut
7. runs the component self-test and tells you exactly how to start

The installer itself has **no dependencies** — it is pure standard library, so
it runs before anything is installed. Nothing here costs money and no account
is required at any point.

Useful flags::

    python3 install.py --yes             # accept every default, no questions
    python3 install.py --minimal         # text-only install, ~120 MB
    python3 install.py --no-ollama       # skip the LLM engine entirely
    python3 install.py --model mistral   # pull a different model
    python3 install.py --repair          # reinstall packages into an existing venv
    python3 install.py --help            # everything else
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_DIR: Path = Path(__file__).resolve().parent
IS_WINDOWS: bool = os.name == "nt"
IS_MACOS: bool = sys.platform == "darwin"
IS_LINUX: bool = sys.platform.startswith("linux")

MIN_PYTHON: Tuple[int, int] = (3, 9)
OLLAMA_HOST: str = os.environ.get("JARVIS_OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL: str = os.environ.get("JARVIS_MODEL", "llama3.2")
EMBED_MODEL: str = os.environ.get("JARVIS_EMBED_MODEL", "nomic-embed-text")
VISION_MODEL: str = os.environ.get("JARVIS_VISION_MODEL", "llava")

#: A free, offline Piper voice (CC-BY licensed, no account needed).
PIPER_VOICE_NAME: str = "en_GB-alan-medium"
PIPER_VOICE_BASE: str = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/"
)

#: Package groups, straight out of requirements.txt but installable in stages
#: so that one optional failure cannot sink the whole install.
PACKAGE_GROUPS: Dict[str, List[str]] = {
    "core": [
        "PyYAML>=6.0.1",
        "httpx>=0.27.0",
        "rich>=13.7.0",
        "python-dateutil>=2.9.0",
        "psutil>=5.9.8",
    ],
    "web": [
        "ddgs>=9.0.0",
        "beautifulsoup4>=4.12.3",
        "lxml>=5.2.0",
        "requests>=2.32.0",
        "feedparser>=6.0.11",
    ],
    "interface": [
        "fastapi>=0.110.0",
        "uvicorn[standard]>=0.29.0",
    ],
    "memory": [
        "chromadb>=0.5.0",
    ],
    "documents": [
        "pypdf>=4.2.0",
        "python-docx>=1.1.2",
        "pandas>=2.2.0",
        "python-pptx>=0.6.23",
    ],
    "desktop": [
        "pyautogui>=0.9.54",
        "Pillow>=10.3.0",
        "pyperclip>=1.8.2",
    ],
    "voice": [
        "edge-tts>=6.1.10",
        "piper-tts>=1.2.0",
        "faster-whisper>=1.0.3",
        "sounddevice>=0.4.6",
        "numpy>=1.26.0",
        "soundfile>=0.12.1",
        "pvporcupine>=3.0.2",
        "openwakeword>=0.6.0",
        "webrtcvad-wheels>=2.0.14",
    ],
    "windows": [
        "pycaw>=20240210",
        "comtypes>=1.4.1",
        "pywin32>=306",
    ],
}

#: Which groups each profile installs, in order.
PROFILES: Dict[str, List[str]] = {
    "minimal": ["core", "web", "interface"],
    "standard": ["core", "web", "interface", "memory", "documents", "desktop"],
    "full": ["core", "web", "interface", "memory", "documents", "desktop", "voice"],
}

#: Groups JARVIS can live without — a failure here is a warning, not an error.
OPTIONAL_GROUPS = {"memory", "documents", "desktop", "voice", "windows"}

PROFILE_BLURB: Dict[str, str] = {
    "full": "everything: voice, wake word, vision, documents, desktop control",
    "standard": "text, web, memory, documents, desktop control (no microphone)",
    "minimal": "text and web only — the smallest possible install",
}

PROFILE_SIZE: Dict[str, str] = {
    "full": "~2.5 GB",
    "standard": "~700 MB",
    "minimal": "~120 MB",
}

WARNINGS: List[str] = []


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------


class Colour:
    """ANSI colour codes, blanked out when the terminal cannot handle them."""

    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[36m"
    RESET = "\033[0m"

    @classmethod
    def disable(cls) -> None:
        """Strip every escape sequence (used for dumb terminals and pipes)."""
        for attribute in ("BOLD", "DIM", "RED", "GREEN", "YELLOW", "BLUE", "RESET"):
            setattr(cls, attribute, "")


def enable_colour() -> None:
    """Turn on ANSI colours, including on Windows 10+ consoles."""
    if os.environ.get("NO_COLOR"):
        Colour.disable()
        return
    if IS_WINDOWS:
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING on stdout.
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            Colour.disable()
            return
    if not sys.stdout.isatty():
        Colour.disable()


def banner() -> None:
    """Print the JARVIS logo."""
    print(
        f"""{Colour.BLUE}{Colour.BOLD}
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝{Colour.RESET}

  {Colour.BOLD}Installer{Colour.RESET} — free, local, no API keys, no subscriptions
"""
    )


def step(number: int, total: int, title: str) -> None:
    """Announce a numbered installation step."""
    print(
        f"\n{Colour.BLUE}{Colour.BOLD}[{number}/{total}]{Colour.RESET} "
        f"{Colour.BOLD}{title}{Colour.RESET}",
        flush=True,
    )


def ok(message: str) -> None:
    """Report a successful action."""
    print(f"  {Colour.GREEN}✓{Colour.RESET} {message}", flush=True)


def warn(message: str, remember: bool = True) -> None:
    """Report a non-fatal problem and collect it for the final summary."""
    print(f"  {Colour.YELLOW}!{Colour.RESET} {message}", flush=True)
    if remember:
        WARNINGS.append(message)


def fail(message: str) -> None:
    """Report a fatal problem."""
    print(f"  {Colour.RED}✗{Colour.RESET} {message}", flush=True)


def info(message: str) -> None:
    """Print an indented informational line."""
    print(f"    {Colour.DIM}{message}{Colour.RESET}", flush=True)


def progress(message: str) -> None:
    """Overwrite the current line with a live progress message."""
    if not sys.stdout.isatty():
        return
    width = max(30, shutil.get_terminal_size((80, 20)).columns - 6)
    text = message if len(message) <= width else message[: width - 1] + "…"
    print(f"\r  {Colour.DIM}· {text}{Colour.RESET}".ljust(width + 8), end="", flush=True)


def clear_progress() -> None:
    """Erase the live progress line."""
    if sys.stdout.isatty():
        width = shutil.get_terminal_size((80, 20)).columns
        print("\r" + " " * (width - 1) + "\r", end="", flush=True)


def ask(question: str, default: str = "") -> str:
    """Ask a free-text question, returning ``default`` when input is impossible."""
    if not sys.stdin.isatty():
        return default
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"  {Colour.BOLD}?{Colour.RESET} {question}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return answer or default


def ask_yes_no(question: str, default: bool = True, assume_yes: bool = False) -> bool:
    """Ask a yes/no question.

    Args:
        question: The prompt text.
        default: The answer used for Enter, non-interactive shells and ``--yes``.
        assume_yes: Skip the prompt entirely (``--yes`` mode).

    Returns:
        The user's choice.
    """
    if assume_yes or not sys.stdin.isatty():
        return default
    hint = "Y/n" if default else "y/N"
    try:
        answer = input(f"  {Colour.BOLD}?{Colour.RESET} {question} [{hint}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    if not answer:
        return default
    return answer[0] == "y"


# ---------------------------------------------------------------------------
# Small system helpers
# ---------------------------------------------------------------------------


def run(command: Sequence[str], timeout: int = 600, **kwargs: object) -> subprocess.CompletedProcess:
    """Run a command and capture its output, never raising on failure."""
    try:
        return subprocess.run(  # type: ignore[call-overload]
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_DIR),
            **kwargs,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(list(command), 127, "", "command not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(list(command), 124, "", "timed out")
    except Exception as exc:  # pragma: no cover - defensive
        return subprocess.CompletedProcess(list(command), 1, "", str(exc))


def run_live(command: Sequence[str], timeout: int = 3600) -> int:
    """Run a command with its output attached to this terminal."""
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        return subprocess.call(list(command), cwd=str(PROJECT_DIR), timeout=timeout)
    except FileNotFoundError:
        return 127
    except subprocess.TimeoutExpired:
        return 124
    except Exception:  # pragma: no cover - defensive
        return 1


def run_streaming(command: Sequence[str], keep: int = 60) -> Tuple[int, str]:
    """Run a command, showing a compact one-line progress trace.

    Args:
        command: The argument vector.
        keep: How many output lines to retain for error reporting.

    Returns:
        ``(exit_code, tail_of_output)``.
    """
    interesting = ("Collecting", "Downloading", "Installing", "Building", "Preparing",
                   "Using cached", "Successfully", "Requirement already")
    tail: List[str] = []
    try:
        process = subprocess.Popen(
            list(command),
            cwd=str(PROJECT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return 1, str(exc)

    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.rstrip()
        if not line:
            continue
        tail.append(line)
        del tail[:-keep]
        if line.startswith(interesting):
            progress(line)
    process.wait()
    clear_progress()
    return process.returncode, "\n".join(tail)


def http_get(url: str, timeout: int = 5) -> Optional[bytes]:
    """Fetch a URL, returning ``None`` on any failure."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "JARVIS-installer"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception:
        return None


def download(url: str, destination: Path, label: str) -> bool:
    """Download a file with a percentage progress line."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "JARVIS-installer"})
        with urllib.request.urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(262144)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if total:
                        progress(f"{label} {done * 100 // total}% "
                                 f"({done // 1048576} of {total // 1048576} MB)")
                    else:
                        progress(f"{label} {done // 1048576} MB")
        clear_progress()
        return True
    except Exception as exc:
        clear_progress()
        fail(f"download failed: {exc}")
        return False


def total_ram_gb() -> float:
    """Best-effort physical memory size in GiB (0.0 when unknown)."""
    try:
        if IS_LINUX:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1048576
        elif IS_MACOS:
            result = run(["sysctl", "-n", "hw.memsize"], timeout=10)
            if result.returncode == 0:
                return int(result.stdout.strip()) / 1073741824
        elif IS_WINDOWS:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                """Windows ``MEMORYSTATUSEX``."""

                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
            return float(status.ullTotalPhys) / 1073741824
    except Exception:
        return 0.0
    return 0.0


def suggest_model() -> str:
    """Pick a sensible default model for the amount of RAM available."""
    ram = total_ram_gb()
    if 0 < ram < 6:
        return "llama3.2:1b"
    return DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Step 1 — environment checks
# ---------------------------------------------------------------------------


def check_environment() -> bool:
    """Verify Python, disk, RAM and connectivity.

    Returns:
        False only when the problem makes installation impossible.
    """
    version = sys.version_info
    if version < MIN_PYTHON:
        fail(f"Python {version.major}.{version.minor} is too old — 3.9 or newer is required.")
        info("Get it from https://www.python.org/downloads/ (free).")
        return False
    ok(f"Python {version.major}.{version.minor}.{version.micro} — {platform.system()} "
       f"{platform.machine()}")

    if not (PROJECT_DIR / "main.py").exists():
        fail(f"{PROJECT_DIR} does not look like the JARVIS folder (no main.py).")
        return False

    try:
        free_gb = shutil.disk_usage(PROJECT_DIR).free / 1073741824
        if free_gb < 3:
            warn(f"only {free_gb:.1f} GB free — the model alone needs ~2 GB")
        else:
            ok(f"{free_gb:.0f} GB free disk space")
    except Exception:
        pass

    ram = total_ram_gb()
    if ram:
        if ram < 6:
            warn(f"{ram:.0f} GB RAM — I will suggest the small 1B model")
        else:
            ok(f"{ram:.0f} GB RAM")

    if http_get("https://pypi.org/simple/", timeout=8) is None:
        warn("no internet connection detected — package downloads will fail")
    else:
        ok("internet reachable")

    if shutil.which("git"):
        ok("git found (JARVIS can clone repositories to extend itself)")
    else:
        warn("git not found — self-extension from GitHub will be unavailable", remember=False)
        info("Install it later from https://git-scm.com/downloads if you want that feature.")
    return True


# ---------------------------------------------------------------------------
# Step 2 — virtual environment
# ---------------------------------------------------------------------------


def venv_python(venv_dir: Path) -> Path:
    """Return the interpreter path inside a virtual environment."""
    if IS_WINDOWS:
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def create_venv(venv_dir: Path, recreate: bool) -> Optional[Path]:
    """Create (or reuse) the project virtual environment.

    Args:
        venv_dir: Where the environment lives.
        recreate: Delete an existing environment first.

    Returns:
        The interpreter path, or ``None`` when creation failed.
    """
    python = venv_python(venv_dir)
    if recreate and venv_dir.exists():
        info("removing the previous environment…")
        shutil.rmtree(venv_dir, ignore_errors=True)

    if python.exists():
        ok(f"reusing the existing environment at {venv_dir.name}/")
        return python

    info("creating the virtual environment (a few seconds)…")
    result = run([sys.executable, "-m", "venv", str(venv_dir)], timeout=300)
    if result.returncode != 0 or not python.exists():
        fail("could not create the virtual environment.")
        detail = (result.stderr or result.stdout).strip().splitlines()
        for line in detail[-4:]:
            info(line)
        if IS_LINUX:
            info("On Debian/Ubuntu run:  sudo apt install python3-venv python3-pip")
        return None
    ok(f"virtual environment ready at {venv_dir}")
    return python


def upgrade_pip(python: Path) -> None:
    """Bring pip, setuptools and wheel up to date inside the environment."""
    code, _ = run_streaming([str(python), "-m", "pip", "install", "--upgrade",
                             "pip", "setuptools", "wheel"])
    if code == 0:
        ok("pip, setuptools and wheel upgraded")
    else:
        warn("could not upgrade pip — continuing with the bundled version", remember=False)


# ---------------------------------------------------------------------------
# Step 3 — packages
# ---------------------------------------------------------------------------


def install_group(python: Path, group: str, packages: Sequence[str]) -> bool:
    """Install one package group, isolating failures when it is optional.

    Args:
        python: The virtual environment interpreter.
        group: Group name, used for messages.
        packages: Requirement specifiers.

    Returns:
        True when everything in the group installed.
    """
    print(f"  {Colour.BOLD}{group}{Colour.RESET} ({len(packages)} packages)")
    code, output = run_streaming([str(python), "-m", "pip", "install", "--upgrade", *packages])
    if code == 0:
        ok(f"{group} installed")
        return True

    if group not in OPTIONAL_GROUPS:
        fail(f"{group} failed to install")
        for line in output.splitlines()[-6:]:
            info(line)
        return False

    # Optional group: find out exactly which package is unhappy and keep the rest.
    warn(f"{group}: one or more packages failed — retrying individually")
    broken: List[str] = []
    for package in packages:
        single, _ = run_streaming([str(python), "-m", "pip", "install", "--upgrade", package])
        if single != 0:
            broken.append(package.split(">=")[0].split("[")[0])
    if broken:
        warn(f"{group}: could not install {', '.join(broken)} — that feature will be disabled")
        return False
    ok(f"{group} installed")
    return True


def install_packages(python: Path, profile: str) -> bool:
    """Install every group belonging to a profile."""
    groups = list(PROFILES[profile])
    if IS_WINDOWS:
        groups.append("windows")

    essential_ok = True
    for group in groups:
        packages = PACKAGE_GROUPS[group]
        if not install_group(python, group, packages) and group not in OPTIONAL_GROUPS:
            essential_ok = False
            break
    return essential_ok


# ---------------------------------------------------------------------------
# Step 4 — Ollama and the model
# ---------------------------------------------------------------------------


def find_ollama() -> Optional[str]:
    """Locate the Ollama binary, including the usual GUI install locations."""
    found = shutil.which("ollama")
    if found:
        return found
    candidates: List[Path] = []
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            candidates.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
        candidates.append(Path(r"C:\Program Files\Ollama\ollama.exe"))
    elif IS_MACOS:
        candidates += [
            Path("/Applications/Ollama.app/Contents/Resources/ollama"),
            Path("/usr/local/bin/ollama"),
            Path("/opt/homebrew/bin/ollama"),
        ]
    else:
        candidates += [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def ollama_is_running() -> bool:
    """True when the Ollama HTTP API answers."""
    return http_get(f"{OLLAMA_HOST}/api/tags", timeout=3) is not None


def install_ollama(assume_yes: bool) -> Optional[str]:
    """Install the Ollama runtime for the current platform.

    Returns:
        The path to the binary, or ``None`` if it was not installed.
    """
    print("  Ollama is the free local engine that runs the language model.")
    if not ask_yes_no("Install Ollama now?", default=True, assume_yes=assume_yes):
        warn("skipping Ollama — JARVIS will run in degraded (no-LLM) mode")
        info("Install it later from https://ollama.com/download")
        return None

    if IS_LINUX:
        if not shutil.which("curl"):
            fail("curl is required for the official installer")
            info("sudo apt install curl   (or dnf/pacman equivalent), then rerun this script")
            return None
        info("running the official installer — it may ask for your password…")
        run_live(["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"], timeout=1800)

    elif IS_MACOS:
        if shutil.which("brew"):
            info("installing with Homebrew…")
            run_live(["brew", "install", "ollama"], timeout=1800)
        else:
            archive = Path(tempfile.gettempdir()) / "Ollama-darwin.zip"
            if download("https://ollama.com/download/Ollama-darwin.zip", archive,
                        "downloading Ollama"):
                info("unpacking into /Applications…")
                result = run(["ditto", "-x", "-k", str(archive), "/Applications"], timeout=600)
                if result.returncode != 0:
                    warn("could not unpack automatically")
                    info("Open the download manually: https://ollama.com/download/mac")
                else:
                    run(["open", "-a", "Ollama"], timeout=60)

    elif IS_WINDOWS:
        installer = Path(tempfile.gettempdir()) / "OllamaSetup.exe"
        if download("https://ollama.com/download/OllamaSetup.exe", installer,
                    "downloading Ollama"):
            info("running the Ollama installer (accept the prompt if Windows asks)…")
            code = run_live([str(installer), "/VERYSILENT", "/NORESTART"], timeout=1800)
            if code != 0:
                run_live([str(installer)], timeout=1800)

    time.sleep(2)
    binary = find_ollama()
    if binary:
        ok(f"Ollama installed at {binary}")
    else:
        warn("Ollama still not on PATH — you may need to open a new terminal")
        info("Download page (free): https://ollama.com/download")
    return binary


def start_ollama(binary: str) -> bool:
    """Start ``ollama serve`` in the background and wait for it to answer."""
    if ollama_is_running():
        ok("Ollama server already running")
        return True
    info("starting the Ollama server…")
    try:
        creation = 0
        if IS_WINDOWS:
            creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
                subprocess, "DETACHED_PROCESS", 0
            )
            subprocess.Popen([binary, "serve"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=creation)
        else:
            subprocess.Popen([binary, "serve"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception as exc:
        warn(f"could not start Ollama automatically ({exc})")
        return False

    for _ in range(40):
        if ollama_is_running():
            ok("Ollama server is up")
            return True
        time.sleep(1)
    warn("Ollama did not answer in time — start it yourself with 'ollama serve'")
    return False


def installed_models() -> List[str]:
    """Names of the models Ollama already has locally."""
    payload = http_get(f"{OLLAMA_HOST}/api/tags", timeout=5)
    if payload is None:
        return []
    try:
        data = json.loads(payload.decode("utf-8"))
        return [str(item.get("name", "")) for item in data.get("models", [])]
    except Exception:
        return []


def pull_model_http(model: str) -> bool:
    """Download a model through the Ollama HTTP API.

    Used when the server is reachable but the ``ollama`` command is not on
    PATH — for instance the macOS app, a Docker container, or a machine on the
    LAN pointed at by ``JARVIS_OLLAMA_HOST``.

    Args:
        model: The model tag to pull.

    Returns:
        True when the download finished successfully.
    """
    payload = json.dumps({"name": model, "stream": True}).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_HOST}/api/pull", data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "JARVIS-installer"},
    )
    try:
        with urllib.request.urlopen(request, timeout=7200) as response:
            for raw in response:
                try:
                    message = json.loads(raw.decode("utf-8"))
                except Exception:
                    continue
                if message.get("error"):
                    clear_progress()
                    info(f"Ollama said: {message['error']}")
                    return False
                total, done = message.get("total"), message.get("completed")
                status = str(message.get("status", ""))
                if isinstance(total, int) and isinstance(done, int) and total:
                    progress(f"{status} {done * 100 // total}%")
                elif status:
                    progress(status)
        clear_progress()
        return True
    except Exception as exc:
        clear_progress()
        info(f"the HTTP pull failed: {exc}")
        return False


def pull_model(binary: str, model: str, required: bool = True) -> bool:
    """Download a model unless it is already present.

    Args:
        binary: Path to the ``ollama`` command, or ``""`` to use the HTTP API.
        model: The model tag to pull.
        required: Whether a failure deserves a warning in the summary.

    Returns:
        True when the model is available locally afterwards.
    """
    have = installed_models()
    if any(name == model or name.startswith(f"{model}:") for name in have):
        ok(f"model '{model}' already downloaded")
        return True
    print(f"  {Colour.BOLD}pulling {model}{Colour.RESET} — this is the big one, "
          f"grab a coffee")
    code = run_live([binary, "pull", model], timeout=7200) if binary else (
        0 if pull_model_http(model) else 1
    )
    if code == 0:
        ok(f"model '{model}' ready")
        return True
    if required:
        warn(f"could not download '{model}' — run 'ollama pull {model}' when convenient")
    else:
        info(f"optional model '{model}' was not downloaded")
    return False


def setup_ollama(assume_yes: bool, model: str, want_embed: bool,
                 want_vision: bool) -> bool:
    """Install Ollama if needed, start it, and pull the requested models.

    Returns:
        True when the main model is downloaded and ready to answer.
    """
    binary = find_ollama()
    running = ollama_is_running()
    if binary:
        ok(f"Ollama found at {binary}")
    elif running:
        ok(f"an Ollama server is already answering at {OLLAMA_HOST}")
    else:
        binary = install_ollama(assume_yes)
    if not binary and not running:
        return False

    if binary and not start_ollama(binary):
        return False

    if not model:
        info("model download skipped — run 'ollama pull llama3.2' when you are ready")
        return False

    ready = pull_model(binary, model)
    if want_embed:
        pull_model(binary, EMBED_MODEL, required=False)
    if want_vision:
        pull_model(binary, VISION_MODEL, required=False)
    return ready


def install_piper_voice(assume_yes: bool) -> bool:
    """Download a free offline Piper voice so speech needs no network.

    Args:
        assume_yes: Skip the question and download.

    Returns:
        True when a voice model is present afterwards.
    """
    folder = PROJECT_DIR / "data" / "piper"
    existing = list(folder.glob("*.onnx")) if folder.exists() else []
    if existing:
        ok(f"offline voice already installed ({existing[0].name})")
        return True
    if not ask_yes_no(
        "Download a fully offline voice so speech never touches the internet (~65 MB)?",
        default=True, assume_yes=assume_yes,
    ):
        info("skipped — JARVIS will use Microsoft's free online voices instead")
        return False

    folder.mkdir(parents=True, exist_ok=True)
    model = folder / f"{PIPER_VOICE_NAME}.onnx"
    config_file = folder / f"{PIPER_VOICE_NAME}.onnx.json"
    if not download(f"{PIPER_VOICE_BASE}{PIPER_VOICE_NAME}.onnx", model,
                    "downloading the offline voice"):
        return False
    if not download(f"{PIPER_VOICE_BASE}{PIPER_VOICE_NAME}.onnx.json", config_file,
                    "downloading the voice config"):
        return False
    ok(f"offline voice installed ({PIPER_VOICE_NAME})")
    return True


# ---------------------------------------------------------------------------
# Step 5 — configuration
# ---------------------------------------------------------------------------


def _set_yaml_value(block: str, key: str, value: str) -> str:
    """Replace one ``key: value`` line inside a YAML block, keeping its comment.

    Args:
        block: The text of a top-level block (e.g. everything under ``user:``).
        key: The key to rewrite.
        value: The new value, always quoted.

    Returns:
        The block with the first matching key updated.
    """
    pattern = rf'(?m)^([ \t]*{re.escape(key)}:[ \t]*)(?:"[^"]*"|\'[^\']*\'|[^#\n]*?)([ \t]*(?:#.*)?)$'
    return re.sub(pattern, lambda match: f'{match.group(1)}"{value}"{match.group(2)}',
                  block, count=1)


def personalise_config(name: str, title: str, model: str) -> None:
    """Write the user's name, title and model choice into ``config.yaml``."""
    config_path = PROJECT_DIR / "config.yaml"
    if not config_path.exists():
        warn("config.yaml is missing — JARVIS will fall back to built-in defaults")
        return
    try:
        text = config_path.read_text(encoding="utf-8")
        original = text

        # Only touch the first "user:" block, never anything else.
        user_block = re.search(r"(?m)^user:\n(?:[ \t]+[^\n]*\n?)*", text)
        if user_block:
            block = user_block.group(0)
            if name:
                block = _set_yaml_value(block, "name", name)
            block = _set_yaml_value(block, "title", title)
            text = text[: user_block.start()] + block + text[user_block.end():]

        if model or OLLAMA_HOST != "http://localhost:11434":
            llm_block = re.search(r"(?m)^llm:\n(?:[ \t]+[^\n]*\n?)*", text)
            if llm_block:
                block = llm_block.group(0)
                if model:
                    block = _set_yaml_value(block, "model", model)
                if OLLAMA_HOST != "http://localhost:11434":
                    block = _set_yaml_value(block, "host", OLLAMA_HOST)
                text = text[: llm_block.start()] + block + text[llm_block.end():]

        if text != original:
            config_path.write_text(text, encoding="utf-8")
            ok(f"config.yaml personalised — name: {name or 'unchanged'}, "
               f"model: {model or 'unchanged'}")
        else:
            ok("config.yaml left as it is")
    except Exception as exc:
        warn(f"could not edit config.yaml ({exc}) — edit it by hand if you like")


def create_directories(python: Path) -> None:
    """Create the data/logs/notes folders declared in the configuration."""
    code = (
        "from core.config import Config; "
        "c = Config.load('config.yaml'); c.ensure_directories(); "
        "print('directories ready')"
    )
    result = run([str(python), "-c", code], timeout=180)
    if result.returncode == 0:
        ok("data, logs, notes and cache folders created")
    else:
        for folder in ("data", "logs", "data/notes", "data/code", "data/screenshots"):
            (PROJECT_DIR / folder).mkdir(parents=True, exist_ok=True)
        ok("data and logs folders created")


# ---------------------------------------------------------------------------
# Step 6 — shortcuts
# ---------------------------------------------------------------------------


def create_shortcut() -> None:
    """Create a desktop / Start-menu entry that launches JARVIS."""
    try:
        if IS_WINDOWS:
            _shortcut_windows()
        elif IS_MACOS:
            _shortcut_macos()
        else:
            _shortcut_linux()
    except Exception as exc:  # pragma: no cover - cosmetic feature
        warn(f"could not create a shortcut ({exc})", remember=False)


def _shortcut_windows() -> None:
    """Create ``JARVIS.lnk`` on the desktop and in the Start menu."""
    target = PROJECT_DIR / "scripts" / "jarvis.bat"
    desktop = Path(os.path.expanduser("~")) / "Desktop"
    start_menu = Path(os.environ.get("APPDATA", "")) / (
        r"Microsoft\Windows\Start Menu\Programs"
    )
    script_lines = [
        "$shell = New-Object -ComObject WScript.Shell",
    ]
    for folder in (desktop, start_menu):
        if not folder.exists():
            continue
        link = folder / "JARVIS.lnk"
        script_lines += [
            f'$s = $shell.CreateShortcut("{link}")',
            '$s.TargetPath = "cmd.exe"',
            f'$s.Arguments = \'/k "{target}" --cli\'',
            f'$s.WorkingDirectory = "{PROJECT_DIR}"',
            '$s.IconLocation = "%SystemRoot%\\System32\\shell32.dll,13"',
            '$s.Description = "JARVIS local AI assistant"',
            "$s.Save()",
        ]
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                  "; ".join(script_lines)], timeout=120)
    if result.returncode == 0:
        ok("shortcut added to your desktop and Start menu")
    else:
        warn("could not create the Windows shortcut", remember=False)


def _shortcut_macos() -> None:
    """Create a double-clickable ``JARVIS.command`` on the desktop."""
    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        return
    launcher = desktop / "JARVIS.command"
    launcher.write_text(
        "#!/bin/bash\n"
        f'cd "{PROJECT_DIR}" || exit 1\n'
        'exec ./scripts/jarvis.sh --cli\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    ok(f"double-clickable launcher created: {launcher}")


def _shortcut_linux() -> None:
    """Create a ``.desktop`` entry in the applications menu."""
    applications = Path.home() / ".local" / "share" / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=JARVIS\n"
        "Comment=Free, local AI assistant\n"
        f"Exec=bash -c 'cd \"{PROJECT_DIR}\" && ./scripts/jarvis.sh --cli; exec bash'\n"
        f"Path={PROJECT_DIR}\n"
        "Icon=utilities-terminal\n"
        "Terminal=true\n"
        "Categories=Utility;Development;\n"
    )
    target = applications / "jarvis.desktop"
    target.write_text(entry, encoding="utf-8")
    target.chmod(0o755)
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        copy = desktop / "jarvis.desktop"
        copy.write_text(entry, encoding="utf-8")
        copy.chmod(0o755)
    ok("JARVIS added to your applications menu")


def make_launchers_executable() -> None:
    """Ensure the shell launchers are executable after a ZIP download."""
    if IS_WINDOWS:
        return
    for script in ("setup.sh", "install.sh", "install.command",
                   "scripts/jarvis.sh",
                   "scripts/install_service_linux.sh",
                   "scripts/install_service_macos.sh"):
        path = PROJECT_DIR / script
        if path.exists():
            try:
                path.chmod(path.stat().st_mode | 0o111)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Step 7 — verification and summary
# ---------------------------------------------------------------------------


def self_test(python: Path) -> bool:
    """Run ``main.py --test`` and report whether it succeeded."""
    print()
    code = run_live([str(python), "main.py", "--test"], timeout=900)
    return code == 0


def final_summary(started: float, model: str, profile: str) -> None:
    """Print the closing instructions."""
    minutes, seconds = divmod(int(time.time() - started), 60)
    activate = r".venv\Scripts\activate" if IS_WINDOWS else "source .venv/bin/activate"
    runner = r".venv\Scripts\python" if IS_WINDOWS else ".venv/bin/python"

    print(f"\n{Colour.GREEN}{Colour.BOLD}{'─' * 70}{Colour.RESET}")
    print(f"{Colour.GREEN}{Colour.BOLD}  JARVIS is installed.{Colour.RESET} "
          f"({profile} profile, {minutes}m {seconds}s)")
    print(f"{Colour.GREEN}{Colour.BOLD}{'─' * 70}{Colour.RESET}\n")

    print(f"  {Colour.BOLD}Start it{Colour.RESET}")
    print(f"    {Colour.BLUE}{runner} main.py{Colour.RESET}"
          f"              voice if a mic is available, else text")
    print(f"    {Colour.BLUE}{runner} main.py --cli{Colour.RESET}"
          f"        text interface")
    print(f"    {Colour.BLUE}{runner} main.py --web{Colour.RESET}"
          f"        chat from your phone on the same Wi-Fi")
    print(f"    {Colour.BLUE}{runner} main.py --say \"what time is it\"{Colour.RESET}")
    if IS_WINDOWS:
        print(f"    {Colour.BLUE}scripts\\jarvis.bat{Colour.RESET}"
              f"                or just double-click the JARVIS desktop icon")
    else:
        print(f"    {Colour.BLUE}./scripts/jarvis.sh{Colour.RESET}"
              f"               starts Ollama too")
    print(f"    {Colour.DIM}(inside an activated shell — {activate} — plain "
          f"'python main.py' works){Colour.RESET}")

    print(f"\n  {Colour.BOLD}First things to say{Colour.RESET}")
    for line in (
        '"what time is it"              "how\'s the weather"',
        '"set a timer for 10 minutes"   "add buy milk to my todos"',
        '"write a python script that renames files by date"',
        '"search github for a qr code library"   "show me your own code map"',
    ):
        print(f"    {line}")

    print(f"\n  {Colour.BOLD}Good to know{Colour.RESET}")
    print(f"    · Model in use: {model} — change it in config.yaml (llm.model)")
    print("    · Everything runs on this machine. No keys, no accounts, no bills.")
    print("    · Ollama must be running: it starts on login, or run 'ollama serve'.")
    if profile != "full":
        print("    · Voice mode needs the full profile: rerun 'python install.py --full'")

    if WARNINGS:
        print(f"\n  {Colour.YELLOW}{Colour.BOLD}Warnings{Colour.RESET}")
        for message in WARNINGS:
            print(f"    {Colour.YELLOW}!{Colour.RESET} {message}")
        print("    Everything else still works — these only disable single features.")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse the installer's command line."""
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Install JARVIS — the free, fully local AI assistant.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python3 install.py                 interactive install\n"
            "  python3 install.py --yes           no questions, sensible defaults\n"
            "  python3 install.py --minimal       text only, ~120 MB\n"
            "  python3 install.py --repair        reinstall packages, keep everything else\n"
        ),
    )
    profile = parser.add_mutually_exclusive_group()
    profile.add_argument("--full", action="store_const", dest="profile", const="full",
                         help="voice, vision, documents, desktop control (default)")
    profile.add_argument("--standard", action="store_const", dest="profile", const="standard",
                         help="everything except the microphone stack")
    profile.add_argument("--minimal", action="store_const", dest="profile", const="minimal",
                         help="text and web only, smallest install")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="accept every default without asking")
    parser.add_argument("--model", default="", help=f"model to pull (default: {DEFAULT_MODEL})")
    parser.add_argument("--no-ollama", action="store_true",
                        help="do not install or start the LLM engine")
    parser.add_argument("--no-model", action="store_true", help="skip the model download")
    parser.add_argument("--no-test", action="store_true", help="skip the closing self-test")
    parser.add_argument("--no-shortcut", action="store_true", help="do not create a shortcut")
    parser.add_argument("--vision", action="store_true", help="also pull the llava vision model")
    parser.add_argument("--no-voice-model", action="store_true",
                        help="skip the offline Piper voice download")
    parser.add_argument("--venv", default=str(PROJECT_DIR / ".venv"),
                        help="virtual environment location (default: ./.venv)")
    parser.add_argument("--recreate", action="store_true",
                        help="delete and rebuild the virtual environment")
    parser.add_argument("--repair", action="store_true",
                        help="reinstall packages only (implies --yes)")
    parser.set_defaults(profile=None)
    return parser.parse_args(list(argv) if argv is not None else None)


def choose_profile(assume_yes: bool) -> str:
    """Ask which profile to install."""
    if assume_yes or not sys.stdin.isatty():
        return "full"
    print("  Which install would you like?\n")
    for index, key in enumerate(("full", "standard", "minimal"), start=1):
        print(f"    {Colour.BOLD}{index}){Colour.RESET} {key:<9} "
              f"{PROFILE_BLURB[key]}  {Colour.DIM}{PROFILE_SIZE[key]}{Colour.RESET}")
    print()
    answer = ask("Choose 1, 2 or 3", "1")
    return {"1": "full", "2": "standard", "3": "minimal"}.get(answer.strip(), "full")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the installer end to end.

    Returns:
        Process exit status: 0 on success, 1 when a required step failed.
    """
    arguments = parse_arguments(argv)
    assume_yes = arguments.yes or arguments.repair
    enable_colour()
    banner()

    started = time.time()
    total_steps = 7

    step(1, total_steps, "Checking your system")
    if not check_environment():
        return 1

    profile = arguments.profile or ("standard" if arguments.repair else None)
    if profile is None:
        print()
        profile = choose_profile(assume_yes)
    ok(f"profile: {profile} — {PROFILE_BLURB[profile]}")

    step(2, total_steps, "Setting up the Python environment")
    python = create_venv(Path(arguments.venv), recreate=arguments.recreate)
    if python is None:
        return 1
    upgrade_pip(python)

    step(3, total_steps, f"Installing packages ({PROFILE_SIZE[profile]} download)")
    if not install_packages(python, profile):
        fail("essential packages could not be installed — see the errors above.")
        info("Try again with:  python install.py --minimal")
        return 1

    model = arguments.model or suggest_model()
    model_installed = ""
    step(4, total_steps, "Local language model (Ollama)")
    if arguments.no_ollama:
        info("skipped (--no-ollama)")
    else:
        wants_vision = bool(arguments.vision) or (
            profile == "full"
            and not arguments.no_model
            and ask_yes_no("Also download the vision model (llava, ~4 GB)?",
                           default=False, assume_yes=assume_yes)
        )
        if setup_ollama(
            assume_yes=assume_yes,
            model="" if arguments.no_model else model,
            want_embed=profile != "minimal" and not arguments.no_model,
            want_vision=wants_vision and not arguments.no_model,
        ):
            model_installed = model

    if profile == "full" and not arguments.no_voice_model:
        install_piper_voice(assume_yes)

    step(5, total_steps, "Configuration")
    if arguments.repair:
        ok("configuration left untouched (--repair)")
    else:
        default_name = os.environ.get("USER") or os.environ.get("USERNAME") or ""
        name = default_name if assume_yes else ask("What should JARVIS call you?", default_name)
        title = "sir" if assume_yes else ask(
            'And how should it address you — "sir", "ma\'am", "boss" or blank for none', "sir"
        )
        personalise_config(name.strip(), title.strip(), model_installed)
    create_directories(python)
    make_launchers_executable()

    step(6, total_steps, "Shortcuts")
    if arguments.no_shortcut:
        info("skipped (--no-shortcut)")
    elif ask_yes_no("Add a JARVIS shortcut to your desktop?", default=True,
                    assume_yes=assume_yes):
        create_shortcut()
    else:
        info("no shortcut created")

    step(7, total_steps, "Checking every component")
    if arguments.no_test:
        info("skipped (--no-test)")
    elif not self_test(python):
        warn("the self-test reported problems — read the lines above")

    final_summary(started, model_installed or model, profile)

    if not assume_yes and sys.stdin.isatty():
        if ask_yes_no("Start JARVIS now?", default=True):
            print()
            run_live([str(python), "main.py", "--cli"], timeout=86400)
        elif IS_WINDOWS:
            input("  Press Enter to close this window…")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(f"\n\n  {Colour.YELLOW}Installation cancelled.{Colour.RESET} "
              f"Rerun 'python install.py' whenever you like — it picks up where it left off.\n")
        raise SystemExit(130)
