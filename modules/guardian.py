# /modules/guardian.py
"""Data guardian: snapshots, restores and babysits everything JARVIS knows.

The heavy lifting lives in :mod:`utils.backup` (the same engine behind
``python main.py --backup`` / ``--restore``): one dated zip of the database,
memory, notes, code, plugins and ``config.yaml``. This module turns those
primitives into voice tools — "back up my data", "list backups", "restore
the backup from this morning" — adds retention pruning (keep the last N,
configurable) and an optional automatic daily snapshot while JARVIS is
running. Everything is local: no cloud, no service.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

from modules.base import BaseModule, ModuleResult, tool
from utils.helpers import ensure_dir, human_bytes, run_blocking, truncate

try:
    from utils.backup import create_backup, inspect_backup, restore_backup
except Exception:  # pragma: no cover - import cycle guard
    create_backup = None  # type: ignore[assignment]
    inspect_backup = None  # type: ignore[assignment]
    restore_backup = None  # type: ignore[assignment]

BACKUP_PREFIX = "jarvis-backup-"
BACKUP_PATTERN = re.compile(r"^jarvis-backup-(\d{8})-(\d{6})\.zip$")


def _stamp_to_text(stamp: Optional[str]) -> str:
    """Turn a ``YYYYMMDD-HHMMSS`` filename stamp into a friendly date."""
    if not stamp:
        return "an unknown time"
    try:
        moment = datetime.strptime(stamp, "%Y%m%d-%H%M%S")
    except Exception:
        return stamp.replace("-", " ")
    return f"{moment:%A} {moment.day} {moment:%B} at {moment:%H:%M}"


class Guardian(BaseModule):
    """Back up, list and restore snapshots of everything JARVIS knows."""

    name = "guardian"
    description = (
        "The data guardian: create a full snapshot of your data (database, "
        "memory, notes, config) into backups/, list the snapshots on disk, "
        "and restore one when something goes wrong. Everything stays on this "
        "machine."
    )
    intent_examples: ClassVar[List[str]] = [
        "back up my data",
        "make a snapshot before we try that",
        "list the backups",
        "restore the backup from yesterday",
    ]

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Resolve where snapshots live and how many to keep.

        Args:
            config: The global configuration object.
            llm: Optional LLM client.
            security: Optional security guard.
        """
        super().__init__(config, llm=llm, security=security)
        self.project_root: Path = Path(getattr(config, "root", Path.cwd()))
        self.backup_dir: Path = config.resolve(
            config.get("assistant.backup_dir", "backups")
        )
        try:
            self.keep: int = max(1, int(config.get("assistant.keep_backups", 5) or 5))
        except (TypeError, ValueError):
            self.keep = 5
        self.auto_backup: bool = bool(config.get("assistant.auto_backup", False))
        self.auto_backup_time: str = str(
            config.get("assistant.auto_backup_time", "04:00") or "04:00"
        ).strip()
        self._snapshot_task: Optional[asyncio.Task] = None
        ensure_dir(self.backup_dir)

    # ------------------------------------------------------------- plumbing
    def _snapshots(self) -> List[Dict[str, Any]]:
        """Return every snapshot in the backup directory, newest first."""
        found: List[Dict[str, Any]] = []
        if not self.backup_dir.is_dir():
            return found
        for path in sorted(self.backup_dir.glob(f"{BACKUP_PREFIX}*.zip"),
                           key=lambda item: item.name, reverse=True):
            match = BACKUP_PATTERN.match(path.name)
            stamp = match.group(1) + "-" + match.group(2) if match else None
            try:
                size = path.stat().st_size
            except Exception:
                size = 0
            found.append({
                "name": path.name,
                "path": str(path),
                "stamp": stamp or "",
                "when": _stamp_to_text(stamp),
                "bytes": size,
            })
        return found

    def _prune(self) -> List[str]:
        """Delete snapshots beyond the newest ``assistant.keep_backups``.

        Returns:
            The names of the snapshots removed.
        """
        removed: List[str] = []
        for item in self._snapshots()[self.keep:]:
            try:
                Path(item["path"]).unlink(missing_ok=True)
                removed.append(item["name"])
            except Exception as exc:
                self.log.debug("Could not prune %s: %s", item["name"], exc)
        return removed

    async def setup(self) -> None:
        """Start the optional automatic daily snapshot loop."""
        if self.auto_backup and self._snapshot_task is None:
            self._snapshot_task = asyncio.create_task(self._auto_snapshot_loop())

    async def shutdown(self) -> None:
        """Cancel the automatic snapshot loop."""
        if self._snapshot_task is not None:
            self._snapshot_task.cancel()
            try:
                await self._snapshot_task
            except (asyncio.CancelledError, Exception):
                pass
            self._snapshot_task = None

    def _seconds_until(self, hour: int, minute: int) -> float:
        """Seconds from now until the next HH:MM on the local clock."""
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    async def _auto_snapshot_loop(self) -> None:
        """Snapshot daily at ``assistant.auto_backup_time`` while running."""
        while True:
            try:
                parts = self.auto_backup_time.split(":")
                hour = int(parts[0]) % 24
                minute = int(parts[1]) if len(parts) > 1 else 0
            except (ValueError, IndexError):
                hour, minute = 4, 0
            await asyncio.sleep(self._seconds_until(hour, minute))
            try:
                await self._snapshot_once(silent=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.log.debug("Automatic snapshot failed: %s", exc)

    async def _snapshot_once(self, silent: bool = False) -> ModuleResult:
        """Create one snapshot and prune the oldest beyond the retention.

        Args:
            silent: When True, failures and outcomes are logged rather than
                announced (used by the automatic daily snapshot).

        Returns:
            A :class:`ModuleResult` describing the snapshot.
        """
        if create_backup is None:  # pragma: no cover - cycle guard
            return ModuleResult.fail("Backup engine unavailable.")
        try:
            summary = await run_blocking(
                create_backup, self.project_root, self.backup_dir
            )
        except Exception as exc:
            message = f"Backup failed: {truncate(str(exc), 160)}"
            if not silent:
                return ModuleResult.fail(message)
            self.log.warning("Automatic snapshot failed: %s", exc)
            return ModuleResult.fail(message)
        pruned = await run_blocking(self._prune)
        name = Path(summary["path"]).name
        spoken = (
            f"Snapshot complete: {summary['files']} file(s), "
            f"{human_bytes(summary['bytes'])} of data, saved as {name}. "
        )
        if pruned:
            spoken += f"I pruned {len(pruned)} older snapshot(s); keeping the last {self.keep}."
        elif not silent:
            spoken += f"I'm keeping the last {self.keep} snapshots."
        return ModuleResult(
            success=True,
            output=spoken,
            speak=spoken,
            data={"backup": {**summary, "name": name, "pruned": pruned}},
        )

    # ----------------------------------------------------------------- tools
    @tool(
        description=(
            "Create a full snapshot of the user's data (SQLite database, "
            "memory, notes, code, config.yaml) as a dated zip in the backup "
            "directory. Old snapshots beyond assistant.keep_backups are pruned. "
            "Everything stays on this machine."
        ),
        params={},
        keywords=["back up my data", "backup my data", "make a backup",
                  "create a backup", "back everything up", "make a snapshot",
                  "snapshot my data", "backup now", "take a backup",
                  "save my data"],
        examples=["back up my data before we try that"],
    )
    async def backup_data(self) -> ModuleResult:
        """Run a full local snapshot of the user's data now."""
        return await self._snapshot_once()

    @tool(
        description=(
            "List every snapshot sitting in the backup directory, newest "
            "first, with its date, size and the filename needed to restore it."
        ),
        params={},
        keywords=["list backups", "show backups", "what backups do I have",
                  "backup history", "my backups", "list snapshots",
                  "what snapshots", "show me the backups"],
    )
    async def list_backups(self) -> ModuleResult:
        """Return a readable catalogue of the snapshots on disk.

        Returns:
            A :class:`ModuleResult` naming each snapshot and its age/size.
        """
        items = self._snapshots()
        if not items:
            return ModuleResult(
                success=True,
                output=(
                    "No snapshots yet, sir. Say \"back up my data\" and I'll "
                    "make the first one."
                ),
                speak="No snapshots yet, sir.",
                data={"backups": []},
            )
        lines = [f"{len(items)} snapshot(s), newest first:"]
        for index, item in enumerate(items, start=1):
            when = item["when"]
            if index == 1:
                when += "  ← newest"
            lines.append(f"  {index}. {when} — {human_bytes(item['bytes'])} "
                         f"({item['name']})")
        body = "\n".join(lines)
        first = items[0]
        speak = (
            f"{len(items)} snapshot(s) on disk. The newest is from "
            f"{first['when']}, {human_bytes(first['bytes'])}."
        )
        return ModuleResult(success=True, output=body, speak=speak,
                            data={"backups": items})

    @tool(
        description=(
            "Restore the user's data from one of the snapshots in the backup "
            "directory. Pass 'name' exactly as shown by list_backups (a "
            "partial date like '20260908' also works when it matches only "
            "one). Anything about to be overwritten is itself saved first, "
            "so the restore is undoable."
        ),
        params={
            "name": {"type": "string", "required": False,
                     "description": "Snapshot name or date to restore from; "
                                    "blank = list what is available"},
        },
        keywords=["restore the backup", "restore from backup", "restore my data",
                  "roll back my data", "undo my data", "recover from backup",
                  "restore the snapshot", "go back to the backup"],
        dangerous=True,
        examples=["restore the backup from yesterday"],
    )
    async def restore_backup_tool(self, name: str = "") -> ModuleResult:
        """Restore everything from a chosen snapshot.

        Args:
            name: Snapshot filename (or a unique fragment of one). Blank
                lists the available snapshots instead.

        Returns:
            A :class:`ModuleResult` describing what was restored.
        """
        if restore_backup is None:  # pragma: no cover - cycle guard
            return ModuleResult.fail("Backup engine unavailable.")
        wanted = (name or "").strip()
        items = self._snapshots()
        if not items:
            return ModuleResult.fail(
                "No snapshots to restore from, sir. Say \"back up my data\" "
                "first and I'll have one."
            )
        if not wanted:
            return ModuleResult(
                success=True,
                output=(
                    "Say which snapshot, sir — for example \"restore the "
                    "backup from this morning\". On disk:\n" + "\n".join(
                        f"  {item['name']} — {item['when']}" for item in items[:8]
                    )
                ),
                speak=f"Which snapshot, sir? The newest is from {items[0]['when']}.",
                data={"backups": items},
            )
        lowered = wanted.lower()
        matches = [
            item for item in items
            if lowered in item["name"].lower() or lowered in item["stamp"].lower()
            or lowered.replace("-", "").replace(":", "") in
            item["stamp"].replace("-", "")
        ]
        if len(matches) > 1:
            return ModuleResult.fail(
                f"'{wanted}' matches {len(matches)} snapshots — be more "
                f"specific, sir. Newest: {matches[0]['name']}.",
                data={"backups": matches},
            )
        if not matches:
            newest = items[0]["name"]
            return ModuleResult.fail(
                f"I can't find a snapshot called '{truncate(wanted, 80)}'. "
                f"The newest one is {newest} — say \"restore {newest}\".",
                data={"backups": items[:5]},
            )
        item = matches[0]
        archive = Path(item["path"])
        try:
            result = await run_blocking(
                restore_backup, self.project_root, archive, overwrite=True
            )
        except Exception as exc:
            return ModuleResult.fail(
                f"The restore hit a snag: {truncate(str(exc), 160)}"
            )
        if not result.get("ok"):
            return ModuleResult.fail(
                f"Couldn't restore: {result.get('error', 'unreadable backup')}"
            )
        restored = int(result.get("restored", 0))
        rejected = result.get("rejected") or []
        spoken = (
            f"Restored {restored} file(s) from the snapshot of {item['when']}, "
            f"sir. Anything it replaced was saved aside first."
        )
        if rejected:
            spoken += (f" {len(rejected)} unsafe path(s) in that snapshot were "
                       f"left alone.")
        self.log.info("Restore of '%s': %s", item["name"],
                      {key: result.get(key) for key in
                       ("restored", "skipped", "rejected", "safety")})
        return ModuleResult(
            success=True,
            output=spoken,
            speak=spoken,
            data={"restored": restored, "skipped": result.get("skipped", 0),
                  "rejected": rejected,
                  "safety": result.get("safety", ""),
                  "snapshot": item["name"]},
        )
