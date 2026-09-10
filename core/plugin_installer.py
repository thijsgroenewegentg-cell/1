"""Human-approved local plugin installer.

The assistant never downloads or executes a plugin during inspection. A user
chooses a local .py file, sees its declared name/description and SHA-256, and
confirms before it is copied into plugins/. The hash is recorded so future UI
code can identify files installed through this path. Built-in plugin hashes
are kept separately in core/trusted_plugins.json; user approvals stay in the
ignored config/plugin_trust.json file.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


@dataclass
class PluginInspection:
    path: Path
    name: str = ""
    description: str = ""
    sha256: str = ""
    source_preview: str = ""
    valid: bool = False
    error: str = ""


def _literal_plugin_meta(tree: ast.AST) -> dict | None:
    for node in getattr(tree, "body", []):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "PLUGIN" for target in targets):
            continue
        value = node.value
        try:
            meta = ast.literal_eval(value)
        except Exception:
            return None
        return meta if isinstance(meta, dict) else None
    return None


def inspect_plugin(path: str | Path) -> PluginInspection:
    source = Path(path).expanduser().resolve()
    result = PluginInspection(path=source)
    if not source.exists() or not source.is_file():
        result.error = "Plugin file does not exist."
        return result
    if source.suffix.lower() != ".py":
        result.error = "Only Python .py plugin files are accepted."
        return result
    try:
        text = source.read_text(encoding="utf-8")
        result.sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        preview_lines = text.splitlines()[:12]
        result.source_preview = "\n".join(preview_lines)[:900]
        tree = ast.parse(text, filename=str(source))
    except UnicodeDecodeError:
        result.error = "Plugin is not valid UTF-8 text."
        return result
    except SyntaxError as exc:
        result.error = f"Python syntax error at line {exc.lineno}: {exc.msg}"
        return result
    except Exception as exc:
        result.error = f"Could not inspect plugin: {exc}"
        return result

    meta = _literal_plugin_meta(tree)
    if meta is None:
        result.error = "Plugin must contain a literal PLUGIN dictionary."
        return result
    name = meta.get("name")
    description = meta.get("description")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        result.error = "PLUGIN['name'] is missing or is not a valid identifier."
        return result
    if not isinstance(description, str) or not description.strip():
        result.error = "PLUGIN['description'] is missing or empty."
        return result
    if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run"
               for node in getattr(tree, "body", [])):
        result.error = "Plugin must define run(parameters, ...)."
        return result

    result.name = name
    result.description = description.strip()
    result.valid = True
    return result


def _trust_path(root: Path) -> Path:
    return root / "config" / "plugin_trust.json"


def _bundled_trust_path(root: Path) -> Path:
    return root / "core" / "trusted_plugins.json"


def _load_trust(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_trust(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="plugin-trust-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except Exception:
            pass


def trust_status(path: str | Path, root: str | Path | None = None) -> str:
    """Return bundled, approved, unverified, or invalid without importing code."""
    source = Path(path).expanduser().resolve()
    base = Path(root).resolve() if root else Path(__file__).resolve().parent.parent
    inspection = inspect_plugin(source)
    if not inspection.valid:
        return "invalid"
    local = _load_trust(_trust_path(base))
    record = local.get(inspection.name)
    if isinstance(record, dict) and record.get("sha256") == inspection.sha256:
        return "approved"
    bundled = _load_trust(_bundled_trust_path(base))
    record = bundled.get(inspection.name)
    if isinstance(record, dict) and record.get("sha256") == inspection.sha256:
        return "bundled"
    return "unverified"


def is_trusted(path: str | Path, root: str | Path | None = None) -> bool:
    return trust_status(path, root) in {"approved", "bundled"}


def install_plugin(source: str | Path, root: str | Path | None = None,
                   replace: bool = False) -> tuple[bool, str]:
    base = Path(root).resolve() if root else Path(__file__).resolve().parent.parent
    inspection = inspect_plugin(source)
    if not inspection.valid:
        return False, inspection.error

    plugins_dir = base / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    destination = plugins_dir / f"{inspection.name}.py"
    already_in_place = destination.exists() and destination.resolve() == inspection.path
    if destination.exists() and not replace and not already_in_place:
        return False, f"A plugin named {inspection.name!r} already exists."

    if not already_in_place:
        temp_fd, temp_name = tempfile.mkstemp(prefix=f"{inspection.name}-", suffix=".py", dir=str(plugins_dir))
        try:
            os.close(temp_fd)
            shutil.copyfile(inspection.path, temp_name)
            os.replace(temp_name, destination)
        except Exception as exc:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except Exception:
                pass
            return False, f"Could not install plugin: {exc}"

    trust = _load_trust(_trust_path(base))
    trust[inspection.name] = {
        "sha256": inspection.sha256,
        "file": destination.name,
        "source": str(inspection.path),
        "installed": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        _save_trust(_trust_path(base), trust)
    except Exception as exc:
        return True, f"Installed {inspection.name}, but trust record could not be saved: {exc}"
    return True, f"Installed and trusted {inspection.name}. Restart MARK to load it."


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and install a MARK plugin with human approval.")
    parser.add_argument("plugin", type=Path, help="Local Python plugin file")
    parser.add_argument("--replace", action="store_true", help="Replace an existing plugin with the same name")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive confirmation")
    args = parser.parse_args()

    inspection = inspect_plugin(args.plugin)
    if not inspection.valid:
        print(f"Rejected: {inspection.error}")
        return 2
    print(f"Name:        {inspection.name}")
    print(f"Description: {inspection.description}")
    print(f"SHA-256:     {inspection.sha256}")
    print(f"Source:      {inspection.path}")
    print("Preview:")
    print(inspection.source_preview)
    if not args.yes:
        try:
            answer = input("Install this local plugin? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in {"y", "yes"}:
            print("Cancelled; no file was changed.")
            return 0
    ok, message = install_plugin(args.plugin, replace=args.replace)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
