# /utils/backup.py
"""Back up, restore and uninstall a JARVIS installation.

Everything JARVIS knows about you lives in a handful of local places: the
SQLite database (todos, reminders, schedules, routines, the file journal), the
ChromaDB memory, your notes and saved code, generated plugins and
``config.yaml``. This module packs those into a single dated zip, puts them
back again, and — when you have had enough — removes the lot.

No cloud, no service: a zip file you can copy to a USB stick.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from utils.helpers import ensure_dir, human_bytes
from utils.logger import get_logger

logger = get_logger("backup")

#: Version stamped into the manifest, so a future format change can be detected.
BACKUP_FORMAT = 1

#: Directories inside the project that hold your data and are worth keeping.
DATA_DIRECTORIES: Tuple[str, ...] = ("data", "notes", "code", "plugins")

#: Things inside those directories that are large and regenerable.
SKIP_PARTS: Tuple[str, ...] = (
    "data/repos",          # cloned git repositories, re-clonable
    "data/piper",          # downloaded TTS voices, re-downloadable
    "data/tts_cache",      # synthesised speech cache
    "data/backups",        # self_improve's own file backups
    "__pycache__",
    ".pytest_cache",
)

#: Individual files worth keeping from the project root.
ROOT_FILES: Tuple[str, ...] = ("config.yaml",)


def _skipped(relative: str) -> bool:
    """Whether a relative path should be left out of a backup.

    Args:
        relative: Path relative to the project root, using forward slashes.

    Returns:
        True when the path is large, regenerable or noise.
    """
    normalised = relative.replace(os.sep, "/")
    for part in SKIP_PARTS:
        if normalised == part or normalised.startswith(part + "/"):
            return True
    return normalised.endswith((".pyc", ".pyo", ".log", ".wal", ".shm"))


def _iter_backup_files(root: Path) -> Iterable[Path]:
    """Yield every file that belongs in a backup.

    Args:
        root: The project root.

    Yields:
        Absolute paths to include.
    """
    for name in ROOT_FILES:
        candidate = root / name
        if candidate.is_file():
            yield candidate
    for directory in DATA_DIRECTORIES:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:  # pragma: no cover - defensive
                continue
            if _skipped(relative):
                continue
            yield path


def _copy_database(source: Path, destination: Path) -> bool:
    """Copy a SQLite database safely, even while JARVIS is using it.

    Args:
        source: The live database file.
        destination: Where to write the snapshot.

    Returns:
        True when the online-backup API produced a consistent copy.
    """
    try:
        ensure_dir(destination.parent)
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as origin, \
                sqlite3.connect(str(destination)) as target:
            origin.backup(target)
        return True
    except Exception as exc:
        logger.debug("Online backup of %s failed (%s); copying the file instead.",
                     source, exc)
        try:
            shutil.copy2(source, destination)
            return False
        except Exception as copy_error:  # pragma: no cover - defensive
            logger.warning("Could not copy %s: %s", source, copy_error)
            return False


def create_backup(root: Path, destination: Optional[Path] = None) -> Dict[str, Any]:
    """Write a dated zip containing everything JARVIS knows.

    Args:
        root: The project root.
        destination: Target ``.zip`` path or a directory. Defaults to
            ``<root>/backups/jarvis-backup-<timestamp>.zip``.

    Returns:
        A summary dict with ``path``, ``files``, ``bytes`` and ``skipped``.
    """
    root = Path(root).resolve()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if destination is None:
        target = root / "backups" / f"jarvis-backup-{stamp}.zip"
    else:
        destination = Path(destination).expanduser()
        target = (destination / f"jarvis-backup-{stamp}.zip"
                  if destination.is_dir() or not destination.suffix
                  else destination)
    ensure_dir(target.parent)

    files = list(_iter_backup_files(root))
    manifest: Dict[str, Any] = {
        "format": BACKUP_FORMAT,
        "created": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "files": [],
    }

    total = 0
    staged: List[Tuple[Path, str, Optional[Path]]] = []
    scratch = target.parent / f".jarvis-backup-{stamp}"
    try:
        for path in files:
            relative = path.relative_to(root).as_posix()
            temporary: Optional[Path] = None
            if path.suffix in (".db", ".sqlite", ".sqlite3"):
                temporary = scratch / relative
                _copy_database(path, temporary)
            staged.append((path, relative, temporary))

        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, relative, temporary in staged:
                source = temporary if temporary and temporary.exists() else path
                try:
                    size = source.stat().st_size
                except Exception:  # pragma: no cover - vanished mid-backup
                    continue
                archive.write(source, relative)
                manifest["files"].append({"path": relative, "bytes": size})
                total += size
            archive.writestr("jarvis-manifest.json", json.dumps(manifest, indent=2))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    logger.info("Backup written to %s (%d files, %s)", target, len(manifest["files"]),
                human_bytes(total))
    return {
        "path": str(target),
        "files": len(manifest["files"]),
        "bytes": total,
        "archive_bytes": target.stat().st_size if target.exists() else 0,
    }


def inspect_backup(archive_path: Path) -> Dict[str, Any]:
    """Read a backup's manifest without extracting anything.

    Args:
        archive_path: The ``.zip`` to inspect.

    Returns:
        The manifest, plus ``ok`` and ``error`` keys.
    """
    try:
        with zipfile.ZipFile(archive_path) as archive, \
                archive.open("jarvis-manifest.json") as handle:
            manifest = json.loads(handle.read().decode("utf-8"))
        manifest["ok"] = True
        manifest["error"] = ""
        return manifest
    except KeyError:
        return {"ok": False, "error": "not a JARVIS backup (no manifest)", "files": []}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "files": []}


def _safe_target(root: Path, member: str) -> Optional[Path]:
    """Resolve an archive member inside ``root``, refusing path escapes.

    Args:
        root: Directory being restored into.
        member: The archive member name.

    Returns:
        The absolute destination, or ``None`` when the member tries to escape.
    """
    if member.startswith("/") or member.startswith("\\") or ".." in Path(member).parts:
        return None
    candidate = (root / member).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def restore_backup(root: Path, archive_path: Path, overwrite: bool = False,
                   dry_run: bool = False) -> Dict[str, Any]:
    """Restore a backup over an installation.

    A safety copy of anything about to be overwritten is taken first, so a
    restore is itself undoable.

    Args:
        root: The project root to restore into.
        archive_path: The backup zip.
        overwrite: Replace files that already exist.
        dry_run: Report what would happen without touching the disk.

    Returns:
        A summary with ``restored``, ``skipped``, ``rejected`` and ``safety``.
    """
    root = Path(root).resolve()
    archive_path = Path(archive_path).expanduser()
    manifest = inspect_backup(archive_path)
    if not manifest.get("ok"):
        return {"ok": False, "error": manifest.get("error", "unreadable backup"),
                "restored": 0, "skipped": 0, "rejected": []}

    restored, skipped = 0, 0
    rejected: List[str] = []
    safety: Optional[str] = None

    with zipfile.ZipFile(archive_path) as archive:
        members = [name for name in archive.namelist()
                   if name != "jarvis-manifest.json" and not name.endswith("/")]

        clashes = []
        for member in members:
            target = _safe_target(root, member)
            if target is None:
                rejected.append(member)
                continue
            if target.exists():
                clashes.append(member)

        if dry_run:
            return {"ok": True, "restored": 0, "skipped": 0, "rejected": rejected,
                    "would_restore": len(members) - len(rejected),
                    "would_overwrite": len(clashes) if overwrite else 0,
                    "clashes": clashes[:20], "created": manifest.get("created", "")}

        if clashes and overwrite:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            safety_path = root / "backups" / f"pre-restore-{stamp}.zip"
            ensure_dir(safety_path.parent)
            with zipfile.ZipFile(safety_path, "w", zipfile.ZIP_DEFLATED) as safe:
                for member in clashes:
                    target = _safe_target(root, member)
                    if target is not None and target.is_file():
                        safe.write(target, member)
            safety = str(safety_path)

        for member in members:
            target = _safe_target(root, member)
            if target is None:
                continue
            if target.exists() and not overwrite:
                skipped += 1
                continue
            ensure_dir(target.parent)
            with archive.open(member) as source, open(target, "wb") as handle:
                shutil.copyfileobj(source, handle)
            restored += 1

    logger.info("Restored %d file(s) from %s (%d skipped)", restored, archive_path, skipped)
    return {"ok": True, "restored": restored, "skipped": skipped, "rejected": rejected,
            "safety": safety, "created": manifest.get("created", "")}


def uninstall_plan(root: Path, keep_data: bool = False) -> List[Dict[str, Any]]:
    """Describe what an uninstall would remove.

    Args:
        root: The project root.
        keep_data: Leave your data (database, memory, notes) in place.

    Returns:
        A list of ``{"path", "bytes", "label"}`` entries, largest first.
    """
    root = Path(root).resolve()
    candidates: List[Tuple[Path, str]] = [
        (root / ".venv", "Python virtual environment"),
        (root / "logs", "log files"),
        (root / "data" / "repos", "cloned repositories"),
        (root / "data" / "piper", "downloaded TTS voices"),
        (root / "data" / "tts_cache", "cached speech"),
    ]
    if not keep_data:
        candidates += [
            (root / "data", "database, memory and knowledge index"),
            (root / "notes", "your notes"),
            (root / "code", "code JARVIS wrote"),
            (root / "plugins", "generated skills"),
        ]

    seen: set[str] = set()
    plan: List[Dict[str, Any]] = []
    for path, label in candidates:
        key = str(path)
        if key in seen or not path.exists():
            continue
        seen.add(key)
        plan.append({"path": key, "label": label, "bytes": _directory_size(path)})
    plan.sort(key=lambda entry: -entry["bytes"])
    return plan


def _directory_size(path: Path) -> int:
    """Total size of a file or directory in bytes, ignoring errors."""
    if path.is_file():
        try:
            return path.stat().st_size
        except Exception:
            return 0
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except Exception:
            continue
    return total


def uninstall(root: Path, keep_data: bool = False,
              remove_services: bool = True) -> Dict[str, Any]:
    """Remove a JARVIS installation's generated state.

    The source tree itself is never deleted — you cloned it, you can delete it.
    Ollama and its models are left alone too; they are a separate program and
    may be in use by something else.

    Args:
        root: The project root.
        keep_data: Keep the database, memory, notes and plugins.
        remove_services: Also unregister the login-time service.

    Returns:
        A summary with ``removed``, ``failed`` and ``bytes``.
    """
    root = Path(root).resolve()
    plan = uninstall_plan(root, keep_data=keep_data)
    removed: List[str] = []
    failed: List[str] = []
    freed = 0

    if remove_services:
        _remove_services(root)

    for entry in plan:
        path = Path(entry["path"])
        try:
            if path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)
            removed.append(entry["path"])
            freed += int(entry["bytes"])
        except Exception as exc:
            logger.warning("Could not remove %s: %s", path, exc)
            failed.append(f"{path}: {exc}")

    return {"removed": removed, "failed": failed, "bytes": freed,
            "kept_data": bool(keep_data)}


def _remove_services(root: Path) -> None:
    """Best-effort removal of the login-time service on this platform.

    Args:
        root: The project root, where the uninstall scripts live.
    """
    import subprocess
    import sys

    scripts = {
        "linux": ["bash", str(root / "scripts" / "install_service_linux.sh"), "--remove"],
        "darwin": ["bash", str(root / "scripts" / "install_service_macos.sh"), "--remove"],
        "win32": ["powershell", "-ExecutionPolicy", "Bypass", "-File",
                  str(root / "scripts" / "install_service_windows.ps1"), "-Remove"],
    }
    command = scripts.get(sys.platform)
    if command is None or not Path(command[-1] if sys.platform != "win32"
                                  else command[-2]).exists():
        return
    try:
        subprocess.run(command, check=False, capture_output=True, timeout=60)
        logger.info("Removed the login-time service.")
    except Exception as exc:  # pragma: no cover - platform specific
        logger.debug("Could not remove the service: %s", exc)


__all__ = [
    "create_backup",
    "inspect_backup",
    "restore_backup",
    "uninstall",
    "uninstall_plan",
]
