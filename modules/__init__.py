# /modules/__init__.py
"""JARVIS capability modules.

Every module subclasses :class:`modules.base.BaseModule` and exposes
``async def execute(command: str, args: dict) -> ModuleResult``.
Modules are imported lazily by the brain so a disabled or broken module can
never prevent JARVIS from starting.
"""

from modules.base import BaseModule, ModuleResult, ToolSpec, tool  # noqa: F401

__all__ = ["BaseModule", "ModuleResult", "ToolSpec", "tool"]
