# /utils/helpers.py
"""Small, dependency-light helpers shared across the whole JARVIS codebase."""

from __future__ import annotations

import asyncio
import functools
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple, TypeVar

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Platform
# ---------------------------------------------------------------------------


def detect_os() -> str:
    """Return a normalised OS name: ``windows``, ``macos``, ``linux`` or ``unknown``."""
    system = platform.system().lower()
    if system.startswith("win"):
        return "windows"
    if system == "darwin":
        return "macos"
    if system == "linux":
        return "linux"
    return "unknown"


IS_WINDOWS = detect_os() == "windows"
IS_MACOS = detect_os() == "macos"
IS_LINUX = detect_os() == "linux"


def is_wsl() -> bool:
    """Return True when running inside Windows Subsystem for Linux."""
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except Exception:
        return False


def has_display() -> bool:
    """Return True when a GUI session appears to be available."""
    if IS_WINDOWS or IS_MACOS:
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def which(binary: str) -> Optional[str]:
    """Locate an executable on PATH (thin :func:`shutil.which` wrapper)."""
    return shutil.which(binary)


def ssl_verify() -> Any:
    """Return the TLS verification setting for HTTP clients.

    Honours ``SSL_CERT_FILE`` / ``REQUESTS_CA_BUNDLE`` / ``CURL_CA_BUNDLE`` and
    falls back to the system CA bundle when ``certifi`` is missing. This keeps
    JARVIS working behind TLS-inspecting proxies. Verification is never
    disabled.

    Returns:
        ``True`` for the library default, or a path to a CA bundle.
    """
    for variable in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        candidate = os.environ.get(variable, "").strip()
        if candidate and Path(candidate).exists():
            return candidate
    try:
        import certifi

        if Path(certifi.where()).exists():
            return True
    except Exception:
        pass
    for bundle in (
        "/etc/ssl/certs/ca-certificates.crt",   # Debian/Ubuntu
        "/etc/pki/tls/certs/ca-bundle.crt",     # Fedora/RHEL
        "/etc/ssl/cert.pem",                    # macOS/BSD
    ):
        if Path(bundle).exists():
            return bundle
    return True


# ---------------------------------------------------------------------------
# Async plumbing
# ---------------------------------------------------------------------------


async def run_blocking(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a blocking callable in the default thread pool.

    Args:
        func: Any synchronous callable.
        *args: Positional arguments for ``func``.
        **kwargs: Keyword arguments for ``func``.

    Returns:
        Whatever ``func`` returns.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


async def with_timeout(
    awaitable: Awaitable[T], seconds: float, default: Optional[T] = None
) -> Optional[T]:
    """Await ``awaitable`` but return ``default`` if it exceeds ``seconds``."""
    try:
        return await asyncio.wait_for(awaitable, timeout=seconds)
    except asyncio.TimeoutError:
        return default
    except Exception:
        return default


async def run_command(
    command: Sequence[str] | str,
    timeout: float = 30.0,
    cwd: Optional[str] = None,
    shell: bool = False,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[int, str, str]:
    """Run a subprocess asynchronously with a hard timeout.

    Args:
        command: Argument list, or a string when ``shell`` is True.
        timeout: Seconds before the process group is killed.
        cwd: Working directory.
        shell: Execute through the system shell.
        env: Extra environment variables (merged over ``os.environ``).

    Returns:
        ``(returncode, stdout, stderr)``. Return code ``-9`` means timeout.
    """
    merged_env = {**os.environ, **(env or {})}
    try:
        if shell or isinstance(command, str):
            cmd_str = command if isinstance(command, str) else " ".join(command)
            proc = await asyncio.create_subprocess_shell(
                cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=merged_env,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=merged_env,
            )
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except Exception as exc:  # pragma: no cover - OS specific
        return 1, "", str(exc)

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return -9, "", f"Command timed out after {timeout:.0f}s"

    return (
        proc.returncode or 0,
        (stdout or b"").decode("utf-8", errors="replace").strip(),
        (stderr or b"").decode("utf-8", errors="replace").strip(),
    )


def run_command_sync(
    command: Sequence[str] | str, timeout: float = 30.0, shell: bool = False
) -> Tuple[int, str, str]:
    """Blocking variant of :func:`run_command` for setup/CLI paths."""
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout,
            shell=shell or isinstance(command, str),
            text=True,
        )
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return -9, "", f"Command timed out after {timeout:.0f}s"
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except Exception as exc:
        return 1, "", str(exc)


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------


def truncate(text: str, limit: int = 500, suffix: str = "…") -> str:
    """Trim ``text`` to ``limit`` characters, appending ``suffix`` when cut."""
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))].rstrip() + suffix


