"""Read-only project, test, package and container helpers.

This plugin intentionally has no "command" parameter and never invokes a
shell. Every subprocess uses a fixed executable/argument list, a bounded
working directory and a timeout. It can inspect a project, run its standard
Python/Node test entry point, check Python dependencies, inspect npm packages,
and read Docker container/config status; it cannot install packages, mutate a
container, or run arbitrary shell text.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


PLUGIN = {
    "name": "project_helper",
    "description": (
        "Safe developer helper for a local project. Inspect project files, run a "
        "fixed Python or Node test helper, check Python/npm packages, or read Docker "
        "container status. No arbitrary shell command, package installation, container "
        "start/stop, deletion, checkout or network command is available."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "status | package_info | test | python_packages | node_packages | containers | docker_validate",
            },
            "path": {
                "type": "STRING",
                "description": "Local project directory or a relative path; defaults to MARK's project",
            },
            "test_kind": {
                "type": "STRING",
                "description": "python_compile | python_unittest | python_pytest | node_test",
            },
            "target": {
                "type": "STRING",
                "description": "Optional relative test/file target inside the project",
            },
        },
        "required": ["action"],
    },
}


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SECRET_PARTS = ("PASSWORD", "TOKEN", "SECRET", "API_KEY", "PRIVATE_KEY")


def _root(value: str) -> Path:
    raw = str(value or "").strip()
    candidate = Path(raw).expanduser() if raw else _PROJECT_ROOT
    if not candidate.is_absolute():
        candidate = (_PROJECT_ROOT / candidate)
    candidate = candidate.resolve()
    if candidate.is_file():
        candidate = candidate.parent
    if not candidate.exists() or not candidate.is_dir():
        raise ValueError("That project directory does not exist.")
    return candidate


def _safe_target(root: Path, value: str) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    target = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("The target must stay inside the selected project.") from exc
    if not target.exists():
        raise ValueError("That project target does not exist.")
    return target


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in list(env):
        upper = key.upper()
        if any(part in upper for part in _SECRET_PARTS):
            env.pop(key, None)
    return env


def _run(argv: list[str], root: Path, timeout: int = 45) -> str:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(root),
            env=_clean_env(),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return f"Not available: {argv[0]}"
    except subprocess.TimeoutExpired as exc:
        output = (exc.output or "") if isinstance(exc.output, str) else ""
        return f"Timed out after {timeout}s.\n{output[-5000:]}"
    except Exception as exc:
        return f"Could not run the fixed helper: {exc}"
    output = (completed.stdout or "").strip()
    if len(output) > 6000:
        output = output[-6000:]
        output = "[output truncated]\n" + output
    return f"exit {completed.returncode}\n{output}" if output else f"exit {completed.returncode}"


def _status(root: Path) -> str:
    known = {
        ".git": "Git repository",
        "pyproject.toml": "Python project metadata",
        "setup.py": "Python setup",
        "requirements.txt": "Python requirements",
        "package.json": "Node package",
        "package-lock.json": "npm lockfile",
        "pnpm-lock.yaml": "pnpm lockfile",
        "yarn.lock": "Yarn lockfile",
        "Dockerfile": "Dockerfile",
        "docker-compose.yml": "Docker Compose",
        "docker-compose.yaml": "Docker Compose",
        "compose.yml": "Docker Compose",
        "compose.yaml": "Docker Compose",
    }
    found = [label for name, label in known.items() if (root / name).exists()]
    try:
        entries = sorted(p.name for p in root.iterdir() if not p.name.startswith("."))
    except OSError as exc:
        return f"Project: {root}\nCould not list files: {exc}"
    listing = ", ".join(entries[:80])
    if len(entries) > 80:
        listing += ", …"
    return (
        f"Project: {root}\nDetected: {', '.join(found) if found else 'no standard manifests'}\n"
        f"Top-level files: {listing or '(empty)'}"
    )


def _package_manifest(root: Path) -> str:
    rows = []
    for filename in ("pyproject.toml", "requirements.txt", "package.json", "Dockerfile"):
        path = root / filename
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            rows.append(f"{filename}: {exc}")
            continue
        if filename == "package.json":
            try:
                data = json.loads(text)
                deps = sorted(set((data.get("dependencies") or {}).keys())
                               | set((data.get("devDependencies") or {}).keys()))
                rows.append(f"package.json: {data.get('name', '(unnamed)')} — {', '.join(deps) or 'no dependencies'}")
            except Exception:
                rows.append("package.json: invalid JSON")
        else:
            lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
            rows.append(f"{filename}: " + " | ".join(lines[:30]))
    return "\n".join(rows) if rows else "No supported package manifest found."


def _test(root: Path, kind: str, target: Path | None) -> str:
    relative = str(target.relative_to(root)) if target else ""
    if kind == "python_compile":
        # compileall is a fixed Python module invocation, not a shell command.
        return _run([sys.executable, "-m", "compileall", "-q", relative or "."], root, 60)
    if kind == "python_unittest":
        argv = [sys.executable, "-m", "unittest", "discover"]
        if relative:
            argv.extend(["-s", relative])
        return _run(argv, root, 120)
    if kind == "python_pytest":
        argv = [sys.executable, "-m", "pytest", "-q"]
        if relative:
            argv.append(relative)
        return _run(argv, root, 120)
    if kind == "node_test":
        if not (root / "package.json").exists():
            return "No package.json was found in that project."
        # npm chooses only the project's declared test script. No shell text or
        # additional user arguments are accepted here.
        return _run(["npm", "test"], root, 120)
    return "Unknown test_kind. Use python_compile, python_unittest, python_pytest or node_test."


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()
    try:
        root = _root(params.get("path", ""))
        target = _safe_target(root, params.get("target", ""))
    except ValueError as exc:
        return str(exc)

    if action == "status":
        result = _status(root)
    elif action == "package_info":
        result = _package_manifest(root)
    elif action == "python_packages":
        result = _run([sys.executable, "-m", "pip", "check"], root)
    elif action == "node_packages":
        if not (root / "package.json").exists():
            result = "No package.json was found in that project."
        else:
            result = _run(["npm", "ls", "--depth=0"], root, 60)
    elif action == "containers":
        result = _run(["docker", "ps", "--all", "--format", "{{.Names}} | {{.Image}} | {{.Status}}"], root, 30)
    elif action == "docker_validate":
        compose = next((root / name for name in ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml") if (root / name).exists()), None)
        if compose is None:
            result = "No Docker Compose file was found."
        else:
            result = _run(["docker", "compose", "config", "--quiet"], root, 30)
    elif action == "test":
        result = _test(root, str(params.get("test_kind", "python_compile")).strip().lower(), target)
    else:
        return "Unknown project action. Use status, package_info, test, python_packages, node_packages, containers or docker_validate."

    if player:
        try:
            player.write_log(f"[Project] {action} in {root}")
        except Exception:
            pass
    return result
