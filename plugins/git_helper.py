"""Safe, read-only Git information for MARK.

This plugin deliberately does not commit, reset, checkout, push, pull or delete
anything. It is for answering questions about a repository's current state.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


PLUGIN = {
    "name": "git_helper",
    "description": (
        "Read-only Git assistant for repository status, changes, recent commits, "
        "branches, remotes and repository root. Use this for Git questions; do not "
        "use it to modify, commit, reset, checkout, push or pull files."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "status | diff | log | branches | remotes | root",
            },
            "path": {
                "type": "STRING",
                "description": "Repository folder or file path; defaults to the current project",
            },
            "limit": {
                "type": "INTEGER",
                "description": "Number of recent commits for log (default: 8)",
            },
        },
        "required": ["action"],
    },
}


_MAX_OUTPUT = 7000


def _repo_path(raw: str) -> Path:
    default_repo = Path(__file__).resolve().parent.parent
    path = Path(raw).expanduser() if str(raw or "").strip() else default_repo
    if path.is_file():
        path = path.parent
    return path.resolve()


def _git(repo: Path, *args: str) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return 127, "", "Git is not installed or is not on PATH."
    except subprocess.TimeoutExpired:
        return 124, "", "Git took too long to respond."
    except Exception as exc:
        return 1, "", str(exc)


def _shorten(text: str) -> str:
    if len(text) <= _MAX_OUTPUT:
        return text
    return text[:_MAX_OUTPUT] + "\n… output truncated."


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()
    repo = _repo_path(str(params.get("path", "")))

    commands = {
        "status": ("status", "--short", "--branch"),
        "diff": ("diff", "--stat"),
        "branches": ("branch", "--all", "--no-color"),
        "remotes": ("remote", "-v"),
        "root": ("rev-parse", "--show-toplevel"),
    }
    if action == "log":
        try:
            limit = max(1, min(30, int(params.get("limit", 8))))
        except (TypeError, ValueError):
            limit = 8
        command = ("log", f"-{limit}", "--oneline", "--decorate", "--no-color")
    else:
        command = commands.get(action)

    if command is None:
        return "Unknown Git action. Use status, diff, log, branches, remotes or root."
    if not repo.exists() or not repo.is_dir():
        return f"Repository folder not found: {repo}"

    code, stdout, stderr = _git(repo, *command)
    if code != 0:
        detail = stderr or stdout or "Git returned an error."
        return f"Git {action} failed in {repo}: {detail}"

    result = stdout or "No output."
    answer = f"Git {action} for {repo}:\n{_shorten(result)}"
    if player:
        try:
            player.write_log(f"[Git] {action}: {repo}")
        except Exception:
            pass
    return answer
