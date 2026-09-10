"""Convenience entry point for installing MARK.

Use ``python setup.py`` when you want the same cross-platform installation as
``python installer/install.py``: a private virtual environment, dependencies,
and a desktop launcher/icon.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


if __name__ == "__main__":
    raise SystemExit(subprocess.call([
        sys.executable,
        str(ROOT / "installer" / "install.py"),
        *sys.argv[1:],
    ]))
