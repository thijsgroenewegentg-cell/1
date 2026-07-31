from pathlib import Path
from ..config import config

def _resolve_path(path: str) -> Path:
    """Resolve path safely inside workspace"""
    ws = config.WORKSPACE_DIR.resolve()
    # Prevent path traversal
    target = (ws / path).resolve()
    # Ensure inside workspace (unless absolute allowed in safe mode off)
    try:
        target.relative_to(ws)
    except ValueError:
        # If safe mode, block
        if config.SAFE_MODE:
            raise ValueError("Path outside workspace not allowed in safe mode")
        # Otherwise allow but warn
        pass
    return target

def file_list(path: str = ".") -> str:
    try:
        resolved = _resolve_path(path)
        if not resolved.exists():
            return f"Path {path} does not exist, Sir."
        if resolved.is_file():
            return f"{path} is a file, not directory"
        
        items = list(resolved.iterdir())
        if not items:
            return f"Directory {path} is empty, Sir."
        
        output = [f"Contents of {path}:\n"]
        for item in sorted(items, key=lambda x: (x.is_file(), x.name)):
            icon = "📄" if item.is_file() else "📁"
            size = f" ({item.stat().st_size} bytes)" if item.is_file() else ""
            output.append(f"{icon} {item.name}{size}")
        return "\n".join(output)
    except Exception as e:
        return f"Error listing {path}: {e}"

def file_read(path: str) -> str:
    try:
        resolved = _resolve_path(path)
        if not resolved.exists():
            return f"File {path} not found, Sir."
        if resolved.is_dir():
            return f"{path} is a directory. Use file_list instead."
        
        # Limit size
        if resolved.stat().st_size > 100_000:
            return f"File {path} too large ({resolved.stat().st_size} bytes). Try first 100k chars."
        
        content = resolved.read_text(encoding="utf-8", errors="ignore")
        if len(content) > 10_000:
            content = content[:10_000] + "\n... [truncated, Sir]"
        return f"File: {path}\n---\n{content}"
    except Exception as e:
        return f"Error reading {path}: {e}"

def file_write(path: str, content: str) -> str:
    try:
        resolved = _resolve_path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"File written successfully to {path}, Sir. ({len(content)} chars)"
    except Exception as e:
        return f"Error writing {path}: {e}"

def file_delete(path: str) -> str:
    try:
        resolved = _resolve_path(path)
        if not resolved.exists():
            return f"File {path} not found, Sir."
        if resolved.is_dir():
            return f"Cannot delete directory {path} with file_delete tool, Sir. It's a directory."
        resolved.unlink()
        return f"File {path} deleted, Sir."
    except Exception as e:
        return f"Error deleting {path}: {e}"
