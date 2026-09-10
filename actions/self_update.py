"""Review-first source maintenance for MARK itself.

This action intentionally does not edit the live checkout while the model is
working. It makes a detached Git worktree, asks Ollama for a unified diff,
applies and tests that diff there, shows the resulting diff, and only then
hands the exact patch to the human confirmation gate. No shell command is
accepted from the model or the user; test modes map to fixed Python commands.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from core import confirm as confirm_gate


BASE_DIR = Path(__file__).resolve().parent.parent
_MAX_FILES = 4
_MAX_FILE_CHARS = 9_000
_MAX_PATCH_CHARS = 120_000
_ALLOWED_SUFFIXES = {".py"}


def _git(args: list[str], cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), text=True, capture_output=True,
        timeout=timeout, check=False,
    )


def _safe_files(raw) -> tuple[list[Path], str | None]:
    values = raw if isinstance(raw, list) else [x.strip() for x in str(raw or "").split(",") if x.strip()]
    if not values:
        return [], "Provide one or more repository-relative Python files to inspect."
    if len(values) > _MAX_FILES:
        return [], f"Review is limited to {_MAX_FILES} files at a time."

    result: list[Path] = []
    root = BASE_DIR.resolve()
    for value in values:
        candidate = Path(str(value).strip())
        if candidate.is_absolute():
            return [], "Files must be repository-relative; absolute paths are not accepted."
        resolved = (root / candidate).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            return [], f"File is outside the MARK repository: {value}"
        if resolved.suffix.lower() not in _ALLOWED_SUFFIXES:
            return [], f"Only Python source files can be changed by self_update: {value}"
        if not resolved.is_file():
            return [], f"File not found: {value}"
        result.append(resolved)
    return result, None


def _relative(path: Path) -> str:
    return path.resolve().relative_to(BASE_DIR.resolve()).as_posix()


def _read_sources(files: list[Path]) -> str:
    parts = []
    for path in files:
        content = path.read_text(encoding="utf-8", errors="replace")
        parts.append(f"\n--- { _relative(path) } ---\n{content[:_MAX_FILE_CHARS]}")
    return "".join(parts)


def _extract_patch(text: str) -> str:
    text = str(text or "").replace("\r\n", "\n").strip()
    text = re.sub(r"^```(?:diff|patch)?\s*\n", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n```\s*$", "", text)
    start = text.find("diff --git ")
    if start >= 0:
        text = text[start:]
    return text.strip()


def _changed_files(worktree: Path) -> list[str]:
    result = _git(["diff", "--name-only", "--diff-filter=ACMRT"], worktree)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _apply_patch(worktree: Path, patch: str) -> tuple[bool, str]:
    check = subprocess.run(
        ["git", "apply", "--check", "--recount", "--whitespace=nowarn", "-"],
        cwd=str(worktree), input=patch, text=True, capture_output=True, timeout=30,
    )
    if check.returncode:
        return False, check.stderr.strip() or "git apply --check rejected the proposed patch."
    applied = subprocess.run(
        ["git", "apply", "--recount", "--whitespace=nowarn", "-"],
        cwd=str(worktree), input=patch, text=True, capture_output=True, timeout=30,
    )
    if applied.returncode:
        return False, applied.stderr.strip() or "The proposed patch could not be applied."
    return True, "Patch applied in the isolated review worktree."


def _run_tests(worktree: Path, mode: str, changed: list[str]) -> tuple[bool, str]:
    mode = str(mode or "auto").lower().strip()
    if mode not in {"auto", "compile", "pytest", "both"}:
        return False, "Test mode must be auto, compile, pytest or both."

    commands: list[list[str]] = []
    if mode in {"auto", "compile", "both"}:
        commands.append([sys.executable, "-m", "compileall", "-q", *changed])
    has_tests = any((worktree / name).exists() for name in ("tests", "pytest.ini", "pyproject.toml", "setup.cfg"))
    if mode in {"pytest", "both"} or (mode == "auto" and has_tests):
        commands.append([sys.executable, "-m", "pytest", "-q"])

    if not commands:
        return True, "Compile check passed; no test suite marker was found, so pytest was skipped."

    reports = []
    for command in commands:
        try:
            result = subprocess.run(
                command, cwd=str(worktree), text=True, capture_output=True,
                timeout=180, check=False,
            )
        except subprocess.TimeoutExpired:
            return False, f"Test timed out: {' '.join(command)}"
        output = (result.stdout + "\n" + result.stderr).strip()
        reports.append(f"$ {' '.join(command)}\n{output[-5000:]}")
        if result.returncode:
            return False, "\n\n".join(reports)
    return True, "\n\n".join(reports)


def _remove_worktree(path: Path) -> None:
    try:
        if path.exists():
            result = _git(["worktree", "remove", "--force", str(path)], BASE_DIR, timeout=30)
            if result.returncode:
                shutil.rmtree(path, ignore_errors=True)
    except Exception:
        shutil.rmtree(path, ignore_errors=True)


def _apply_live(patch: str, files: list[str], worktree: Path, player=None) -> str:
    try:
        # Re-check against the live tree immediately before the user-approved
        # apply. Existing edits therefore cause a refusal instead of being
        # silently overwritten.
        check = subprocess.run(
            ["git", "apply", "--check", "--recount", "--whitespace=nowarn", "-"],
            cwd=str(BASE_DIR), input=patch, text=True, capture_output=True, timeout=30,
        )
        if check.returncode:
            return "The live checkout changed since review, so the patch was not applied: " + (check.stderr.strip() or "conflict")
        applied = subprocess.run(
            ["git", "apply", "--recount", "--whitespace=nowarn", "-"],
            cwd=str(BASE_DIR), input=patch, text=True, capture_output=True, timeout=30,
        )
        if applied.returncode:
            return "The reviewed patch failed to apply to the live checkout: " + (applied.stderr.strip() or "unknown error")
        if player:
            player.write_log(f"[Self-update] Applied reviewed patch to {', '.join(files)}")
            try:
                player.show_content("CODE REVIEW — APPLIED", f"Applied after confirmation:\n\n{patch}")
            except Exception:
                pass
        return f"Reviewed patch applied to the live checkout: {', '.join(files)}"
    finally:
        _remove_worktree(worktree)


def _review(parameters: dict, player=None) -> str:
    files, error = _safe_files(parameters.get("files"))
    if error:
        return error
    mode = str(parameters.get("test_mode", "auto"))
    instruction = str(parameters.get("instruction", "")).strip()
    if not instruction:
        return "Provide the requested code change in instruction."

    status = _git(["rev-parse", "--is-inside-work-tree"], BASE_DIR)
    if status.returncode or status.stdout.strip() != "true":
        return "The MARK directory is not a Git worktree; no self-update was attempted."
    relative_files = [_relative(p) for p in files]
    tracked = _git(["ls-files", "--error-unmatch", "--", *relative_files], BASE_DIR)
    if tracked.returncode:
        return "Self-update only reviews tracked Python files; add the requested file to Git first."
    dirty = _git(["diff", "--name-only", "HEAD", "--", *relative_files], BASE_DIR)
    if dirty.returncode or dirty.stdout.strip():
        return "The requested files have uncommitted changes. Commit or stash them before requesting a self-update review."

    worktree = BASE_DIR.parent / f".mark-review-{uuid.uuid4().hex}"
    added = _git(["worktree", "add", "--detach", str(worktree), "HEAD"], BASE_DIR, timeout=60)
    if added.returncode:
        return "Could not create the isolated Git review worktree: " + (added.stderr.strip() or "unknown error")

    try:
        sources = _read_sources(files)
        from core.llm_client import call_llm_text, get_llm_settings
        _, main_model = get_llm_settings()
        prompt = f"""You are preparing a small, reviewable change to the MARK Python repository.
