# /core/vault.py
"""Local secret vault — codes you do not want in plain notes.

``remember my wifi password is hunter2`` stores the secret in an obfuscated
file next to the journal; ``what is my wifi password`` reads it back only
when asked, ``forget my wifi password`` removes it. Obfuscation is a local
XOR with a key derived from this installation's own paths — not encryption
for the cloud, and nothing ever leaves this machine or enters the journal,
threads or search index.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.vault")

_MAGIC = b"JV1:"


def _path(config: Any) -> Path:
    try:
        journal = config.resolve(
            config.get("assistant.journal_file", "data/journal.json")
        )
        return journal.parent / "vault.json"
    except Exception:
        return Path("data/vault.json")


def _key(config: Any) -> bytes:
    material = str(_path(config).absolute()).encode("utf-8") + b"|jarvis-vault-v1"
    return hashlib.sha256(material).digest()


def _scramble(value: str, key: bytes) -> str:
    payload = _MAGIC + value.encode("utf-8")
    stream = (key * (len(payload) // len(key) + 1))[: len(payload)]
    encoded = bytes(a ^ b for a, b in zip(payload, stream))
    return base64.b64encode(encoded).decode()


def _unscramble(blob: str, key: bytes) -> Optional[str]:
    try:
        payload = base64.b64decode(blob)
        stream = (key * (len(payload) // len(key) + 1))[: len(payload)]
        plain = bytes(a ^ b for a, b in zip(payload, stream))
        if not plain.startswith(_MAGIC):
            return None
        return plain[len(_MAGIC):].decode("utf-8")
    except Exception:
        return None


def store(config: Any, name: str, value: str) -> str:
    """Put one secret in the vault (overwrites an existing entry).

    Args:
        config: Configuration.
        name: The label, e.g. ``"wifi password"``.
        value: The secret text.

    Returns:
        The canonical label used (lowercased, collapsed spaces).
    """
    label = _label(name)
    state = _load(config)
    state["entries"][label] = _scramble(value or "", _key(config))
    _save(config, state)
    return label


def get(config: Any, name: str) -> Optional[str]:
    """Read a secret back, or ``None`` when it is not in the vault."""
    state = _load(config)
    blob = state["entries"].get(_label(name))
    return _unscramble(blob, _key(config)) if blob else None


def forget(config: Any, name: str) -> bool:
    """Remove a secret from the vault.

    Args:
        config: Configuration.
        name: The label.

    Returns:
        True when something was removed.
    """
    state = _load(config)
    if _label(name) not in state["entries"]:
        return False
    state["entries"].pop(_label(name), None)
    _save(config, state)
    return True


def labels(config: Any) -> List[str]:
    """The vault's entry labels (never their values)."""
    return sorted(_load(config)["entries"].keys())


def _label(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())[:60]


def _load(config: Any) -> Dict[str, Any]:
    path = _path(config)
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("entries"), dict):
                return raw
    except Exception as exc:  # pragma: no cover - best-effort store
        logger.debug("Vault unreadable: %s", exc)
    return {"entries": {}}


def _save(config: Any, state: Dict[str, Any]) -> None:
    path = _path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


__all__ = ["forget", "get", "labels", "store"]
