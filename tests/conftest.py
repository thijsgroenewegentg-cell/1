# /tests/conftest.py
"""Shared pytest configuration.

``tests/test_smoke.py`` is an end-to-end script, not a pytest module: it
boots a mock Ollama, builds the whole assistant and prints its own report.
``modules/self_improve.py`` runs it with ``python tests/test_smoke.py``, so
it must keep working as a standalone program — pytest simply ignores it and
runs the fast unit tests in ``test_units.py`` instead.

Run everything with::

    pytest                      # fast unit tests
    python tests/test_smoke.py  # full integration sweep
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

collect_ignore = ["test_smoke.py", "mock_ollama.py"]