Return ONLY a valid unified Git patch. Do not return Markdown, explanations, shell commands, or files outside the requested list.

Requested change:
{instruction}

Files you may change (and no others):
{', '.join(_relative(p) for p in files)}

Current source:
{sources}

Rules:
- Preserve existing safety boundaries, confirmation gates, Ollama-only backend, and Edge TTS default.
- Make the smallest coherent change.
- The patch must use paths relative to the repository and include diff --git headers.
- Do not add credentials, arbitrary command execution, network listeners, or destructive fallbacks.
- Return an empty patch only if the request is already satisfied.
"""
        generated = call_llm_text(prompt, model=main_model, num_predict=5000, timeout=300)
        patch = _extract_patch(generated)
        if not patch or "diff --git " not in patch:
            _remove_worktree(worktree)
            return "The model did not produce a unified patch, so no files were changed."
        if len(patch) > _MAX_PATCH_CHARS:
            _remove_worktree(worktree)
            return "The proposed patch is too large for the review gate."

        ok, result = _apply_patch(worktree, patch)
        if not ok:
            _remove_worktree(worktree)
            return "Patch review rejected it before testing: " + result
        changed = _changed_files(worktree)
        allowed = {_relative(p) for p in files}
        if not changed or not set(changed).issubset(allowed):
            _remove_worktree(worktree)
            return "Patch review rejected changes outside the requested file list."
        tested, test_report = _run_tests(worktree, mode, changed)
        diff = _git(["diff", "--no-ext-diff", "--unified=3", "--", *changed], worktree, timeout=30).stdout
        review = (
            f"Files: {', '.join(changed)}\n"
            f"Tests: {'PASS' if tested else 'FAIL'}\n\n{test_report}\n\n"
            f"Diff:\n{diff[:100000]}"
        )
        if player:
            player.write_log(f"[Self-update] Review prepared for {', '.join(changed)}")
            try:
                player.show_content("CODE REVIEW — ISOLATED PATCH", review)
            except Exception:
                pass
        if not tested:
            _remove_worktree(worktree)
            return "The isolated patch was not applied because its tests failed.\n\n" + review

        detail = (
            f"The isolated worktree patch passed {mode} checks and changed {', '.join(changed)}. "
            "The full diff is shown in the CODE REVIEW panel. Apply it to MARK's live checkout?"
        )
        if confirm_gate.pending_title():
            _remove_worktree(worktree)
            return "There is already a confirmation waiting on screen. Answer it before applying another change."
        result = confirm_gate.request(
            "self_update_apply",
            "Apply reviewed code patch",
            detail,
            lambda: _apply_live(patch, changed, worktree, player=player),
        )
        # A cancelled/expired confirmation has no callback in the generic gate;
        # keep the isolated directory bounded and let an accepted callback clean
        # it sooner if it runs.
        threading.Timer(95.0, _remove_worktree, args=(worktree,)).start()
        return result + "\n\n" + review
    except Exception as exc:
        _remove_worktree(worktree)
        return f"Self-update review failed safely: {exc}"


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "review")).lower().strip()
    if action == "inspect":
        files, error = _safe_files(params.get("files"))
        if error:
            return error
        report = _read_sources(files)
        if player:
            try:
                player.show_content("CODE REVIEW — FILE INSPECTION", report)
            except Exception:
                pass
        return "Inspected files in read-only mode:\n" + ", ".join(_relative(p) for p in files)
    if action == "review":
        return _review(params, player=player)
    return "Use action inspect (read-only) or review (isolated patch, tests, diff, then confirmation)."


TOOL = {
    "name": "self_update",
    "description": (
        "Review-first MARK source maintenance. Inspect Python files, generate a unified patch in a detached Git worktree, run fixed compile/pytest checks, show the diff, and ask the human before applying it to the live checkout. It never accepts shell commands or arbitrary paths."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": ["inspect", "review"], "description": "inspect or review"},
            "files": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Repository-relative Python files"},
            "instruction": {"type": "STRING", "description": "Requested change for review"},
            "test_mode": {"type": "STRING", "enum": ["auto", "compile", "pytest", "both"], "description": "Fixed test policy; default auto"},
        },
        "required": ["action", "files"],
    },
    "handler": run,
}
