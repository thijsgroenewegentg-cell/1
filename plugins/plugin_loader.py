# /plugins/plugin_loader.py
"""Discovering, vetting, loading and unloading plugin skills.

A plugin is a single ``.py`` file under ``plugins/`` that defines a
:class:`~modules.base.BaseModule` subclass. Once loaded, its ``@tool`` methods
become things JARVIS can be asked to do, exactly like a built-in module.

The dangerous part is that JARVIS writes some of these files itself, so
loading is deliberately a two-step affair:

``plugins/pending/`` → you read it → :func:`approve` → ``plugins/`` → loaded

:func:`vet_source` is the static gate every candidate passes first: it must
parse, it must define a module, and it must not import or call any of the
things on :data:`BANNED_IMPORTS` / :data:`BANNED_CALLS`. That check is static
only — it is a seatbelt, not a sandbox, which is exactly why approval is
manual.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modules.base import BaseModule
from utils.logger import get_logger

logger = get_logger("plugins.loader")

#: Imports a generated plugin has no business making.
BANNED_IMPORTS = {
    "ctypes", "multiprocessing", "socketserver", "pty", "pickle", "marshal",
    "shelve", "telnetlib", "ftplib", "smtplib", "webbrowser", "winreg",
}

#: Calls that turn a text file into arbitrary code execution.
BANNED_CALLS = {"eval", "exec", "compile", "__import__", "globals", "breakpoint"}

#: Attribute chains that are almost always an escape attempt.
BANNED_ATTRIBUTES = {"__subclasses__", "__globals__", "__bases__", "__mro__"}


@dataclass
class PluginInfo:
    """What is known about one plugin file.

    Attributes:
        name: The plugin's stem, e.g. ``weather_extra``.
        path: Where the file lives.
        pending: True when it is waiting for review.
        module_name: The BaseModule subclass it defines, if any.
        tools: Names of the tools it exposes.
        issues: Why it was rejected, when it was.
        loaded: True when it is live in this process.
    """

    name: str
    path: Path
    pending: bool = False
    module_name: str = ""
    tools: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    loaded: bool = False

    @property
    def safe(self) -> bool:
        """True when static vetting found nothing to complain about."""
        return not self.issues

    def describe(self) -> str:
        """One line for a listing."""
        state = "pending" if self.pending else ("loaded" if self.loaded else "installed")
        tools = f"{len(self.tools)} tools" if self.tools else "no tools"
        verdict = "clean" if self.safe else f"{len(self.issues)} concern(s)"
        return f"{self.name} ({state}, {tools}, {verdict})"


def discover(directory: Path, pending: bool = False) -> List[Path]:
    """List candidate plugin files in a directory.

    Args:
        directory: ``plugins/`` or ``plugins/pending/``.
        pending: Look in the ``pending`` subdirectory instead.

    Returns:
        Sorted paths of files that could be plugins.
    """
    target = directory / "pending" if pending else directory
    if not target.exists():
        return []
    return sorted(
        path for path in target.glob("*.py")
        if not path.name.startswith("_") and path.name not in {"base.py", "plugin_loader.py"}
    )


def vet_source(source: str) -> Tuple[List[str], str, List[str]]:
    """Statically check plugin source before anyone imports it.

    Args:
        source: The file's text.

    Returns:
        A tuple of (issues, module class name, tool names). An empty issues
        list means nothing obviously dangerous was found.
    """
    issues: List[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [f"does not parse: {error}"], "", []

    module_name = ""
    tools: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names] if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in names:
                root = name.split(".")[0]
                if root in BANNED_IMPORTS:
                    issues.append(f"imports {root}")
        elif isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name) and target.id in BANNED_CALLS:
                issues.append(f"calls {target.id}()")
            if isinstance(target, ast.Attribute) and target.attr in BANNED_ATTRIBUTES:
                issues.append(f"touches {target.attr}")
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_ATTRIBUTES:
            issues.append(f"touches {node.attr}")
        elif isinstance(node, ast.ClassDef):
            bases = {getattr(base, "id", getattr(base, "attr", "")) for base in node.bases}
            if "BaseModule" in bases:
                module_name = node.name
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for decorator in item.decorator_list:
                            label = getattr(decorator, "id", "") or getattr(
                                getattr(decorator, "func", None), "id", ""
                            )
                            if label == "tool":
                                tools.append(item.name)

    if not module_name:
        issues.append("defines no BaseModule subclass")
    return sorted(set(issues)), module_name, tools


def inspect_plugin(path: Path, pending: bool = False) -> PluginInfo:
    """Read and vet one plugin file without importing it.

    Args:
        path: The file to inspect.
        pending: Whether it lives in the review queue.

    Returns:
        A populated :class:`PluginInfo`.
    """
    info = PluginInfo(name=path.stem, path=path, pending=pending)
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as error:
        info.issues.append(f"unreadable: {error}")
        return info
    info.issues, info.module_name, info.tools = vet_source(source)
    return info


def survey(directory: Path) -> List[PluginInfo]:
    """Inspect every installed and pending plugin.

    Args:
        directory: The ``plugins/`` folder.

    Returns:
        Installed plugins first, then the pending queue.
    """
    found = [inspect_plugin(path) for path in discover(directory)]
    found += [inspect_plugin(path, pending=True) for path in discover(directory, pending=True)]
    return found


def load(path: Path, config: Any, llm: Any = None, security: Any = None,
         enforce: bool = True) -> Optional[BaseModule]:
    """Import a plugin file and instantiate the module it defines.

    Args:
        path: Path to the plugin file.
        config: The global configuration object.
        llm: Optional LLM client handed to the module.
        security: Optional security guard handed to the module.
        enforce: Refuse to import a file that fails :func:`vet_source`.

    Returns:
        The instantiated module, or ``None`` when it defines none or was
        rejected.
    """
    info = inspect_plugin(path)
    if enforce and not info.safe:
        logger.warning("Refusing to load %s: %s", path.name, "; ".join(info.issues))
        return None

    module_name = f"jarvis_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None
    imported = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = imported
    try:
        spec.loader.exec_module(imported)
    except Exception as error:
        logger.warning("Plugin %s failed to import: %s", path.name, error)
        sys.modules.pop(module_name, None)
        return None

    for attribute in vars(imported).values():
        if (
            isinstance(attribute, type)
            and issubclass(attribute, BaseModule)
            and attribute is not BaseModule
        ):
            try:
                return attribute(config, llm=llm, security=security)
            except TypeError:
                return attribute(config)
            except Exception as error:
                logger.warning("Plugin %s would not start: %s", path.name, error)
                return None
    return None


def unload(name: str) -> bool:
    """Drop a plugin's imported module from ``sys.modules``.

    The caller still has to unregister it from the brain; this only makes the
    next import re-read the file from disk.

    Args:
        name: The plugin's stem.

    Returns:
        True when something was removed.
    """
    return sys.modules.pop(f"jarvis_plugin_{name}", None) is not None


def approve(directory: Path, name: str) -> Tuple[bool, str]:
    """Move a plugin out of the review queue so it can be loaded.

    Args:
        directory: The ``plugins/`` folder.
        name: The plugin's stem.

    Returns:
        ``(ok, message)``.
    """
    source = directory / "pending" / f"{name}.py"
    if not source.exists():
        return False, f"There is no plugin called '{name}' waiting for review."
    info = inspect_plugin(source, pending=True)
    if not info.safe:
        return False, f"'{name}' still looks wrong: {'; '.join(info.issues)}."
    target = directory / f"{name}.py"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
    except Exception as error:
        return False, f"Could not approve '{name}': {error}"
    return True, f"'{name}' approved with {len(info.tools)} tool(s)."


def reject(directory: Path, name: str, keep_source: bool = False) -> Tuple[bool, str]:
    """Delete a plugin from the review queue.

    Args:
        directory: The ``plugins/`` folder.
        name: The plugin's stem.
        keep_source: Leave any cloned repository behind.

    Returns:
        ``(ok, message)``.
    """
    source = directory / "pending" / f"{name}.py"
    if not source.exists():
        return False, f"Nothing called '{name}' is waiting for review."
    with contextlib.suppress(Exception):
        source.unlink()
    clone = directory / "pending" / name
    if clone.is_dir() and not keep_source:
        with contextlib.suppress(Exception):
            shutil.rmtree(clone)
    return True, f"'{name}' rejected and removed."


def remove(directory: Path, name: str) -> Tuple[bool, str]:
    """Delete an installed plugin and forget its import.

    Args:
        directory: The ``plugins/`` folder.
        name: The plugin's stem.

    Returns:
        ``(ok, message)``.
    """
    target = directory / f"{name}.py"
    if not target.exists():
        return False, f"No plugin called '{name}' is installed."
    with contextlib.suppress(Exception):
        target.unlink()
    unload(name)
    return True, f"'{name}' removed."


def summary(directory: Path) -> Dict[str, Any]:
    """Counts for the status screens.

    Args:
        directory: The ``plugins/`` folder.

    Returns:
        A dict with installed/pending/unsafe counts and the names.
    """
    everything = survey(directory)
    installed = [item for item in everything if not item.pending]
    pending = [item for item in everything if item.pending]
    return {
        "installed": len(installed),
        "pending": len(pending),
        "unsafe": len([item for item in everything if not item.safe]),
        "names": [item.name for item in installed],
        "waiting": [item.name for item in pending],
        "tools": sum(len(item.tools) for item in installed),
    }


__all__ = [
    "BANNED_CALLS",
    "BANNED_IMPORTS",
    "PluginInfo",
    "approve",
    "discover",
    "inspect_plugin",
    "load",
    "reject",
    "remove",
    "summary",
    "survey",
    "unload",
    "vet_source",
]
