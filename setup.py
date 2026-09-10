"""One-time setup for MARK's local Ollama build."""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run(label: str, args: list[str]) -> None:
    print(f"\n▶ {label}")
    subprocess.run(args, check=True)


def main() -> None:
    os_name = platform.system()
    print(f"◈ MARK local setup — detected OS: {os_name}")
    print("   The language model is local: install Ollama separately from https://ollama.com")

    run("Installing Python dependencies", [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])

    # Browser control is optional. Do not make a first run fail because a user
    # only wants chat, files and desktop tools.
    try:
        run("Installing Playwright Chromium", [sys.executable, "-m", "playwright", "install", "chromium"])
    except subprocess.CalledProcessError:
        print("⚠ Playwright browser install failed; browser_control will be unavailable until installed manually.")

    if shutil.which("ollama"):
        print("\n✅ Ollama command found.")
    else:
        print("\n⚠ Ollama was not found on PATH.")
        print("  Install it from https://ollama.com, then run:")
        print("    ollama pull qwen2.5:14b")
        print("    ollama pull qwen2.5vl:7b")

    print("\n✅ Python setup complete.")
    print("   Launch with: python main.py")
    print("   On first launch, enter your Ollama URL and model in the local setup panel.")


if __name__ == "__main__":
    main()
