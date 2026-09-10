"""Install MARK and create a desktop launcher.

This is the cross-platform installer used by the small platform wrappers in this
folder. It intentionally installs into the checkout/prefix supplied by the
user, so MARK can write its local settings without administrator privileges.

Examples:
    python installer/install.py
    python installer/install.py --skip-dependencies
    python installer/install.py --root "$HOME/Applications/MARK"
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import shlex
import subprocess
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "MARK"


def say(message: str) -> None:
    print(f"[MARK installer] {message}", flush=True)


def run(label: str, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    say(label)
    return subprocess.run(args, check=check)


def python_in_venv(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def make_venv(root: Path) -> Path:
    venv = root / ".venv"
    python = python_in_venv(venv)
    if not python.exists():
        run("Creating the private Python environment…", [sys.executable, "-m", "venv", str(venv)])
    if not python.exists():
        raise RuntimeError(f"Could not create the virtual environment at {venv}")
    return python


def install_dependencies(root: Path, python: Path, skip_playwright: bool) -> None:
    requirements = root / "requirements.txt"
    run("Upgrading pip…", [str(python), "-m", "pip", "install", "--upgrade", "pip"])
    run("Installing MARK dependencies…", [str(python), "-m", "pip", "install", "-r", str(requirements)])

    if not skip_playwright:
        try:
            run("Installing the Chromium browser for browser controls…", [
                str(python), "-m", "playwright", "install", "chromium",
            ])
        except subprocess.CalledProcessError:
            say("WARNING: Chromium installation failed; browser controls can be installed later with:")
            say(f"  {python} -m playwright install chromium")


def write_launchers(root: Path) -> tuple[Path, Path]:
    """Return (Windows batch launcher, POSIX launcher)."""
    installer_dir = root / "installer"
    installer_dir.mkdir(parents=True, exist_ok=True)

    bat = installer_dir / "mark.bat"
    bat.write_text(
        "@echo off\n"
        "set \"ROOT=%~dp0..\"\n"
        "set \"PY=%ROOT%\\.venv\\Scripts\\python.exe\"\n"
        "if not exist \"%PY%\" (\n"
        "  echo MARK is not installed yet. Run installer\\install.ps1 first.\n"
        "  pause\n"
        "  exit /b 1\n"
        ")\n"
        "\"%PY%\" \"%ROOT%\\main.py\" %*\n",
        encoding="utf-8",
    )

    sh = installer_dir / "mark.sh"
    sh.write_text(
        "#!/usr/bin/env bash\n"
        "set -e\n"
        "ROOT=\"$(CDPATH= cd -- \"$(dirname -- \"${BASH_SOURCE[0]}\")/..\" && pwd)\"\n"
        "PY=\"$ROOT/.venv/bin/python\"\n"
        "if [ ! -x \"$PY\" ]; then\n"
        "  echo 'MARK is not installed yet. Run: python3 installer/install.py' >&2\n"
        "  exit 1\n"
        "fi\n"
        "exec \"$PY\" \"$ROOT/main.py\" \"$@\"\n",
        encoding="utf-8",
    )
    sh.chmod(sh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bat, sh


def _windows_desktop_dir() -> Path:
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    candidates = [home / "Desktop", home / "OneDrive" / "Desktop"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _make_windows_shortcut(shortcut: Path, launcher: Path, icon: Path, root: Path) -> bool:
    """Create a real .lnk without adding a Python shortcut dependency."""
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return False
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "MARK_SHORTCUT": str(shortcut),
        "MARK_ROOT": str(root),
        "MARK_LAUNCHER": str(launcher),
        "MARK_ICON": str(icon),
        "MARK_CMD": os.environ.get("ComSpec", "cmd.exe"),
    })
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$s = $ws.CreateShortcut($env:MARK_SHORTCUT); "
        "$s.TargetPath = $env:MARK_CMD; "
        "$s.Arguments = '/c ""' + $env:MARK_LAUNCHER + '""'; "
        "$s.WorkingDirectory = $env:MARK_ROOT; "
        "$s.IconLocation = $env:MARK_ICON + ',0'; "
        "$s.Description = 'Local Ollama AI assistant'; "
        "$s.Save()"
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        say(f"WARNING: could not create {shortcut}: {result.stderr.strip()[:180]}")
    return result.returncode == 0


def install_windows_shortcuts(root: Path, launcher: Path) -> None:
    icon = root / "config" / "jarvis.ico"
    desktop = _windows_desktop_dir()
    start_menu = Path(os.environ.get("APPDATA", str(Path.home()))) / \
        "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
    created = []
    for destination in (desktop / "MARK.lnk", start_menu / "MARK.lnk"):
        if _make_windows_shortcut(destination, launcher, icon, root):
            created.append(destination)
    if created:
        say("Desktop and Start Menu shortcuts created.")
    else:
        say(f"Shortcut creation was unavailable; launch manually with {launcher}")


def install_linux_shortcuts(root: Path, launcher: Path) -> None:
    icon = root / "config" / "mark.png"
    desktop_entry = "\n".join([
        "[Desktop Entry]",
        "Version=1.0",
        "Type=Application",
        "Name=MARK",
        "Comment=Local Ollama AI assistant",
        f"Exec={launcher}",
        f"Path={root}",
        f"Icon={icon}",
        "Terminal=false",
        "Categories=Utility;",
        "StartupNotify=true",
        "",
    ])
    applications = Path.home() / ".local" / "share" / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    entry = applications / "mark.desktop"
    entry.write_text(desktop_entry, encoding="utf-8")
    entry.chmod(entry.stat().st_mode | stat.S_IXUSR)

    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    desktop_file = desktop / "MARK.desktop"
    desktop_file.write_text(desktop_entry, encoding="utf-8")
    desktop_file.chmod(desktop_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    gio = shutil.which("gio")
    if gio:
        subprocess.run([gio, "set", str(desktop_file), "metadata::trusted", "true"], check=False)
    say(f"Linux application entry and desktop icon created: {desktop_file}")


def install_macos_shortcut(root: Path, launcher: Path) -> None:
    app = Path.home() / "Applications" / "MARK.app"
    contents = app / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    (resources / "MARK.png").write_bytes((root / "config" / "mark.png").read_bytes())
    (contents / "Info.plist").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleDisplayName</key><string>MARK</string>
<key>CFBundleName</key><string>MARK</string>
<key>CFBundleIdentifier</key><string>ai.arena.mark</string>
<key>CFBundleVersion</key><string>1.0.0</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleExecutable</key><string>MARK</string>
<key>CFBundleIconFile</key><string>MARK.png</string>
</dict></plist>
""",
        encoding="utf-8",
    )
    app_launcher = macos / "MARK"
    app_launcher.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(str(launcher))} \"$@\"\n",
        encoding="utf-8",
    )
    app_launcher.chmod(app_launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    desktop_link = Path.home() / "Desktop" / "MARK.app"
    desktop_link.parent.mkdir(parents=True, exist_ok=True)
    if desktop_link.exists() or desktop_link.is_symlink():
        if desktop_link.is_dir() and not desktop_link.is_symlink():
            shutil.rmtree(desktop_link)
        else:
            desktop_link.unlink()
    desktop_link.symlink_to(app, target_is_directory=True)
    say(f"macOS application and desktop icon created: {desktop_link}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install MARK and create a desktop icon")
    parser.add_argument("--root", type=Path, default=SOURCE_ROOT,
                        help="Installation root (default: this repository)")
    parser.add_argument("--skip-dependencies", action="store_true")
    parser.add_argument("--skip-playwright", action="store_true")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    if root != SOURCE_ROOT and not (root / "main.py").exists():
        if root.is_relative_to(SOURCE_ROOT):
            parser.error("--root cannot be a directory inside the source checkout")
        say(f"Copying MARK to {root} …")
        root.parent.mkdir(parents=True, exist_ok=True)

        def _ignore(_directory: str, names: list[str]) -> set[str]:
            ignored = {".git", ".venv", "__pycache__", "build", "dist"}
            return {name for name in names if name in ignored or name.endswith(".pyc")}

        shutil.copytree(SOURCE_ROOT, root, dirs_exist_ok=True, ignore=_ignore)
    if not (root / "main.py").exists() or not (root / "requirements.txt").exists():
        parser.error(f"{root} does not look like a MARK source directory")
    root.joinpath("config").mkdir(exist_ok=True)
    root.joinpath("memory").mkdir(exist_ok=True)

    python = make_venv(root)
    if not args.skip_dependencies:
        install_dependencies(root, python, args.skip_playwright)
    bat, sh = write_launchers(root)

    system = platform.system()
    if system == "Windows":
        install_windows_shortcuts(root, bat)
    elif system == "Darwin":
        install_macos_shortcut(root, sh)
    else:
        install_linux_shortcuts(root, sh)

    say("Installation complete.")
    say("Next: install/start Ollama, then pull qwen2.5:14b and qwen2.5vl:7b.")
    say(f"Launch manually with: {bat if system == 'Windows' else sh}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