def clean_text(text: str) -> str:
    """Collapse whitespace and normalise unicode for LLM/TTS friendliness."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_markdown(text: str) -> str:
    """Remove markdown decorations so TTS does not read asterisks aloud."""
    if not text:
        return ""
    text = re.sub(r"```[\s\S]*?```", " (code block omitted) ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"(\*\*|__|\*|_|~~)", "", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    return clean_text(text)


def sentence_chunks(text: str, max_chars: int = 900) -> List[str]:
    """Split text into <= ``max_chars`` chunks on sentence boundaries."""
    text = clean_text(text)
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            while len(sentence) > max_chars:
                chunks.append(sentence[:max_chars])
                sentence = sentence[max_chars:]
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def slugify(text: str, max_length: int = 60) -> str:
    """Turn arbitrary text into a safe lowercase filename slug."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    return (text or "untitled")[:max_length].strip("-") or "untitled"


def extract_json(text: str) -> Optional[Any]:
    """Best-effort extraction of a JSON object/array from noisy LLM output.

    Handles ```json fences, leading prose, trailing commentary and single
    quotes. Returns ``None`` when nothing parseable is found.
    """
    if not text:
        return None
    candidate = text.strip()

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", candidate, re.IGNORECASE)
    if fence:
        candidate = fence.group(1).strip()

    try:
        return json.loads(candidate)
    except Exception:
        pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(candidate)):
            char = candidate[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    blob = candidate[start : index + 1]
                    try:
                        return json.loads(blob)
                    except Exception:
                        try:
                            return json.loads(blob.replace("'", '"'))
                        except Exception:
                            break
    return None


def extract_code_blocks(text: str) -> List[Tuple[str, str]]:
    """Return ``(language, code)`` pairs for every fenced block in ``text``."""
    if not text:
        return []
    blocks = re.findall(r"```([\w+#.-]*)\n([\s\S]*?)```", text)
    return [(lang.strip().lower() or "text", code.rstrip()) for lang, code in blocks]


def similar(a: str, b: str) -> float:
    """Cheap token-overlap similarity in ``[0, 1]`` (no extra dependencies)."""
    tokens_a = set(re.findall(r"\w+", (a or "").lower()))
    tokens_b = set(re.findall(r"\w+", (b or "").lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def human_bytes(num: float) -> str:
    """Format a byte count as a human readable string."""
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(num) < 1024.0:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} EB"


def human_duration(seconds: float) -> str:
    """Format a duration in seconds as ``2h 5m 3s``."""
    seconds = int(max(0, seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts: List[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def now_iso() -> str:
    """Current local time as an ISO-8601 string (second precision)."""
    return datetime.now().replace(microsecond=0).isoformat()


def friendly_time(dt: Optional[datetime] = None) -> str:
    """Human friendly clock string, e.g. ``Friday 05 September, 14:32``."""
    dt = dt or datetime.now()
    return dt.strftime("%A %d %B %Y, %H:%M")


def parse_duration(text: str) -> Optional[int]:
    """Parse ``"10 minutes"``, ``"1h30m"``, ``"90s"`` into seconds.

    Returns:
        Number of seconds, or ``None`` when nothing recognisable is found.
    """
    if not text:
        return None
    text = text.lower().strip()
    total = 0
    found = False

    for value, unit in re.findall(
        r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s|days?|d)"
        r"(?![a-z])",
        text,
    ):
        found = True
        amount = float(value)
        if unit.startswith(("hour", "hr", "h")):
            total += amount * 3600
        elif unit.startswith(("day", "d")):
            total += amount * 86400
        elif unit.startswith(("min", "m")):
            total += amount * 60
        else:
            total += amount
    if found:
        return int(total)

    bare = re.fullmatch(r"(\d+(?:\.\d+)?)", text)
    if bare:
        return int(float(bare.group(1)) * 60)  # bare numbers mean minutes
    return None


def parse_when(text: str, reference: Optional[datetime] = None) -> Optional[datetime]:
    """Parse a loose time expression into an absolute ``datetime``.

    Understands ``in 10 minutes``, ``at 5pm``, ``tomorrow at 09:30``,
    ``2026-09-05 14:00`` and bare clock times.

    Args:
        text: Free-form time expression.
        reference: "Now" for relative expressions (defaults to current time).

    Returns:
        A future ``datetime`` when parsing succeeds, else ``None``.
    """
    if not text:
        return None
    reference = reference or datetime.now()
    lowered = text.lower().strip()

    relative = re.search(r"\bin\s+(.+)", lowered)
    if relative:
        seconds = parse_duration(relative.group(1))
        if seconds:
            return reference + timedelta(seconds=seconds)

    day_offset = 0
    if "tomorrow" in lowered:
        day_offset = 1
    elif "tonight" in lowered:
        day_offset = 0

    clock = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lowered)
    if clock:
        hour = int(clock.group(1)) % 12
        minute = int(clock.group(2) or 0)
        if clock.group(3) == "pm":
            hour += 12
        target = (reference + timedelta(days=day_offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if target <= reference:
            target += timedelta(days=1)
        return target

    iso_like = re.search(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}):(\d{2}))?", lowered)
    if iso_like:
        try:
            date_part = datetime.strptime(iso_like.group(1), "%Y-%m-%d")
            hour = int(iso_like.group(2) or 9)
            minute = int(iso_like.group(3) or 0)
            return date_part.replace(hour=hour, minute=minute)
        except Exception:
            pass

    hhmm = re.search(r"\b(\d{1,2}):(\d{2})\b", lowered)
    if hhmm:
        hour, minute = int(hhmm.group(1)), int(hhmm.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            target = (reference + timedelta(days=day_offset)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if target <= reference:
                target += timedelta(days=1)
            return target

    try:  # optional, nicer parsing when python-dateutil is installed
        from dateutil import parser as date_parser  # type: ignore

        parsed = date_parser.parse(text, fuzzy=True, default=reference)
        if parsed <= reference:
            parsed += timedelta(days=1)
        return parsed
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------


def ensure_dir(path: str | Path) -> Path:
    """Create ``path`` (and parents) if missing and return it as a ``Path``."""
    directory = Path(path).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def expand_path(path: str | Path) -> Path:
    """Expand ``~``, environment variables and resolve to an absolute path."""
    return Path(os.path.expandvars(str(path))).expanduser().resolve()


def resolve_user_path(text: str) -> Path:
    """Resolve friendly folder names (``desktop``, ``downloads``, ``~/x``)."""
    raw = (text or "").strip().strip("\"'")
    lowered = raw.lower()
    home = Path.home()
    shortcuts = {
        "": home,
        ".": Path.cwd(),
        "here": Path.cwd(),
        "home": home,
        "~": home,
        "desktop": home / "Desktop",
        "my desktop": home / "Desktop",
        "downloads": home / "Downloads",
        "download": home / "Downloads",
        "documents": home / "Documents",
        "docs": home / "Documents",
        "pictures": home / "Pictures",
        "photos": home / "Pictures",
        "music": home / "Music",
        "videos": home / "Videos",
    }
    if lowered in shortcuts:
        return shortcuts[lowered]
    return expand_path(raw)


def safe_filename(name: str, extension: str = "") -> str:
    """Build a filesystem-safe filename, optionally forcing an extension."""
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "untitled").strip(" .") or "untitled"
    if extension and not stem.lower().endswith(extension.lower()):
        stem = f"{stem}{extension}"
    return stem[:200]


def read_text_file(path: str | Path, limit: int = 200_000) -> str:
    """Read a text file defensively, tolerating odd encodings."""
    file_path = Path(path)
    try:
        return file_path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        try:
            return file_path.read_bytes()[:limit].decode("latin-1", errors="replace")
        except Exception:
            return ""


def bullet_list(items: Sequence[str], bullet: str = "•", limit: int = 20) -> str:
    """Render a bullet list, capped at ``limit`` entries."""
    rows = [f"{bullet} {item}" for item in list(items)[:limit]]
    remaining = max(0, len(items) - limit)
    if remaining:
        rows.append(f"{bullet} …and {remaining} more")
    return "\n".join(rows)


def python_executable() -> str:
    """Return the interpreter to use for sandboxed code execution."""
    return sys.executable or "python3"
