# /utils/cache.py
"""Tiny SQLite-backed TTL cache.

Used to keep DuckDuckGo, weather and news lookups from hammering (and getting
rate-limited by) the free public endpoints JARVIS relies on. Values are JSON
serialised, so anything the modules return can be cached.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from utils.helpers import ensure_dir, run_blocking
from utils.logger import get_logger

logger = get_logger("utils.cache")


class Cache:
    """A persistent key/value cache with per-entry expiry.

    Example::

        cache = Cache("data/cache.db")
        hit = await cache.aget("weather:amsterdam")
        if hit is None:
            hit = await fetch_weather()
            await cache.aset("weather:amsterdam", hit, ttl=900)
    """

    def __init__(self, path: str | Path, default_ttl: int = 900) -> None:
        """Args:
        path: SQLite file used for storage.
        default_ttl: Fallback lifetime in seconds.
        """
        self.path = Path(path)
        self.default_ttl = int(default_ttl)
        ensure_dir(self.path.parent)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection."""
        connection = sqlite3.connect(str(self.path), timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    def _init(self) -> None:
        """Create the cache table."""
        try:
            with self._connect() as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS cache ("
                    " key TEXT PRIMARY KEY, value TEXT, expires REAL, created REAL)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires)"
                )
        except Exception as exc:  # pragma: no cover
            logger.debug("Cache init failed: %s", exc)

    @staticmethod
    def make_key(*parts: Any) -> str:
        """Build a stable cache key from arbitrary parts."""
        raw = "|".join(str(part) for part in parts)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]

    # -- sync API -----------------------------------------------------------
    def get(self, key: str) -> Optional[Any]:
        """Return a cached value, or ``None`` when missing or expired."""
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT value, expires FROM cache WHERE key = ?", (key,)
                ).fetchone()
            if row is None:
                return None
            if row["expires"] and row["expires"] < time.time():
                self.delete(key)
                return None
            return json.loads(row["value"])
        except Exception as exc:
            logger.debug("Cache read failed: %s", exc)
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Store a value with a lifetime in seconds."""
        try:
            payload = json.dumps(value, default=str)
        except Exception:
            return False
        expiry = time.time() + int(ttl if ttl is not None else self.default_ttl)
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO cache (key, value, expires, created)"
                    " VALUES (?, ?, ?, ?)",
                    (key, payload, expiry, time.time()),
                )
            return True
        except Exception as exc:
            logger.debug("Cache write failed: %s", exc)
            return False

    def delete(self, key: str) -> None:
        """Remove one entry."""
        try:
            with self._connect() as connection:
                connection.execute("DELETE FROM cache WHERE key = ?", (key,))
        except Exception:
            pass

    def purge_expired(self) -> int:
        """Delete every expired entry. Returns the number removed."""
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM cache WHERE expires < ?", (time.time(),)
                )
                return cursor.rowcount or 0
        except Exception:
            return 0

    def clear(self) -> None:
        """Empty the cache completely."""
        try:
            with self._connect() as connection:
                connection.execute("DELETE FROM cache")
        except Exception:
            pass

    def stats(self) -> dict:
        """Return entry counts for status displays."""
        try:
            with self._connect() as connection:
                total = connection.execute("SELECT COUNT(*) AS n FROM cache").fetchone()["n"]
                live = connection.execute(
                    "SELECT COUNT(*) AS n FROM cache WHERE expires > ?", (time.time(),)
                ).fetchone()["n"]
            return {"entries": total, "live": live, "path": str(self.path)}
        except Exception:
            return {"entries": 0, "live": 0, "path": str(self.path)}

    # -- async API ----------------------------------------------------------
    async def aget(self, key: str) -> Optional[Any]:
        """Async wrapper around :meth:`get`."""
        return await run_blocking(self.get, key)

    async def aset(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Async wrapper around :meth:`set`."""
        return await run_blocking(self.set, key, value, ttl)


__all__ = ["Cache"]
