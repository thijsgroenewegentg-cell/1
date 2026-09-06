# /interfaces/web_ui.py
"""The phone/LAN web interface — FastAPI, WebSocket chat and hold-to-talk.

The implementation lives in :mod:`interfaces.web`; this is the name the
project layout uses, and it is the import everything outside the package
should prefer::

    from interfaces.web_ui import WebInterface

Serve it with ``python main.py --web`` (add ``--port``), or type ``web`` in
the terminal interface. It binds ``web_ui.host`` (default ``0.0.0.0``) on
``web_ui.port`` so a phone on the same network can reach it, and prints the
LAN address to use.
"""

from __future__ import annotations

from interfaces.web import WebInterface, local_addresses, render_icon

__all__ = ["WebInterface", "local_addresses", "render_icon"]
