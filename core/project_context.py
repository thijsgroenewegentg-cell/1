"""Small, secret-safe local project context for MARK's system prompt."""
from __future__ import annotations

from pathlib import Path


_SKIP = {".git", ".venv", "node_modules", "__pycache__", "config", "memory", ".env"}
_SECRET_NAME_PARTS = ("credential", "secret", "token", "password", "passwd", "private_key", ".pem", ".key")
_MANIFESTS = (
    "pyproject.toml", "requirements.txt", "package.json", "Cargo.toml",
    "Dockerfile", "compose.yaml", "docker-compose.yml", "README.md",
)


def _root(value: str | Path | None) -> Path:
    path = Path(value).expanduser() if value else Path.cwd()
    path = path if path.is_dir() else path.parent
    return path.resolve()


def describe(value: str | Path | None = None, limit: int = 1400) -> str:
    root = _root(value)
    try:
        entries = sorted(
            item.name for item in root.iterdir()
            if item.name not in _SKIP
            and not item.name.startswith(".")
            and not any(part in item.name.lower() for part in _SECRET_NAME_PARTS)
        )[:80]
    except OSError as exc:
        return f"Project context unavailable: {exc}"
    manifests = [name for name in _MANIFESTS if (root / name).is_file()]
    branch = ""
    head = root / ".git" / "HEAD"
    try:
        raw = head.read_text(encoding="utf-8", errors="replace").strip()
        branch = raw[5:].removeprefix("refs/heads/") if raw.startswith("ref:") else "detached"
    except OSError:
        pass
    text = (
        f"Root: {root}\n"
        f"Branch: {branch or 'not a Git checkout'}\n"
        f"Manifests: {', '.join(manifests) or 'none'}\n"
        f"Visible top-level entries: {', '.join(entries) or '(empty)'}"
    )
    return text[:limit]
