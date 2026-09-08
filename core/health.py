# /core/health.py
"""Offline health probes for the nightly self-check.

Every night the assistant quietly asks "is everything I depend on still
alive?" — and does it *without* a model, a microphone or a network call to
any third party. The answers are written to a small JSON file
(``assistant.health_file``) that the next morning briefing reads, so an
offline Ollama or a vanished Blender install shows up at breakfast instead
of failing halfway through the first request.

Probes deliberately degrade to ``ok`` when they cannot be answered: a check
that cannot run must not become a false alarm in the morning brief.
"""

from __future__ import annotations

import json
import shutil
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("core.health")


def _health_path(config: Any) -> Path:
    """Resolve ``assistant.health_file`` against the config root when possible.

    Args:
        config: The global configuration (or a plain dict in tests).

    Returns:
        The absolute-ish path of the health file.
    """
    raw = str(config.get("assistant.health_file", "data/health.json") or "")
    resolve = getattr(config, "resolve", None)
    if callable(resolve):
        return resolve(raw)
    return Path(raw).expanduser()


def _probe_ollama(host: str, timeout: float = 3.0) -> Dict[str, Any]:
    """Is Ollama reachable at ``host``?

    Args:
        host: Base URL from ``llm.host``.
        timeout: Seconds before giving up.

    Returns:
        ``{"ok": bool, "detail": str}``.
    """
    url = str(host or "").rstrip("/")
    if not url:
        return {"ok": False, "detail": "no llm.host configured"}
    try:
        from httpx import get as httpx_get

        response = httpx_get(f"{url}/api/tags", timeout=timeout)
        return {"ok": response.status_code == 200, "detail": f"HTTP {response.status_code}"}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def _probe_port(host: str, port: int, timeout: float = 2.0) -> Dict[str, Any]:
    """Is something listening on ``host:port``?

    Args:
        host: Hostname or IP.
        port: TCP port.
        timeout: Connect timeout in seconds.

    Returns:
        ``{"ok": bool, "detail": str}``.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"ok": True, "detail": f"listening on {host}:{port}"}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def _probe_blender() -> Dict[str, Any]:
    """Find a Blender executable on PATH (or the usual suspects).

    Returns:
        ``{"ok": bool, "detail": str}``.
    """
    found = shutil.which("blender")
    if found:
        return {"ok": True, "detail": str(found)}
    # macOS / Windows common install locations, looked up lazily so this
    # module imports cleanly on machines without any of them.
    candidates: list[str] = []
    if sys.platform == "darwin":
        candidates = [
            "/Applications/Blender.app/Contents/MacOS/Blender",
            str(Path.home() / "Applications/Blender.app/Contents/MacOS/Blender"),
        ]
    elif sys.platform == "win32":
        candidates = [
            str(Path.home() / "AppData/Roaming/Blender Foundation/Blender"),
        ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return {"ok": True, "detail": str(path)}
    return {"ok": False, "detail": "blender not found on PATH"}


def _probe_microphone(timeout: float = 2.0) -> Dict[str, Any]:
    """Can the OS enumerate an input device?

    Returns:
        ``{"ok": bool, "detail": str}`` — ``ok`` is True when sounddevice
        cannot be imported either, because that means voice input is simply
        not part of this install and there is nothing to fix.
    """
    try:
        import sounddevice as sd  # type: ignore[import-not-found]
    except Exception:
        return {"ok": True, "detail": "sounddevice not installed (voice off)"}
    try:
        devices = sd.query_devices()
        has_input = any(
            device.get("max_input_channels", 0) > 0 for device in devices
        )
        return {
            "ok": has_input,
            "detail": "no input device found" if not has_input else "input device found",
        }
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def _probe_wake_word(config: Any) -> Dict[str, Any]:
    """Is the wake-word engine importable when one is configured?

    Returns:
        ``{"ok": bool, "detail": str}``. Disabled wake word is always fine.
    """
    engine = str(config.get("voice.wake_word", "") or "").lower().strip()
    if not engine or engine in ("jarvis", "off", "false"):
        return {"ok": True, "detail": f"wake word: {engine or 'disabled'}"}
    try:
        if engine == "openwakeword":
            import openwakeword  # noqa: F401  (import test only)
        elif engine == "porcupine":
            import pvporcupine  # noqa: F401  (import test only)
        else:
            return {"ok": True, "detail": f"wake word engine '{engine}' unknown; skipped"}
        return {"ok": True, "detail": f"{engine} importable"}
    except Exception as exc:
        return {"ok": False, "detail": f"{engine} missing: {exc}"}


def run_probes(config: Any) -> Dict[str, str]:
    """Run every cheap offline probe and label the results.

    Args:
        config: The global configuration (only ``llm.host``, ``voice.*`` and
            ``blender.executable`` matter).

    Returns:
        ``{service: "ok"|"problem"|"disabled"}``.
    """
    results: Dict[str, str] = {}

    llm_host = str(config.get("llm.host", "http://localhost:11434") or "")
    ollama = _probe_ollama(llm_host)
    results["ollama"] = "ok" if ollama["ok"] else "problem"

    blender = _probe_blender()
    results["blender"] = "ok" if blender["ok"] else "problem"

    voice_on = bool(config.get("voice.enabled", True))
    mic = _probe_microphone()
    results["microphone"] = (
        "disabled" if not voice_on else ("ok" if mic["ok"] else "problem")
    )
    wake = _probe_wake_word(config)
    results["wake_word"] = "ok" if wake["ok"] else "problem"

    if not voice_on:
        results["wake_word"] = "disabled"
    return results


def write_report(config: Any, results: Dict[str, str]) -> Path:
    """Persist a probe report to ``assistant.health_file``.

    Args:
        config: Configuration holding ``assistant.health_file``.
        results: Output of :func:`run_probes`.

    Returns:
        The file that was written.
    """
    path = _health_path(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "time": datetime.now().strftime("%H:%M"),
                    "services": results,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("Health report write failed: %s", exc)
    return path


def read_report(config: Any) -> Optional[Dict[str, Any]]:
    """Return the latest health report, if any.

    Args:
        config: Configuration holding ``assistant.health_file``.

    Returns:
        The report dict, or ``None`` when absent or unreadable.
    """
    try:
        data = json.loads(_health_path(config).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def summarize(report: Optional[Dict[str, Any]]) -> str:
    """Turn a report into one calm spoken sentence.

    Args:
        report: The stored report, or ``None``.

    Returns:
        A human summary mentioning only services that need attention, or an
        all-clear line.
    """
    if not report:
        return "No self-check has run yet."
    services = report.get("services") or {}
    problems = [
        name for name, state in services.items()
        if state == "problem"
    ]
    if not problems:
        return "Nightly self-check: all clear."
    labels = {
        "ollama": "Ollama",
        "blender": "Blender",
        "microphone": "the microphone",
        "wake_word": "the wake word engine",
    }
    named = ", ".join(labels.get(name, name) for name in problems)
    return f"Nightly self-check: {named} {('is' if len(problems) == 1 else 'are')} offline."


def last_report_is_today(report: Optional[Dict[str, Any]], day: str) -> bool:
    """Whether the report dates from the given day.

    Args:
        report: The stored report, or ``None``.
        day: ``YYYY-MM-DD`` to compare against.

    Returns:
        True only when the report is fresh for that day.
    """
    return bool(report and str(report.get("date", "")) == day)


__all__ = [
    "last_report_is_today",
    "read_report",
    "run_probes",
    "summarize",
    "write_report",
]
