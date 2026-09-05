# /modules/code_assistant.py
"""Coding help: write, explain, debug, test, save and safely run code."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.helpers import (
    ensure_dir,
    extract_code_blocks,
    python_executable,
    read_text_file,
    resolve_user_path,
    run_command,
    safe_filename,
    slugify,
    truncate,
)

LANGUAGE_EXTENSIONS: Dict[str, str] = {
    "python": ".py",
    "py": ".py",
    "javascript": ".js",
    "js": ".js",
    "typescript": ".ts",
    "bash": ".sh",
    "shell": ".sh",
    "sh": ".sh",
    "html": ".html",
    "css": ".css",
    "sql": ".sql",
    "json": ".json",
    "yaml": ".yaml",
    "go": ".go",
    "rust": ".rs",
    "java": ".java",
    "c": ".c",
    "cpp": ".cpp",
    "text": ".txt",
}


class CodeAssistant(BaseModule):
    """Generate, explain, debug and execute code with the local LLM."""

    name = "code_assistant"
    description = (
        "Programming help: write code from a description, explain existing code, debug "
        "errors, generate unit tests, save snippets to files and run Python in a sandbox."
    )
    intent_examples = [
        "write a python script that renames files",
        "explain this code",
        "debug this traceback",
        "run this python snippet",
    ]

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Prepare the code output directory and sandbox settings."""
        super().__init__(config, llm=llm, security=security)
        self.code_dir: Path = config.path_for("code")
        self.sandbox_timeout = float(config.get("security.sandbox_timeout", 20))
        self.last_code: str = ""
        self.last_language: str = "python"

    # ------------------------------------------------------------------ utils
    def _require_llm(self) -> Optional[ModuleResult]:
        """Return an error result when no LLM is available."""
        if self.llm is None or not getattr(self.llm, "available", False):
            return ModuleResult.fail(
                "That needs the language model, and Ollama isn't responding. "
                "Start it with 'ollama serve'."
            )
        return None

    @staticmethod
    def _first_code(text: str, fallback_language: str = "python") -> tuple[str, str]:
        """Extract the first fenced code block, or treat the whole text as code."""
        blocks = extract_code_blocks(text)
        if blocks:
            language, code = blocks[0]
            return (language or fallback_language), code
        return fallback_language, text.strip()

    def _resolve_source(self, code: str) -> str:
        """Resolve ``code`` that may be a path, a fenced block, or raw source."""
        candidate = (code or "").strip()
        if not candidate:
            return self.last_code
        if len(candidate) < 400 and "\n" not in candidate:
            path = resolve_user_path(candidate)
            if path.exists() and path.is_file():
                return read_text_file(path, 80_000)
        _, extracted = self._first_code(candidate)
        return extracted or candidate

    # ---------------------------------------------------------- offline route
    def offline_router(self, command: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """Rule-based routing with parameter extraction (used without an LLM)."""
        text = strip_command_prefix(command)
        lowered = text.lower()

        if any(phrase in lowered for phrase in ("run this", "run the code", "execute python",
                                                "run it", "execute the snippet")):
            return "run_python", {"code": text}

        if any(phrase in lowered for phrase in ("explain this code", "explain the code",
                                                "what does this code", "walk me through")):
            return "explain_code", {"code": text}

        if any(phrase in lowered for phrase in ("debug", "fix this", "why does this fail",
                                                "traceback", "this is broken")):
            return "debug_code", {"code": text}

        if any(phrase in lowered for phrase in ("refactor", "clean up this code",
                                                "optimize this code")):
            return "refactor_code", {"code": text}

        if any(phrase in lowered for phrase in ("write tests", "unit test", "pytest")):
            return "write_tests", {"code": text}

        if any(phrase in lowered for phrase in ("save this code", "save it to", "save the script")):
            filename = re.search(r"(?:as|to|in)\s+([\w./~-]+)", lowered)
            return "save_code", {"filename": filename.group(1) if filename else ""}

        if any(phrase in lowered for phrase in ("python version", "environment info",
                                                "which packages", "pip list")):
            return "environment_info", {}

        language = "python"
        for candidate in ("python", "javascript", "typescript", "bash", "go", "rust", "sql",
                          "java", "html", "css"):
            if candidate in lowered:
                language = candidate
                break
        return "write_code", {"description": text, "language": language}

    # ------------------------------------------------------------------ write
    @tool(
        description="Write code from a plain-English description.",
        params={
            "description": {
                "type": "string",
                "description": "What the code should do",
                "required": True,
            },
            "language": {"type": "string", "description": "Language", "default": "python"},
            "save_as": {
                "type": "string",
                "description": "Optional filename to save the result",
                "default": "",
            },
        },
        keywords=["write a script", "write code", "write a function", "code for", "program that",
                  "implement", "create a class"],
        examples=['write_code(description="rename all jpgs by date", language="python")'],
    )
    async def write_code(
        self, description: str, language: str = "python", save_as: str = ""
    ) -> ModuleResult:
        """Generate code and optionally save it to disk."""
        error = self._require_llm()
        if error:
            return error
        brief = (description or "").strip()
        if not brief:
            return ModuleResult.fail("Describe what the code should do, sir.")

        language = (language or "python").lower()
        prompt = (
            f"Write {language} code that does the following:\n{brief}\n\n"
            "Requirements: complete and runnable, no placeholders or TODOs, standard library "
            "where possible, brief docstrings, type hints if the language supports them, and "
            "graceful error handling. Output exactly one fenced code block, then one sentence "
            "of explanation."
        )
        raw = await self.llm.complete(prompt, temperature=0.2, max_tokens=1400)
        if not raw.strip():
            return ModuleResult.fail("The model returned nothing. Is it still loading?")

        detected, code = self._first_code(raw, language)
        self.last_code, self.last_language = code, detected

        data: Dict[str, Any] = {"language": detected, "code": code}
        output = raw.strip()

        if save_as:
            saved = await self.save_code(code=code, filename=save_as, language=detected)
            data["path"] = saved.data.get("path", "")
            output += f"\n\n{saved.output}"

        return ModuleResult(
            success=True,
            output=output,
            speak=f"Written. {truncate(brief, 80)}."
            + (f" Saved to {Path(data['path']).name}." if data.get("path") else ""),
            data=data,
        )

    @tool(
        description="Explain what a piece of code does (accepts code or a file path).",
        params={
            "code": {"type": "string", "description": "Source code or file path", "required": True},
            "detail": {"type": "string", "description": "brief or deep", "default": "brief"},
        },
        keywords=["explain this code", "what does this code do", "walk me through this code",
                  "review this code"],
    )
    async def explain_code(self, code: str, detail: str = "brief") -> ModuleResult:
        """Explain code in plain English."""
        error = self._require_llm()
        if error:
            return error
        source = self._resolve_source(code)
        if not source:
            return ModuleResult.fail("Give me some code or a file path to look at.")

        depth = (
            "Give a line-by-line walkthrough, then note complexity and edge cases."
            if str(detail).startswith("deep")
            else "Explain the purpose, the flow in 3-5 bullet points, and any obvious risks."
        )
        answer = await self.llm.complete(
            f"Explain this code.\n\n```\n{truncate(source, 8000)}\n```\n\n{depth}",
            temperature=0.3,
            max_tokens=800,
        )
        return ModuleResult.ok(answer.strip() or "The model had no comment.")

    @tool(
        description="Find and fix a bug, given code and optionally an error message.",
        params={
            "code": {"type": "string", "description": "Source code or file path", "required": True},
            "error": {"type": "string", "description": "Error/traceback", "default": ""},
        },
        keywords=["debug", "fix this code", "why does this fail", "traceback", "this is broken",
                  "error in my code"],
    )
    async def debug_code(self, code: str, error: str = "") -> ModuleResult:
        """Diagnose and repair code."""
        problem = self._require_llm()
        if problem:
            return problem
        source = self._resolve_source(code)
        if not source:
            return ModuleResult.fail("No code to debug.")

        prompt = (
            "Debug this code.\n\n"
            f"```\n{truncate(source, 8000)}\n```\n"
            + (f"\nReported error:\n{truncate(error, 1500)}\n" if error else "")
            + "\nRespond with: (1) the root cause in one or two sentences, (2) the corrected "
            "code in a single fenced block, (3) one line on how to verify the fix."
        )
        answer = await self.llm.complete(prompt, temperature=0.2, max_tokens=1400)
        detected, fixed = self._first_code(answer, self.last_language)
        if fixed:
            self.last_code, self.last_language = fixed, detected
        return ModuleResult(
            success=True,
            output=answer.strip() or "No diagnosis produced.",
            speak="I found the problem and patched it — the corrected code is on screen.",
            data={"fixed_code": fixed, "language": detected},
        )

    @tool(
        description="Improve or refactor existing code.",
        params={
            "code": {"type": "string", "description": "Source code or path", "required": True},
            "goal": {
                "type": "string",
                "description": "readability, performance, tests…",
                "default": "readability and robustness",
            },
        },
        keywords=["refactor", "clean up this code", "optimize this code", "improve this code"],
    )
    async def refactor_code(
        self, code: str, goal: str = "readability and robustness"
    ) -> ModuleResult:
        """Rewrite code toward a stated goal."""
        error = self._require_llm()
        if error:
            return error
        source = self._resolve_source(code)
        if not source:
            return ModuleResult.fail("No code supplied.")
        answer = await self.llm.complete(
            f"Refactor this code for {goal}. Keep behaviour identical. "
            "Return one fenced code block followed by a short bullet list of the changes.\n\n"
            f"```\n{truncate(source, 8000)}\n```",
            temperature=0.2,
            max_tokens=1500,
        )
        detected, refactored = self._first_code(answer, self.last_language)
        if refactored:
            self.last_code, self.last_language = refactored, detected
        return ModuleResult.ok(answer.strip() or "Nothing to change, apparently.")

    @tool(
        description="Generate unit tests for a piece of code.",
        params={
            "code": {"type": "string", "description": "Source code or path", "required": True},
            "framework": {"type": "string", "description": "pytest/unittest", "default": "pytest"},
        },
        keywords=["write tests", "unit test", "test this code", "pytest"],
    )
    async def write_tests(self, code: str, framework: str = "pytest") -> ModuleResult:
        """Produce a test suite for the given code."""
        error = self._require_llm()
        if error:
            return error
        source = self._resolve_source(code)
        if not source:
            return ModuleResult.fail("No code supplied.")
        answer = await self.llm.complete(
            f"Write {framework} tests covering the happy path, edge cases and failure modes "
            f"for this code. Output one fenced code block only.\n\n```\n{truncate(source, 7000)}\n```",
            temperature=0.2,
            max_tokens=1200,
        )
        _, tests = self._first_code(answer, "python")
        return ModuleResult(success=True, output=answer.strip(), data={"tests": tests})

    # -------------------------------------------------------------------- run
    @tool(
        description="Run a Python snippet in a sandboxed subprocess with a timeout.",
        params={
            "code": {"type": "string", "description": "Python source", "default": ""},
            "timeout": {"type": "integer", "description": "Seconds", "default": 0},
        },
        dangerous=False,
        keywords=["run this code", "execute python", "run the script", "try running", "test this code"],
    )
    async def run_python(self, code: str = "", timeout: int = 0) -> ModuleResult:
        """Execute Python in a temporary directory as a separate process.

        The snippet is risk-assessed first; anything touching the filesystem,
        shell or network requires confirmation.
        """
        source = self._resolve_source(code) or self.last_code
        if not source.strip():
            return ModuleResult.fail("No code to run.")

        if self.security is not None:
            assessment = self.security.assess_code(source)
            if assessment.needs_confirmation and self.security.confirm_dangerous:
                approved = await self.security.confirm(
                    f"This snippet {assessment.reason.lower()}. Run it anyway?"
                )
                if not approved:
                    return ModuleResult.fail("Execution cancelled.")

        limit = float(timeout) if timeout else self.sandbox_timeout
        with tempfile.TemporaryDirectory(prefix="jarvis-sandbox-") as workdir:
            script = Path(workdir) / "snippet.py"
            script.write_text(source, encoding="utf-8")
            environment = {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "HOME": workdir,
            }
            code_returned, out, err = await run_command(
                [python_executable(), "-I", str(script)],
                timeout=limit,
                cwd=workdir,
                env=environment,
            )

        if code_returned == -9:
            return ModuleResult.fail(f"Execution timed out after {limit:.0f}s.")

        body = ""
        if out:
            body += f"stdout:\n{truncate(out, 3000)}"
        if err:
            body += ("\n\n" if body else "") + f"stderr:\n{truncate(err, 2000)}"
        body = body or "(no output)"

        success = code_returned == 0
        return ModuleResult(
            success=success,
            output=f"Exit code {code_returned}.\n{body}",
            error="" if success else truncate(err, 400),
            speak="It ran cleanly." if success else "It failed — details on screen.",
            data={"exit_code": code_returned, "stdout": out, "stderr": err},
        )

    # ------------------------------------------------------------------- save
    @tool(
        description="Save code to a file.",
        params={
            "code": {"type": "string", "description": "Source (blank = last generated)",
                     "default": ""},
            "filename": {"type": "string", "description": "File name or path", "required": True},
            "language": {"type": "string", "description": "Language for the extension",
                         "default": ""},
        },
        keywords=["save this code", "save to file", "write it to", "export the script"],
    )
    async def save_code(
        self, filename: str, code: str = "", language: str = ""
    ) -> ModuleResult:
        """Write code to ``filename`` (relative names land in ``paths.code``)."""
        source = self._resolve_source(code) or self.last_code
        if not source.strip():
            return ModuleResult.fail("There's no code to save.")

        language = (language or self.last_language or "python").lower()
        extension = LANGUAGE_EXTENSIONS.get(language, ".txt")
        name = (filename or "").strip() or f"snippet-{datetime.now():%Y%m%d-%H%M%S}"

        target = Path(name).expanduser()
        if not target.is_absolute():
            ensure_dir(self.code_dir)
            target = self.code_dir / safe_filename(slugify(target.stem) + target.suffix)
        if not target.suffix:
            target = target.with_suffix(extension)

        if self.security is not None:
            assessment = self.security.is_path_allowed(target, write=True)
            if assessment.blocked:
                return ModuleResult.fail(f"Refused: {assessment.reason}")

        try:
            ensure_dir(target.parent)
            target.write_text(source, encoding="utf-8")
            if extension == ".sh":
                os.chmod(target, 0o755)
        except Exception as exc:
            return ModuleResult.fail(f"Could not write {target}: {exc}")

        return ModuleResult(
            success=True,
            output=f"Saved {len(source.splitlines())} lines to {target}",
            speak=f"Saved to {target.name}.",
            data={"path": str(target)},
        )

    @tool(
        description="Read a source file from disk and show it.",
        params={
            "path": {"type": "string", "description": "File path", "required": True},
            "max_lines": {"type": "integer", "description": "Line cap", "default": 200},
        },
        keywords=["show me the file", "open the script", "read the source", "cat the file"],
    )
    async def read_code(self, path: str, max_lines: int = 200) -> ModuleResult:
        """Load a source file into context (and remember it for follow-ups)."""
        target = resolve_user_path(path)
        if not target.exists() or not target.is_file():
            return ModuleResult.fail(f"No file at {target}.")
        content = read_text_file(target, 200_000)
        lines = content.splitlines()
        shown = "\n".join(lines[: int(max_lines)])
        self.last_code = content
        self.last_language = {
            ".py": "python", ".js": "javascript", ".ts": "typescript", ".sh": "bash",
            ".sql": "sql", ".go": "go", ".rs": "rust",
        }.get(target.suffix.lower(), "text")
        suffix = f"\n… ({len(lines) - int(max_lines)} more lines)" if len(lines) > int(max_lines) else ""
        return ModuleResult(
            success=True,
            output=f"{target} ({len(lines)} lines):\n{shown}{suffix}",
            speak=f"Loaded {target.name}, {len(lines)} lines.",
            data={"path": str(target), "lines": len(lines)},
        )

    @tool(
        description="Check the Python environment: version, interpreter and key packages.",
        params={},
        keywords=["python version", "which packages", "environment info", "pip list"],
    )
    async def environment_info(self) -> ModuleResult:
        """Report interpreter details and whether key packages are importable."""
        import importlib.util

        packages = [
            "httpx", "chromadb", "duckduckgo_search", "edge_tts", "faster_whisper",
            "sounddevice", "pvporcupine", "pyautogui", "psutil", "bs4", "pandas", "rich",
        ]
        installed = {
            package: bool(importlib.util.find_spec(package.replace("-", "_")))
            for package in packages
        }
        missing = [name for name, present in installed.items() if not present]
        lines = [
            f"Python {sys.version.split()[0]} at {python_executable()}",
            f"Virtualenv: {sys.prefix != getattr(sys, 'base_prefix', sys.prefix)}",
            "Installed: " + ", ".join(name for name, ok in installed.items() if ok),
        ]
        if missing:
            lines.append("Missing: " + ", ".join(missing))
        return ModuleResult(
            success=True, output="\n".join(lines), data={"installed": installed, "missing": missing}
        )


__all__ = ["CodeAssistant"]
