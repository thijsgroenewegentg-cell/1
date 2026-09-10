"""User-visible file checkpoints for reversible multi-step work."""
from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CHECKPOINT_ROOT = BASE_DIR / "memory" / "checkpoints"
INDEX_PATH = CHECKPOINT_ROOT / "index.json"
OPERATIONS_PATH = CHECKPOINT_ROOT / "operations.json"
_lock = threading.RLock()


def _load() -> list[dict]:
    try:
        value = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _save(value: list[dict]) -> None:
    CHECKPOINT_ROOT.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(value[-30:], indent=2, ensure_ascii=False), encoding="utf-8")


def _safe_path(raw: str) -> Path:
    path = Path(str(raw or "")).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"File not found: {raw}")
    if path == BASE_DIR or BASE_DIR not in path.parents:
        # Checkpoints can protect user files, but never copy outside the home folder.
        if Path.home().resolve() not in path.parents:
            raise ValueError("Checkpoint paths must be inside the user home folder.")
    return path


def create(label: str, paths) -> dict:
    values = paths if isinstance(paths, list) else [x.strip() for x in str(paths or "").split(",") if x.strip()]
    if not values or len(values) > 20:
        raise ValueError("Provide between 1 and 20 files.")
    checkpoint_id = uuid.uuid4().hex[:10]
    target = CHECKPOINT_ROOT / checkpoint_id
    target.mkdir(parents=True, exist_ok=False)
    records = []
    try:
        for raw in values:
            source = _safe_path(raw)
            # Store a flat numbered copy plus the original path in the index.
            name = f"{len(records):03d}_{source.name}"
            dest = target / name
            shutil.copy2(source, dest)
            records.append({"source": str(source), "copy": str(dest)})
        checkpoint = {"id": checkpoint_id, "label": str(label or "checkpoint")[:120], "created": datetime.now().isoformat(timespec="seconds"), "files": records}
        with _lock:
            index = _load()
            index.append(checkpoint)
            _save(index)
        return checkpoint
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def list_checkpoints() -> list[dict]:
    with _lock:
        return _load()


def restore(checkpoint_id: str) -> str:
    checkpoint_id = str(checkpoint_id or "").strip()
    if not re.fullmatch(r"[a-f0-9]{10}", checkpoint_id):
        return "Checkpoint id is invalid."
    with _lock:
        checkpoint = next((x for x in _load() if x.get("id") == str(checkpoint_id)), None)
    if not checkpoint:
        return "Checkpoint not found."
    restored = []
    for record in checkpoint.get("files", []):
        source = Path(record["source"]).resolve()
        copy = Path(record["copy"]).resolve()
        if not copy.is_file() or source.parent == source:
            continue
        if Path.home().resolve() not in source.parents and source != Path.home().resolve():
            return "Checkpoint restore refused: target is outside the user home folder."
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(copy, source)
        restored.append(str(source))
    return f"Restored checkpoint {checkpoint_id}: {', '.join(restored) or 'no files'}"


def remove(checkpoint_id: str) -> bool:
    checkpoint_id = str(checkpoint_id or "").strip()
    if not re.fullmatch(r"[a-f0-9]{10}", checkpoint_id):
        return False
    with _lock:
        index = _load()
        kept = [x for x in index if x.get("id") != str(checkpoint_id)]
        found = len(kept) != len(index)
        if found:
            _save(kept)
        target = CHECKPOINT_ROOT / str(checkpoint_id)
        shutil.rmtree(target, ignore_errors=True)
        return found
