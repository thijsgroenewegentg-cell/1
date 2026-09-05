# /utils/security.py
"""Safety layer for anything that can damage the machine.

Every destructive action (shell commands, file deletion, code execution)
passes through :class:`SecurityGuard`, which classifies risk and — when the
action is dangerous — asks the user to confirm out loud or in the terminal.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Sequence

from utils.helpers import expand_path
from utils.logger import get_logger

logger = get_logger("utils.security")

ConfirmHook = Callable[[str], Awaitable[bool]]


class RiskLevel(str, Enum):
    """How much damage an action could do."""

    SAFE = "safe"
    CAUTION = "caution"
    DANGEROUS = "dangerous"
    BLOCKED = "blocked"


@dataclass
class RiskAssessment:
    """Result of inspecting a command or path."""

    level: RiskLevel
    reason: str = ""
    matched: str = ""

    @property
    def needs_confirmation(self) -> bool:
        """True when the user should explicitly approve the action."""
        return self.level in (RiskLevel.CAUTION, RiskLevel.DANGEROUS)

    @property
    def blocked(self) -> bool:
        """True when the action must never run."""
        return self.level is RiskLevel.BLOCKED


# Commands that are never executed, no matter what the user says.
_BLOCKED_PATTERNS: Sequence[str] = (
    r"rm\s+(-[a-z]*\s+)*(-rf|-fr)\s+/(?:\s|$)",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:",           # fork bomb
    r"\bmkfs(\.\w+)?\b",
    r"\bdd\b[^|;]*of=/dev/(sd|nvme|hd|disk)",
    r">\s*/dev/(sd|nvme|hd|disk)\w*",
    r"\bformat\s+[a-z]:\s",
    r"\bdiskpart\b",
    r"chmod\s+(-[a-z]*\s+)*777\s+/(?:\s|$)",
    r"chown\s+.*\s+/(?:\s|$)",
    r"\bshred\b\s+.*/dev/",
    r"curl[^|;]*\|\s*(sudo\s+)?(ba)?sh",
    r"wget[^|;]*\|\s*(sudo\s+)?(ba)?sh",
    r"\bhalt\b|\binit\s+0\b",
    r"del\s+/[fsq]+\s+[a-z]:\\\*",
    r"Remove-Item\s+.*-Recurse.*\s+[Cc]:\\\\?\s*$",
)

# Commands that work fine but deserve a "are you sure?".
_DANGEROUS_PATTERNS: Sequence[str] = (
    r"\brm\b\s+(-[a-z]*\s+)*-?[rf]",
    r"\brmdir\b",
    r"\bsudo\b",
    r"\bsu\b\s",
    r"\bkill(all)?\b",
    r"\bpkill\b",
    r"\bshutdown\b|\breboot\b|\brestart-computer\b",
    r"\bapt(-get)?\s+(remove|purge|autoremove)",
    r"\b(brew|dnf|yum|pacman|apk)\s+(remove|uninstall|-R)",
    r"\bpip\s+uninstall",
    r"\bnpm\s+(uninstall|prune)",
    r"\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f|push\s+.*--force)",
    r"\bdocker\s+(system\s+prune|rm|rmi|kill)",
    r"\bmv\b\s+/",
    r"\btruncate\b",
    r"\bcrontab\s+-r",
    r"\bRemove-Item\b",
    r"\bdel\b\s+/",
    r"\bregedit\b|\breg\s+delete\b",
    r"\bnetsh\b",
    r"\biptables\b|\bufw\s+(disable|reset)",
    r"\bchmod\b|\bchown\b",
    r"\bmkdir\b\s+/(?:etc|usr|bin|sbin|var)",
    r">\s*/etc/",
)

# Commands that merely touch the network / write files → light caution.
_CAUTION_PATTERNS: Sequence[str] = (
    r"\bcurl\b|\bwget\b",
    r"\bpip\s+install",
    r"\bnpm\s+(install|i)\b",
    r"\bgit\s+(push|pull|clone)",
    r"\bssh\b|\bscp\b|\brsync\b",
    r"\bnc\b\s|\bnetcat\b",
    r"\bpython\d?\b\s+-c",
    r"\beval\b|\bexec\b",
    r">\s*[^\s|]+",
)

# Directories that should never be written to or organised.
_PROTECTED_ROOTS = (
    "/", "/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc", "/root",
    "/sbin", "/sys", "/usr", "/var", "/System", "/Library", "/Applications",
    "C:\\", "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
)

# Python constructs blocked inside the code sandbox.
_SANDBOX_FORBIDDEN: Sequence[str] = (
    r"\bimport\s+shutil\b",
    r"\bshutil\.rmtree\b",
    r"\bos\.(remove|unlink|rmdir|removedirs|system)\b",
    r"\bsubprocess\b",
    r"\bsocket\b",
    r"\bctypes\b",
    r"\b__import__\s*\(\s*['\"]os['\"]",
    r"\bopen\s*\([^)]*['\"][wa]",
)


@dataclass
class SecurityGuard:
    """Classifies risk and gates dangerous operations behind confirmation.

    Args:
        confirm_dangerous: When False, dangerous actions run without asking.
        allow_shell: Master switch for arbitrary shell execution.
        extra_blocked: Additional regexes that always block.
        allowed_roots: Filesystem roots writes are restricted to. Empty means
            "home directory plus the project data folder".
    """

    confirm_dangerous: bool = True
    allow_shell: bool = True
    extra_blocked: Sequence[str] = field(default_factory=list)
    allowed_roots: Sequence[str] = field(default_factory=list)
    _confirm_hook: Optional[ConfirmHook] = field(default=None, repr=False)
    audit_log: List[Dict[str, str]] = field(default_factory=list, repr=False)

    # -- configuration ------------------------------------------------------
    @classmethod
    def from_config(cls, config: Dict) -> "SecurityGuard":
        """Build a guard from the ``security`` section of config.yaml."""
        section = config or {}
        return cls(
            confirm_dangerous=bool(section.get("confirm_dangerous", True)),
            allow_shell=bool(section.get("allow_shell", True)),
            extra_blocked=list(section.get("blocked_patterns", []) or []),
            allowed_roots=list(section.get("allowed_roots", []) or []),
        )

    def set_confirm_hook(self, hook: Optional[ConfirmHook]) -> None:
        """Install the coroutine used to ask the user for approval."""
        self._confirm_hook = hook

    # -- assessment ---------------------------------------------------------
    def assess(self, command: str) -> RiskAssessment:
        """Classify a shell command string.

        Args:
            command: The raw command line.

        Returns:
            A :class:`RiskAssessment` describing the risk level.
        """
        text = (command or "").strip()
        if not text:
            return RiskAssessment(RiskLevel.BLOCKED, "Empty command")

        if not self.allow_shell:
            return RiskAssessment(RiskLevel.BLOCKED, "Shell execution disabled in config")

        for pattern in list(_BLOCKED_PATTERNS) + list(self.extra_blocked):
            if re.search(pattern, text, re.IGNORECASE):
                return RiskAssessment(
                    RiskLevel.BLOCKED, "Matches a permanently blocked pattern", pattern
                )

        for pattern in _DANGEROUS_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return RiskAssessment(
                    RiskLevel.DANGEROUS, "Potentially destructive command", pattern
                )

        for pattern in _CAUTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return RiskAssessment(
                    RiskLevel.CAUTION, "Command writes files or uses the network", pattern
                )

        return RiskAssessment(RiskLevel.SAFE, "No risky patterns detected")

    def assess_code(self, code: str) -> RiskAssessment:
        """Classify a Python snippet destined for the sandbox."""
        text = code or ""
        for pattern in _SANDBOX_FORBIDDEN:
            if re.search(pattern, text):
                return RiskAssessment(
                    RiskLevel.DANGEROUS, "Code touches the filesystem, shell or network", pattern
                )
        return RiskAssessment(RiskLevel.SAFE, "Snippet looks inert")

    def is_path_allowed(self, path: str | Path, write: bool = False) -> RiskAssessment:
        """Check whether a path may be read from or written to.

        Args:
            path: The target path.
            write: True when the operation modifies the path.

        Returns:
            A :class:`RiskAssessment`; ``BLOCKED`` means refuse outright.
        """
        try:
            target = expand_path(path)
        except Exception as exc:
            return RiskAssessment(RiskLevel.BLOCKED, f"Unresolvable path: {exc}")

        target_str = str(target)
        for protected in _PROTECTED_ROOTS:
            if target_str == protected.rstrip("\\/") or target_str == protected:
                return RiskAssessment(
                    RiskLevel.BLOCKED, f"{target} is a protected system location"
                )

        if write:
            roots = [expand_path(root) for root in self.allowed_roots] or [
                Path.home(),
                Path.cwd(),
            ]
            if not any(self._is_within(target, root) for root in roots):
                return RiskAssessment(
                    RiskLevel.DANGEROUS,
                    f"{target} is outside the allowed roots "
                    f"({', '.join(str(r) for r in roots)})",
                )
            for protected in _PROTECTED_ROOTS:
                protected_path = Path(protected)
                if protected_path.is_absolute() and self._is_within(target, protected_path):
                    if not self._is_within(target, Path.home()):
                        return RiskAssessment(
                            RiskLevel.BLOCKED, f"{target} lives inside {protected}"
                        )
        return RiskAssessment(RiskLevel.SAFE, "Path is fine")

    @staticmethod
    def _is_within(child: Path, parent: Path) -> bool:
        """Return True when ``child`` is inside ``parent``."""
        try:
            child.relative_to(parent)
            return True
        except Exception:
            return False

    # -- gating -------------------------------------------------------------
    async def confirm(self, prompt: str) -> bool:
        """Ask the user to approve an action.

        Falls back to a terminal ``input()`` when no hook is registered, and
        denies by default in a non-interactive environment.
        """
        if self._confirm_hook is not None:
            try:
                return bool(await self._confirm_hook(prompt))
            except Exception as exc:  # pragma: no cover - UI failure
                logger.warning("Confirmation hook failed (%s); denying.", exc)
                return False
        try:
            loop = asyncio.get_running_loop()
            answer = await loop.run_in_executor(
                None, lambda: input(f"\n[confirm] {prompt} [y/N]: ")
            )
            return answer.strip().lower() in {"y", "yes", "yeah", "do it", "confirm"}
        except Exception:
            return False

    async def authorize(self, command: str, description: str = "") -> RiskAssessment:
        """Assess ``command`` and, if needed, obtain user confirmation.

        Returns:
            The assessment. ``level`` is ``BLOCKED`` if the command is banned
            or the user declined.
        """
        assessment = self.assess(command)
        self.audit_log.append(
            {"command": command, "level": assessment.level.value, "reason": assessment.reason}
        )

        if assessment.blocked:
            logger.warning("Blocked command: %s (%s)", command, assessment.reason)
            return assessment

        if assessment.needs_confirmation and self.confirm_dangerous:
            label = description or command
            question = (
                f"{label}\n  Risk: {assessment.level.value} — {assessment.reason}\n"
                f"  Shall I proceed?"
            )
            approved = await self.confirm(question)
            if not approved:
                return RiskAssessment(RiskLevel.BLOCKED, "User declined", assessment.matched)
        return assessment

    def recent_audit(self, limit: int = 10) -> List[Dict[str, str]]:
        """Return the most recent risk assessments for transparency."""
        return self.audit_log[-limit:]
