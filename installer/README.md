# MARK installer

## Windows

Install [Python 3](https://www.python.org/downloads/) and [Ollama](https://ollama.com), then either:

- build `MARK.iss` with Inno Setup 6 to produce `output/MARK-Installer.exe`, or
- run `install.ps1` from PowerShell.

The installer creates a user-writable install under `%LOCALAPPDATA%\Programs\MARK`, installs the Python dependencies into `.venv`, and creates a desktop and Start Menu shortcut with `config/jarvis.ico`.

## Linux and macOS

From the repository root:

```bash
python3 installer/install.py
```

This creates `.venv`, installs `requirements.txt`, and creates a desktop launcher. Linux uses `~/.local/share/applications/mark.desktop` plus `~/Desktop/MARK.desktop`; macOS uses `~/Applications/MARK.app` plus a Desktop alias.

Use `--skip-dependencies` when dependencies are already installed, and `--skip-playwright` to omit the optional Chromium download.

After installation, pull the local models:

```bash
ollama pull qwen2.5:14b
ollama pull qwen2.5vl:7b
```
