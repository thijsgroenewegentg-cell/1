# /interfaces/web.py
"""Phone- and LAN-friendly web interface for JARVIS.

A single self-contained FastAPI app: a dark, mobile-first chat page served from
memory, a WebSocket that streams tokens as the model produces them, a plain
JSON endpoint for scripts, and optional audio replies rendered with the same
edge-tts voice the desktop uses.

It binds to the LAN (``0.0.0.0`` by default) so you can talk to the assistant
running on your desktop from your phone — nothing is proxied through a cloud
service. Set ``web_ui.token`` to require ``?token=…`` before anyone on your
network can chat with it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from utils.helpers import human_bytes, truncate
from utils.logger import get_logger

logger = get_logger("interfaces.web")

# FastAPI is imported at module level (not inside the factory) so that the
# annotations below resolve — ``from __future__ import annotations`` turns them
# into strings that FastAPI looks up in this module's globals.
try:
    from fastapi import (
        FastAPI,
        HTTPException,
        Query,
        Request,
        WebSocket,
        WebSocketDisconnect,
    )
    from fastapi.responses import (
        FileResponse,
        HTMLResponse,
        JSONResponse,
        Response,
    )

    HAS_FASTAPI = True
except Exception:  # pragma: no cover - optional dependency
    HAS_FASTAPI = False
    FastAPI = None  # type: ignore[misc, assignment]

def render_icon(size: int) -> bytes:
    """Draw the app icon as a PNG, with no image library involved.

    A black rounded square with a red reactor ring — enough for a home-screen
    icon, and it costs nothing but ``zlib``.

    Args:
        size: Width and height in pixels.

    Returns:
        The encoded PNG bytes.
    """
    import struct
    import zlib

    centre = (size - 1) / 2.0
    outer = size * 0.40
    inner = size * 0.27
    core = size * 0.12
    corner = size * 0.22
    background = (0, 0, 0)
    ring = (239, 68, 68)

    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG filter type: none
        for x in range(size):
            # Rounded-square mask, so the icon looks right when not masked.
            dx = max(abs(x - centre) - (size / 2 - corner), 0.0)
            dy = max(abs(y - centre) - (size / 2 - corner), 0.0)
            if (dx * dx + dy * dy) ** 0.5 > corner:
                rows.extend((0, 0, 0, 0))
                continue
            distance = ((x - centre) ** 2 + (y - centre) ** 2) ** 0.5
            if distance <= core or inner <= distance <= outer:
                red, green, blue = ring
            else:
                red, green, blue = background
            rows.extend((red, green, blue, 255))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        """Assemble one PNG chunk with its CRC."""
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
            + chunk(b"IEND", b""))


SERVICE_WORKER = """// JARVIS offline shell
const CACHE = "jarvis-shell-v1";
const SHELL = ["/icon-192.png", "/icon-512.png", "/manifest.webmanifest"];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.pathname.startsWith("/api/") || url.pathname === "/ws") return;
  event.respondWith(
    fetch(request)
      .then(response => {
        if (response.ok && (url.pathname === "/" || SHELL.includes(url.pathname))) {
          const copy = response.clone();
          caches.open(CACHE).then(cache => cache.put(request, copy)).catch(() => {});
        }
        return response;
      })
      .catch(() =>
        caches.match(request).then(hit =>
          hit || new Response(
            "<!doctype html><meta charset=utf-8><style>body{background:#000;color:#a1a1aa;"
            + "font:16px system-ui;display:grid;place-items:center;height:100vh;margin:0}</style>"
            + "<p>JARVIS is not reachable. Is the machine awake, sir?</p>",
            { headers: { "Content-Type": "text/html" }, status: 503 }
          )
        )
      )
  );
});
"""

#: The interface itself lives next door as a real HTML file, so it can be
#: edited and read like a document instead of a Python string.
APP_FILE = Path(__file__).with_name("app.html")

#: The dramatic boot-up sequence shown full-screen while the console loads.
BOOT_FILE = Path(__file__).with_name("boot_sequence.html")

#: Shown only if that file is missing from an installation.
FALLBACK_PAGE = """<!doctype html><meta charset="utf-8">
<title>__TITLE__</title>
<body style="background:#000;color:#f4f4f5;font:16px system-ui;padding:40px">
<h1>__TITLE__</h1>
<p>interfaces/app.html is missing, so this is the plain fallback.</p>
<form onsubmit="event.preventDefault();ask()">
  <input id="q" style="width:70%;padding:8px" placeholder="Ask something">
  <button>Send</button></form>
<pre id="out" style="white-space:pre-wrap"></pre>
<script>
const token = new URLSearchParams(location.search).get("token") || "";
async function ask() {
  const text = document.getElementById("q").value;
  const reply = await fetch("/api/ask" + (token ? "?token=" + token : ""),
    { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }) }).then(r => r.json());
  document.getElementById("out").textContent += "\n> " + text + "\n" + (reply.reply || reply.detail);
}
</script></body>"""


def load_page() -> str:
    """Read the interface from disk, falling back to a minimal page.

    Returns:
        The HTML, with ``__TITLE__`` and ``__TOKEN_QUERY__`` still in place.
    """
    try:
        return APP_FILE.read_text(encoding="utf-8")
    except Exception as error:  # pragma: no cover - only when a file is lost
        logger.warning("interfaces/app.html is unreadable (%s); using the fallback.", error)
        return FALLBACK_PAGE


#: Longest message accepted from a browser. Generous for dictation, small
#: enough that nobody can push a megabyte into the model and the database.
MAX_MESSAGE_CHARS = 8000


def _format_uptime(seconds: Any) -> str:
    """Render an uptime in seconds as a short human string.

    Args:
        seconds: Elapsed seconds, as reported by the brain.

    Returns:
        Something like ``"3m"``, ``"2h 14m"`` or ``"1d 3h"``; ``"just started"``
        below a minute.
    """
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return ""
    if total < 60:
        return "just started"
    minutes, hours = (total // 60) % 60, total // 3600
    if hours >= 24:
        return f"{hours // 24}d {hours % 24}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class WebInterface:
    """FastAPI + WebSocket front-end that runs alongside the CLI."""

    def __init__(
        self,
        brain: Any,
        config: Any,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        """Configure the web server without starting it.

        Args:
            brain: The :class:`core.brain.Brain` handling requests.
            config: Global configuration object.
            host: Bind address override (default ``web_ui.host``).
            port: Port override (default ``web_ui.port``).
        """
        self.brain = brain
        self.config = config
        section = config.section("web_ui")
        self.host = host or str(section.get("host", "0.0.0.0"))
        self.port = int(port or section.get("port", 8765))
        self.token = self._resolve_token(str(section.get("token", "") or ""),
                                         bool(section.get("require_token", True)))
        self.allow_tts = bool(section.get("allow_tts", True))
        self.title = str(section.get("title", config.get("assistant.name", "JARVIS")))
        self.clients: int = 0
        self._sockets: Set[Any] = set()
        self._watching = False
        self._page_cache: Optional[str] = None
        self._page_stamp: float = 0.0
        #: Strong references to in-flight relay tasks, so they are not
        #: collected mid-send.
        self._relays: Set["asyncio.Task[None]"] = set()
        self._icons: Dict[int, bytes] = {}
        self._stt: Optional[Any] = None
        self._stt_tried = False
        self.max_audio_bytes = int(section.get("max_audio_mb", 25) or 25) * 1024 * 1024
        self.rate_limit = int(section.get("rate_limit_per_minute", 40) or 40)
        self._hits: Dict[str, List[float]] = {}
        self._server: Optional[Any] = None
        self._tts: Optional[Any] = None
        self._paused: bool = False
        #: Serialises who may swap the security confirmation hook. The brain
        #: runs one turn at a time, but two browsers could otherwise race to
        #: install their own hook and one would answer the other's prompt.
        self._confirm_lock = asyncio.Lock()
        self._confirm_seq: int = 0
        self.app = self._build_app()

    # ------------------------------------------------------------------ utils
    def _resolve_token(self, configured: str, require: bool) -> str:
        """Return the shared secret, generating a stable one when needed.

        An unauthenticated chat window bound to ``0.0.0.0`` is an open door on
        any shared network, so when no token is configured JARVIS mints one,
        stores it in ``data/web_token.txt`` (owner-readable) and prints it in
        the URL. Set ``web_ui.require_token: false`` for a deliberately open
        instance.

        Args:
            configured: The token from ``config.yaml``.
            require: Whether a token is mandatory.

        Returns:
            The token to enforce, or ``""`` when explicitly disabled.
        """
        if configured:
            return configured
        if not require:
            logger.warning("Web interface running without a token — anyone on your "
                           "network can talk to JARVIS.")
            return ""
        path = self.config.resolve("data/web_token.txt")
        try:
            if path.exists():
                existing = path.read_text(encoding="utf-8").strip()
                if existing:
                    return existing
            token = secrets.token_urlsafe(12)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(token + "\n", encoding="utf-8")
            with contextlib.suppress(Exception):
                path.chmod(0o600)
            logger.info("Generated a web access token (stored in %s).", path)
            return token
        except Exception as exc:  # pragma: no cover - read-only filesystem
            logger.warning("Could not persist a web token (%s); using a session-only one.", exc)
            return secrets.token_urlsafe(12)

    def _rate_limited(self, client: str, cost: int = 1) -> bool:
        """Simple per-IP token bucket protecting the LLM from abuse.

        Args:
            client: The caller's address.
            cost: How much of the budget this request consumes.

        Returns:
            True when the caller has exceeded the allowance.
        """
        now = time.monotonic()
        window, allowance = 60.0, self.rate_limit
        used = [stamp for stamp in self._hits.get(client, []) if now - stamp < window]
        if len(used) + cost > allowance:
            self._hits[client] = used
            logger.warning("Rate-limited %s (%d requests in the last minute).",
                           client, len(used))
            return True
        used.extend([now] * cost)
        self._hits[client] = used
        if len(self._hits) > 256:  # keep the table from growing forever
            for key in [k for k, v in self._hits.items() if not v or now - v[-1] > window]:
                self._hits.pop(key, None)
        return False

    @property
    def url(self) -> str:
        """The address to open in a browser."""
        host = "localhost" if self.host in {"0.0.0.0", "::"} else self.host
        suffix = f"?token={self.token}" if self.token else ""
        return f"http://{host}:{self.port}/{suffix}"

    def _authorised(self, supplied: Optional[str]) -> bool:
        """Constant-time check of the shared secret."""
        if not self.token:
            return True
        return bool(supplied) and secrets.compare_digest(str(supplied), self.token)

    async def _tts_engine(self) -> Optional[Any]:
        """Lazily build a TTS engine for the ``/api/tts`` endpoint."""
        if not self.allow_tts:
            return None
        if self._tts is None:
            try:
                from interfaces.voice import TextToSpeech

                engine = TextToSpeech(self.config)
                # The browser plays the audio, so a server-side command-line
                # player is irrelevant here. Requiring one meant a machine with
                # edge-tts installed but no ffmpeg reported "tts unavailable".
                if await engine.initialize(require_player=False):
                    self._tts = engine
            except Exception as exc:
                logger.debug("Web TTS unavailable: %s", exc)
                self._tts = None
        return self._tts

    async def _dashboard_payload(self) -> Dict[str, Any]:
        """Assemble the idle home dashboard: five glanceable, read-only cards.

        Each capability degrades to an empty card when its module is disabled,
        its data is empty or it errors — the home page must never depend on
        any one of them. Everything is read from local modules, so the cards
        work with the model offline.

        Returns:
            ``{"cards": [{"key", "title", "lines": [{"text", "meta"}]}]}``.
        """
        cards: List[Dict[str, Any]] = []

        async def _call(module: str, tool_name: str,
                        params: Optional[Dict[str, Any]] = None) -> Any:
            """Run one module tool with a short timeout; never raise."""
            module_obj = self.brain.modules.get(module) if self.brain else None
            if module_obj is None:
                return None
            try:
                return await asyncio.wait_for(
                    module_obj.call_tool(tool_name, params or {}), timeout=6
                )
            except Exception as exc:
                logger.debug("Dashboard %s.%s failed: %s", module, tool_name, exc)
                return None

        # -- open tasks ------------------------------------------------------
        result = await _call("productivity", "list_todos", {"limit": 8})
        rows = (result.data or {}).get("todos", []) if result and result.success else []
        open_rows = [row for row in rows if not row.get("done")]
        if result is not None:
            lines = []
            if open_rows:
                for row in open_rows[:5]:
                    meta = []
                    if row.get("priority") == "high":
                        meta.append("high")
                    due = str(row.get("due") or "")
                    if due and "T" in due:
                        meta.append(f"due {due[11:16]}")
                    lines.append({"text": str(row.get("task", "")),
                                  "meta": " · ".join(meta) or ""})
            else:
                lines.append({"text": "Nothing open — suspiciously quiet.",
                              "meta": ""})
            cards.append({
                "key": "tasks", "title": "Open tasks",
                "lines": lines,
                "empty": not open_rows,
            })

        # -- next reminders --------------------------------------------------
        result = await _call("productivity", "list_reminders", {"limit": 4})
        rows = (result.data or {}).get("reminders", []) if result and result.success else []
        if result is not None:
            lines = []
            if rows:
                for row in rows[:4]:
                    due = str(row.get("due") or "")
                    meta = f"at {due[11:16]}" if "T" in due else ""
                    lines.append({"text": str(row.get("text", "")), "meta": meta})
            else:
                lines.append({"text": "No reminders coming up.", "meta": ""})
            cards.append({
                "key": "reminders", "title": "Next reminders",
                "lines": lines, "empty": not rows,
            })

        # -- weather (only when web_search is enabled) -----------------------
        if self.config.get("modules.web_search", True):
            result = await _call("web_search", "weather", {})
            if result is not None and result.success:
                text = (result.speak or result.output or "").strip()
                if text:
                    first = text.split("\n")[0]
                    cards.append({
                        "key": "weather", "title": "Weather",
                        "lines": [{"text": first[:200], "meta": ""}],
                        "empty": False,
                    })

        # -- system -----------------------------------------------------------
        result = await _call("system_control", "system_stats")
        if result is not None and result.success:
            data = result.data or {}
            if data.get("cpu_percent") is not None:
                lines = [
                    {"text": f"CPU {float(data['cpu_percent']):.0f}%",
                     "meta": f"{data.get('cpu_cores', '?')} cores"},
                    {"text": f"RAM {float(data['ram_percent']):.0f}%",
                     "meta": f"{data.get('ram_used', '?')} of {data.get('ram_total', '?')}"},
                    {"text": f"Disk {float(data['disk_percent']):.0f}%",
                     "meta": f"{data.get('disk_used', '?')} used"},
                ]
                cards.append({"key": "system", "title": "System",
                              "lines": lines, "empty": False})

        # -- last self-check --------------------------------------------------
        try:
            from core.health import read_report, summarize

            report = read_report(self.config)
        except Exception:
            report = None
        if report and (report.get("date") or report.get("ok") is not None):
            day = str(report.get("date", "") or "")
            when = f"{day[8:10]}/{day[5:7]}/{day[0:4]}" if "T" not in day and len(day) == 10 else day
            cards.append({
                "key": "health", "title": "Last self-check",
                "lines": [{"text": (summarize(report) or "All quiet.")[:200],
                           "meta": when or ""}],
                "empty": False,
            })
        elif str(self.config.get("assistant.nightly_check_time", "") or "").strip():
            cards.append({
                "key": "health", "title": "Last self-check",
                "lines": [{"text": "No check recorded yet — the first runs "
                                   "overnight.", "meta": ""}],
                "empty": True,
            })
        return {"cards": cards}

    async def speech_available(self) -> bool:
        """Whether ``/api/tts`` can actually return audio.

        The page uses this to decide if the "read replies aloud" control is
        meaningful. Without it the toggle happily showed "on" while every
        request to ``/api/tts`` failed with a 503.
        """
        if not self.allow_tts:
            return False
        return await self._tts_engine() is not None

    # -------------------------------------------------------------------- app
    def _build_app(self) -> Any:
        """Construct the FastAPI application.

        Raises:
            RuntimeError: If FastAPI is not installed.
        """
        if not HAS_FASTAPI:
            raise RuntimeError(
                "The web interface needs FastAPI and uvicorn: "
                "pip install 'fastapi>=0.110' 'uvicorn>=0.29'"
            )

        app = FastAPI(title=f"{self.title} web interface", docs_url=None, redoc_url=None)
        # The interface is one 61 KB document of markup, style and script.
        # Compressed it is a fifth of that, which is the difference between a
        # snappy load and a visible one over Wi-Fi.
        try:
            from fastapi.middleware.gzip import GZipMiddleware

            app.add_middleware(GZipMiddleware, minimum_size=1024)
        except Exception as error:  # pragma: no cover - middleware is optional
            logger.debug("Compression unavailable: %s", error)
        def rendered_page() -> str:
            """Return the interface with its placeholders filled in.

            Read per request and cached against the file's modification time,
            so editing interfaces/app.html shows up on the next refresh
            instead of needing a restart. A page load costs one stat().
            """
            try:
                stamp = APP_FILE.stat().st_mtime
            except OSError:
                stamp = 0.0
            if self._page_cache is None or self._page_stamp != stamp:
                self._page_cache = load_page().replace("__TITLE__", self.title).replace(
                    "__TOKEN_QUERY__", f"?token={self.token}" if self.token else ""
                )
                self._page_stamp = stamp
            return self._page_cache

        @app.get("/", response_class=HTMLResponse)
        async def index(token: str = Query(default="")) -> Any:
            """Serve the chat page.

            ``no-store`` matters: the page is re-read from disk per request so
            that edits show up on refresh, but a browser (or a proxy in front of
            one) is free to heuristic-cache a response that carries no caching
            header at all. That silently served a stale interface after an
            update, which reads as "the change did nothing".
            """
            if not self._authorised(token):
                return HTMLResponse(
                    "<h1>401</h1><p>Append ?token=… to the URL.</p>", status_code=401
                )
            return HTMLResponse(rendered_page(),
                                headers={"Cache-Control": "no-store, must-revalidate"})

        @app.get("/boot", response_class=HTMLResponse)
        async def boot_page(token: str = Query(default="")) -> Any:
            """Serve the boot-up sequence page (shown inside the console)."""
            if not self._authorised(token):
                return HTMLResponse("<h1>401</h1><p>Append ?token=…</p>",
                                    status_code=401)
            try:
                content = BOOT_FILE.read_text(encoding="utf-8")
            except Exception:  # pragma: no cover - only when the file is lost
                content = ("<!doctype html><body style=\"background:#000;"
                           "color:#fff\">boot unavailable</body>")
            return HTMLResponse(content,
                                headers={"Cache-Control": "no-store"})

        @app.get("/api/status")
        async def status(token: str = Query(default="")) -> Any:
            """Report assistant status and a greeting."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            report = await self.brain.status_report()
            # Hot-reload language -> voice: if the user changed assistant.language
            # in config.yaml, pick the right edge voice on the next status poll
            # without requiring a restart.
            try:
                tts = await self._tts_engine()
                if tts is not None:
                    cur_lang = str(self.config.get("assistant.language", "en"))
                    if getattr(tts, "language", "") != __import__("utils.language").language.normalise(cur_lang):
                        # Re-derive voice_for so a language switch is audible immediately.
                        from utils.language import voice_for
                        tts.language = __import__("utils.language").language.normalise(cur_lang)
                        cfg_voice = str(self.config.get("voice.tts.voice", "") or "")
                        tts.voice = voice_for(cur_lang, cfg_voice)
            except Exception:
                pass
            # Redacted presence of an ElevenLabs key for the HUD — never the raw value.
            has_eleven = False
            try:
                eng = await self._tts_engine()
                has_eleven = bool(getattr(eng, "elevenlabs_api_key", "") if eng else self.config.get("voice.tts.elevenlabs_api_key", "")) or bool(__import__("os").getenv("ELEVENLABS_API_KEY"))
            except Exception:
                has_eleven = False
            tts_cache_info = {}
            try:
                eng = await self._tts_engine()
                if eng is not None and hasattr(eng, "cache_dir"):
                    cdir = eng.cache_dir
                    files = list(cdir.glob("*.mp3")) + list(cdir.glob("*.wav")) if cdir.exists() else []
                    # Auto-prune if >200 files so the browser cache button is not the only relief
                    if len(files) > 200:
                        try:
                            # Keep newest 180
                            files_sorted = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
                            for old in files_sorted[180:]:
                                try: old.unlink()
                                except Exception: pass
                            files = files_sorted[:180]
                        except Exception:
                            pass
                    # Per-engine breakdown via suffix + mtime buckets (engine is in hash, not filename)
                    # We approximate by counting mp3 (elevenlabs/edge) vs wav (piper)
                    mp3 = [f for f in files if f.suffix == ".mp3"]
                    wav = [f for f in files if f.suffix == ".wav"]
                    tts_cache_info = {"files": len(files), "bytes": sum(f.stat().st_size for f in files if f.exists()), "mp3": len(mp3), "wav": len(wav)}
            except Exception:
                tts_cache_info = {}
            return JSONResponse(
                {
                    "greeting": await self.brain.greeting(),
                    "llm": report.get("llm", {}),
                    "modules": report.get("modules", []),
                    "memory": report.get("memory", {}),
                    # The panel has always had an "Uptime" row with nothing to
                    # put in it, so it read "—" forever: the brain reports
                    # uptime_seconds, which was never passed through.
                    "uptime": _format_uptime(report.get("uptime_seconds", 0)),
                    "turns": report.get("turns", 0),
                    "clients": self.clients,
                    # So the page can disable the "read replies aloud" control
                    # instead of offering speech that cannot be delivered.
                    "speech": await self.speech_available(),
                    "has_elevenlabs_key": has_eleven,
                    "tts_cache": tts_cache_info,
                }
            )

        @app.get("/api/dashboard")
        async def dashboard(token: str = Query(default="")) -> Any:
            """Idle-home cards: tasks, reminders, weather, system, self-check.

            Read-only and cheap: local SQLite plus one optional weather
            request, every call wrapped so a failing module never fails the
            page. The browser refreshes it while the home screen is idle.
            """
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            try:
                payload = await self._dashboard_payload()
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Dashboard assembly failed: %s", exc)
                payload = {"cards": []}
            return JSONResponse(payload)

        @app.post("/api/ask")
        async def ask(request: Request, token: str = Query(default="")) -> Any:
            """Answer a single question over plain JSON (no streaming)."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            try:
                payload: Dict[str, Any] = await request.json()
            except Exception:
                payload = {}
            text = str(payload.get("text", "")).strip()
            if not text:
                raise HTTPException(status_code=400, detail="missing 'text'")
            if len(text) > MAX_MESSAGE_CHARS:
                # Otherwise a phone can push a megabyte through the model and
                # into the conversation database in one request.
                raise HTTPException(
                    status_code=413,
                    detail=f"that message is too long (limit {MAX_MESSAGE_CHARS} characters)",
                )
            client = request.client.host if request.client else "unknown"
            if self._rate_limited(client):
                raise HTTPException(status_code=429, detail="slow down a moment, sir")
            reply = await self.brain.process(text)
            intent = getattr(self.brain, "last_intent", None)
            return JSONResponse(
                {
                    "reply": reply,
                    "intent": getattr(intent, "module", "") if intent else "",
                }
            )

        @app.get("/api/tools")
        async def tools(token: str = Query(default="")) -> Any:
            """List every tool, so the interface can offer them for browsing."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            listing = []
            for module_name, module in getattr(self.brain, "modules", {}).items():
                for name, spec in getattr(module, "tools", {}).items():
                    examples = list(getattr(spec, "examples", []) or [])
                    listing.append({
                        "module": module_name,
                        "name": name,
                        "description": getattr(spec, "description", ""),
                        "example": examples[0] if examples else "",
                        "dangerous": bool(getattr(spec, "dangerous", False)),
                    })
            listing.sort(key=lambda item: (item["module"], item["name"]))
            return JSONResponse({"tools": listing})

        @app.get("/api/audit")
        async def audit(token: str = Query(default=""), limit: int = Query(default=25)) -> Any:
            """Report what needed permission, for the audit tab."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            guard = getattr(self.brain, "security", None)
            if guard is None:
                return JSONResponse({"entries": []})
            try:
                entries = guard.recent_audit(max(1, min(200, int(limit))))
            except Exception as error:
                logger.debug("Could not read the audit trail: %s", error)
                entries = []
            return JSONResponse({"entries": entries})

        @app.get("/api/voices")
        async def voices(token: str = Query(default=""), refresh: str = Query(default="")) -> Any:
            """List available TTS voices for the picker."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            engine = await self._tts_engine()
            # ?refresh=1 busts the 1h ElevenLabs cache
            if refresh and refresh.strip().lower() in {"1", "true", "yes"} and engine is not None:
                try:
                    # Clear the class cache so the next call fetches fresh
                    if hasattr(engine, "_ELEVEN_VOICES_CACHE"):
                        engine._ELEVEN_VOICES_CACHE = None
                        engine._ELEVEN_VOICES_AT = 0.0
                except Exception:
                    pass
            configured_engine = str(self.config.get("voice.tts.engine", "auto"))
            language = str(self.config.get("assistant.language", "en"))
            # Redacted source of the key for the HUD
            source = ""
            try:
                if getattr(engine, "elevenlabs_api_key", ""):
                    # Could be from config or env — check which
                    cfg_has = bool(str(self.config.get("voice.tts.elevenlabs_api_key", "") or "").strip())
                    env_has = bool(__import__("os").getenv("ELEVENLABS_API_KEY", "").strip())
                    if cfg_has and env_has:
                        source = "config.yaml + env"
                    elif cfg_has:
                        source = "config.yaml"
                    elif env_has:
                        source = "env/secrets.env"
                    else:
                        source = "config"
                elif self.config.get("voice.tts.elevenlabs_api_key", ""):
                    source = "config.yaml"
                elif __import__("os").getenv("ELEVENLABS_API_KEY"):
                    # Distinguish data/secrets.env vs env
                    import pathlib as _pl
                    sec = None
                    try:
                        sec = self.config.resolve("data/secrets.env")
                    except Exception:
                        sec = _pl.Path("data/secrets.env")
                    source = "data/secrets.env" if sec and sec.exists() else "env"
            except Exception:
                source = "env" if __import__("os").getenv("ELEVENLABS_API_KEY") else ""
            current = {
                "engine": configured_engine,
                "active_engine": getattr(engine, "active_engine", "") if engine else "",
                "language": language,
                "edge_voice": getattr(engine, "voice", "") if engine else "",
                "elevenlabs_voice_id": getattr(engine, "elevenlabs_voice_id", "") if engine else "",
                "elevenlabs_model": getattr(engine, "elevenlabs_model", "") if engine else "",
                "has_elevenlabs_key": bool(getattr(engine, "elevenlabs_api_key", "") if engine else self.config.get("voice.tts.elevenlabs_api_key", "")) or bool(__import__("os").getenv("ELEVENLABS_API_KEY")),
                "elevenlabs_source": source,
            }
            edge_voices: List[str] = []
            eleven_voices: List[Dict[str, Any]] = []
            if engine is not None:
                try:
                    edge_voices = await engine.list_voices(language=language)
                except Exception:
                    edge_voices = []
                if getattr(engine, "_has_elevenlabs", lambda: False)():
                    try:
                        if hasattr(engine, "list_elevenlabs_voices"):
                            eleven_voices = await engine.list_elevenlabs_voices()
                    except Exception as exc:
                        logger.debug("ElevenLabs voice list failed: %s", exc)
                        eleven_voices = []
            # Piper status for the panel
            piper_installed = False
            try:
                piper_dir = self.config.resolve("data/piper")
                piper_installed = any(piper_dir.glob("*.onnx")) if piper_dir.exists() else False
            except Exception:
                piper_installed = False
            current["piper_installed"] = piper_installed
            return JSONResponse({
                "current": current,
                "edge_voices": edge_voices[:40],
                "elevenlabs_voices": eleven_voices[:30],
                "speech": await self.speech_available(),
            })

        @app.post("/api/voices")
        async def save_voice(request: Request, token: str = Query(default="")) -> Any:
            """Persist the picker choice to config.yaml."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            try:
                payload: Dict[str, Any] = await request.json()
            except Exception:
                payload = {}
            engine = str(payload.get("engine", "") or "").strip().lower()
            voice = str(payload.get("voice", "") or "").strip()
            eleven_id = str(payload.get("elevenlabs_voice_id", "") or "").strip()
            eleven_model = str(payload.get("elevenlabs_model", "") or "").strip()
            # Allow the combined picker value "elevenlabs:ID" / "edge:Name"
            if not engine and voice:
                if voice.startswith("elevenlabs:"):
                    engine = "elevenlabs"
                    eleven_id = voice.split(":", 1)[1].strip()
                    voice = ""
                elif voice.startswith("edge:"):
                    engine = "edge"
                    voice = voice.split(":", 1)[1].strip()
            # Validate
            if engine and engine not in {"auto", "piper", "edge", "elevenlabs", "eleven", "eleven_labs"}:
                raise HTTPException(status_code=400, detail="unknown engine")
            # Write through the config object so aliases, env and save() all apply
            if engine:
                self.config.set("voice.tts.engine", engine)
            if voice:
                self.config.set("voice.tts.voice", voice)
            if eleven_id:
                self.config.set("voice.tts.elevenlabs_voice_id", eleven_id)
            if eleven_model:
                self.config.set("voice.tts.elevenlabs_model", eleven_model)
            # Also persist assistant.language if the picker sent a language hint
            lang = str(payload.get("language", "") or "").strip()
            if lang:
                self.config.set("assistant.language", lang)
            try:
                self.config.save()
            except Exception as exc:
                logger.warning("Could not save voice config: %s", exc)
                raise HTTPException(status_code=500, detail="could not save config")
            # Re-initialise the in-memory TTS so the next /api/tts uses it without restart
            try:
                tts = await self._tts_engine()
                if tts is not None:
                    # Force re-read from config
                    tts.engine = str(self.config.get("voice.tts.engine", "auto"))
                    tts.voice = str(self.config.get("voice.tts.voice", "") or tts.voice)
                    tts.elevenlabs_voice_id = str(self.config.get("voice.tts.elevenlabs_voice_id", "") or getattr(tts, "elevenlabs_voice_id", ""))
                    tts.elevenlabs_model = str(self.config.get("voice.tts.elevenlabs_model", "") or getattr(tts, "elevenlabs_model", ""))
                    # Language -> voice hot-reload
                    from utils.language import voice_for as _vf
                    cur_lang = str(self.config.get("assistant.language", "en"))
                    tts.language = __import__("utils.language").language.normalise(cur_lang)
                    if not voice and engine != "elevenlabs":
                        cfg_v = str(self.config.get("voice.tts.voice", "") or "")
                        tts.voice = _vf(cur_lang, cfg_v)
                    await tts.initialize(require_player=False)
            except Exception as exc:
                logger.debug("TTS re-init after save failed: %s", exc)
            return JSONResponse({"ok": True})

        @app.post("/api/tts/cache/clear")
        async def clear_tts_cache(token: str = Query(default="")) -> Any:
            """Clear the TTS cache (mp3/wav files)."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            try:
                tts = await self._tts_engine()
                if tts is not None and hasattr(tts, "cache_dir"):
                    cdir = tts.cache_dir
                    count = 0
                    if cdir.exists():
                        for f in list(cdir.glob("*.mp3")) + list(cdir.glob("*.wav")) + list(cdir.glob("*.part")):
                            try:
                                f.unlink()
                                count += 1
                            except Exception:
                                pass
                    return JSONResponse({"ok": True, "cleared": count})
            except Exception as exc:
                logger.debug("Cache clear failed: %s", exc)
            return JSONResponse({"ok": True, "cleared": 0})

        @app.post("/api/vision")
        async def vision(request: Request, token: str = Query(default="")) -> Any:
            """Describe an image dropped onto the web UI (llava etc)."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            # Separate vision bucket so a 25MB drop does not starve /api/ask
            if self._rate_limited("vision", cost=4):
                raise HTTPException(status_code=429, detail="vision busy, try again")
            ctype = (request.headers.get("content-type", "") or "").lower()
            tmp_path = None
            question = ""
            try:
                if "multipart/form-data" in ctype:
                    form = await request.form()
                    file = form.get("file") or form.get("image")
                    question = str(form.get("question", "") or form.get("text", "") or "").strip()
                    if file is not None and hasattr(file, "read"):
                        data = await file.read() if hasattr(file, "read") else file
                        if isinstance(data, (bytes, bytearray)) and len(data) > 0:
                            if len(data) > 25 * 1024 * 1024:
                                raise HTTPException(status_code=413, detail="image too large (25 MB)")
                            import secrets
                            import tempfile
                            suffix = ".png"
                            fname = getattr(file, "filename", "") or ""
                            if "." in fname:
                                suffix = "." + fname.rsplit(".", 1)[-1][:4].lower()
                                if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
                                    suffix = ".png"
                            tmp = Path(tempfile.gettempdir()) / f"jarvis-vision-{secrets.token_hex(6)}{suffix}"
                            tmp.write_bytes(bytes(data))
                            tmp_path = tmp
                    if tmp_path is None:
                        raise HTTPException(status_code=400, detail="no image file")
                else:
                    try:
                        payload = await request.json()
                    except Exception:
                        payload = {}
                    question = str(payload.get("question", "") or payload.get("text", "") or "").strip()
                    path_str = str(payload.get("path", "") or "").strip()
                    if path_str:
                        tmp_path = Path(path_str).expanduser()
                        if not tmp_path.exists():
                            raise HTTPException(status_code=404, detail="file not found")
                    else:
                        raise HTTPException(status_code=400, detail="no image")
            except HTTPException:
                raise
            except Exception as exc:
                logger.warning("Vision upload failed: %s", exc)
                raise HTTPException(status_code=500, detail="vision upload failed")
            try:
                vision_mod = None
                for mod in getattr(self.brain, "modules", {}).values():
                    if getattr(mod, "name", "") == "vision" or "vision" in str(type(mod)).lower():
                        vision_mod = mod
                        break
                    if hasattr(mod, "describe_image"):
                        vision_mod = mod
                        break
                if vision_mod is not None and hasattr(vision_mod, "call_tool"):
                    result = await vision_mod.call_tool("describe_image", {"path": str(tmp_path), "question": question or "Describe this image."})
                    text_out = getattr(result, "data", "") or getattr(result, "message", "") or str(result)
                    if hasattr(result, "success") and not result.success:
                        text_out = getattr(result, "message", "") or getattr(result, "data", "") or "Vision failed."
                    return JSONResponse({"text": str(text_out)[:4000]})
                prompt = f"Describe this image: {tmp_path}" + (f" Question: {question}" if question else "")
                reply = await self.brain.process(prompt)
                return JSONResponse({"text": reply[:4000]})
            except HTTPException:
                raise
            except Exception as exc:
                logger.warning("Vision describe failed: %s", exc)
                raise HTTPException(status_code=500, detail="vision failed")
            finally:
                try:
                    if tmp_path and tmp_path.exists() and str(tmp_path).startswith(str(Path(tempfile.gettempdir()))):
                        tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

        @app.get("/api/memory")
        async def list_memory(token: str = Query(default=""), q: str = Query(default=""), limit: int = Query(default=20)) -> Any:
            """List or search long-term memory."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            try:
                mem = getattr(self.brain, "memory", None)
                if mem is None:
                    return JSONResponse({"facts": [], "total": 0})
                if q.strip():
                    hits = await mem.recall(q.strip(), k=max(1, min(50, int(limit))))
                    facts = []
                    for h in hits:
                        # h may be dict, object with .text/.score/.category, or plain string
                        if isinstance(h, dict):
                            facts.append({"text": str(h.get("text", h.get("fact", str(h)))), "score": float(h.get("score", 0) or 0), "id": str(h.get("id", "")), "category": str(h.get("category", h.get("label", "fact"))), "when": str(h.get("when", h.get("created", "")))})
                        else:
                            facts.append({"text": getattr(h, "text", str(h)), "score": float(getattr(h, "score", 0) or 0), "id": str(getattr(h, "id", "")), "category": str(getattr(h, "category", getattr(h, "label", "fact"))), "when": str(getattr(h, "when", getattr(h, "created", ""))) })
                    return JSONResponse({"facts": facts, "total": len(facts)})
                stats = {}
                try:
                    stats = await mem.stats() if hasattr(mem, "stats") else {}
                except Exception:
                    stats = {}
                facts = []
                try:
                    if hasattr(mem, "recall"):
                        hits = await mem.recall("user", k=max(1, min(50, int(limit))))
                        for h in hits:
                            if isinstance(h, dict):
                                facts.append({"text": str(h.get("text", h.get("fact", str(h)))), "score": float(h.get("score", 0) or 0), "category": str(h.get("category", h.get("label", "fact"))), "when": str(h.get("when", h.get("created", "")))})
                            else:
                                facts.append({"text": getattr(h, "text", str(h)), "score": float(getattr(h, "score", 0) or 0), "category": str(getattr(h, "category", getattr(h, "label", "fact"))), "when": str(getattr(h, "when", getattr(h, "created", ""))) })
                except Exception:
                    facts = []
                return JSONResponse({"facts": facts[:limit], "total": stats.get("long_term", stats.get("entries", len(facts))) if isinstance(stats, dict) else len(facts), "backend": stats.get("backend", "") if isinstance(stats, dict) else ""})
            except Exception as exc:
                logger.debug("Memory list failed: %s", exc)
                return JSONResponse({"facts": [], "total": 0})

        @app.post("/api/memory")
        async def manage_memory(request: Request, token: str = Query(default="")) -> Any:
            """Remember or forget a fact."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            try:
                payload: Dict[str, Any] = await request.json()
            except Exception:
                payload = {}
            action = str(payload.get("action", "") or "").strip().lower()
            text_mem = str(payload.get("text", "") or "").strip()
            if not text_mem:
                raise HTTPException(status_code=400, detail="missing 'text'")
            mem = getattr(self.brain, "memory", None)
            if mem is None:
                raise HTTPException(status_code=503, detail="memory unavailable")
            try:
                if action in {"forget", "delete", "remove"}:
                    removed = await mem.forget(text_mem)
                    return JSONResponse({"ok": True, "removed": int(removed or 0)})
                else:
                    ok = await mem.remember(text_mem, category=str(payload.get("category", "fact")))
                    return JSONResponse({"ok": bool(ok)})
            except Exception as exc:
                logger.warning("Memory manage failed: %s", exc)
                raise HTTPException(status_code=500, detail="memory failed")

        @app.get("/api/doctor")
        async def doctor(token: str = Query(default="")) -> Any:
            """JSON doctor for the web panel (no shell)."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            try:
                from utils.doctor import diagnose
                report = await diagnose(self.config, root=self.config.root if hasattr(self.config, "root") else None)
                return JSONResponse(report.as_dict())
            except Exception as exc:
                logger.warning("Doctor failed: %s", exc)
                raise HTTPException(status_code=500, detail="doctor failed")

        @app.get("/api/system/status")
        async def system_status(token: str = Query(default="")) -> Any:
            """Whether system_control is paused (kill-switch)."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            return JSONResponse({"paused": self._paused, "confirm_dangerous": bool(self.config.get("security.confirm_dangerous", True)), "allowed_roots": self.config.get("security.allowed_roots", [])})

        @app.post("/api/system/pause")
        async def system_pause(request: Request, token: str = Query(default="")) -> Any:
            """Kill-switch: pause/unpause system_control + vision + shell."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            # Toggle if no explicit value
            if "paused" in payload:
                self._paused = bool(payload["paused"])
            else:
                self._paused = not self._paused
            # Also reflect in brain if it has a flag
            try:
                brain = self.brain
                if hasattr(brain, "paused"):
                    brain.paused = self._paused
            except Exception:
                pass
            logger.warning("System pause toggled to %s via web UI", self._paused)
            return JSONResponse({"paused": self._paused})

        @app.post("/api/piper/install")
        async def piper_install(token: str = Query(default="")) -> Any:
            """Download the offline Piper voice (en_GB-alan-medium, ~65MB)."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            # Rate-limit: only one install at a time
            if self._rate_limited("piper_install"):
                raise HTTPException(status_code=429, detail="install in progress, slow down")
            try:
                piper_dir = self.config.resolve("data/piper")
                if any(piper_dir.glob("*.onnx")) if piper_dir.exists() else False:
                    return JSONResponse({"ok": True, "already": True})
                # Lazy import the installer from install.py's logic
                # We reuse the same URLs as install.py
                PIPER_VOICE_NAME = "en_GB-alan-medium"
                PIPER_VOICE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/"
                import shutil
                import urllib.request
                piper_dir.mkdir(parents=True, exist_ok=True)
                model = piper_dir / f"{PIPER_VOICE_NAME}.onnx"
                cfg = piper_dir / f"{PIPER_VOICE_NAME}.onnx.json"
                def _dl(url: str, dest: Path) -> bool:
                    try:
                        with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
                            shutil.copyfileobj(r, f)
                        return dest.exists() and dest.stat().st_size > 1024
                    except Exception as e:
                        logger.warning("Piper download failed: %s", e)
                        return False
                ok1 = _dl(f"{PIPER_VOICE_BASE}{PIPER_VOICE_NAME}.onnx", model)
                ok2 = _dl(f"{PIPER_VOICE_BASE}{PIPER_VOICE_NAME}.onnx.json", cfg)
                if ok1 and ok2:
                    return JSONResponse({"ok": True, "already": False, "voice": PIPER_VOICE_NAME})
                # Cleanup partial
                try:
                    if not ok1: model.unlink(missing_ok=True)
                    if not ok2: cfg.unlink(missing_ok=True)
                except Exception:
                    pass
                raise HTTPException(status_code=503, detail="download failed")
            except HTTPException:
                raise
            except Exception as exc:
                logger.warning("Piper install failed: %s", exc)
                raise HTTPException(status_code=500, detail="piper install failed")

        @app.get("/api/tts")
        async def tts(text: str = Query(...), token: str = Query(default=""), voice: str = Query(default=""), engine: str = Query(default="")) -> Any:
            """Render text to speech and return an audio file.

            Optional ``voice`` and ``engine`` override the config for a preview
            without persisting the change. ``voice`` is an ElevenLabs voice_id
            when engine is elevenlabs, otherwise an edge-tts ShortName.
            """
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            tts_engine = await self._tts_engine()
            if tts_engine is None:
                raise HTTPException(status_code=503, detail="tts unavailable")
            if self._rate_limited("tts"):
                raise HTTPException(status_code=429, detail="too much speech")
            # Preview overrides — temporary, does not write to config.yaml.
            # Snapshot so a preview does not poison the next plain /api/tts call.
            _orig_engine = getattr(tts_engine, "engine", "")
            _orig_voice = getattr(tts_engine, "voice", "")
            _orig_eid = getattr(tts_engine, "elevenlabs_voice_id", "")
            _orig_active = getattr(tts_engine, "active_engine", "")
            if engine or voice:
                try:
                    if engine:
                        tts_engine.engine = engine.lower().strip()
                        await tts_engine.initialize(require_player=False)
                    if voice:
                        if tts_engine.active_engine == "elevenlabs" or (engine and engine.lower().strip() in ("elevenlabs", "eleven", "eleven_labs")):
                            tts_engine.elevenlabs_voice_id = voice.strip()
                        else:
                            tts_engine.voice = voice.strip()
                except Exception as exc:
                    logger.debug("TTS preview override failed: %s", exc)
            path: Optional[Path] = await tts_engine.synthesize(text[:1500])
            # Restore originals after preview so state does not drift.
            if engine or voice:
                try:
                    tts_engine.engine = _orig_engine
                    tts_engine.voice = _orig_voice
                    tts_engine.elevenlabs_voice_id = _orig_eid
                    # Re-initialise to the original engine if it changed.
                    if getattr(tts_engine, "active_engine", "") != _orig_active:
                        await tts_engine.initialize(require_player=False)
                except Exception:
                    pass
            if path is None or not path.exists():
                raise HTTPException(status_code=503, detail="synthesis failed")
            media = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"
            return FileResponse(str(path), media_type=media,
                                filename=f"reply{path.suffix or '.mp3'}")

        @app.get("/manifest.webmanifest")
        async def manifest(token: str = Query(default="")) -> Any:
            """Serve the PWA manifest so the page installs to a home screen."""
            suffix = f"?token={token}" if token else ""
            return JSONResponse(
                {
                    "name": self.title,
                    "short_name": self.title,
                    "description": "Your local AI assistant.",
                    "start_url": f"/{suffix}",
                    "scope": "/",
                    "display": "standalone",
                    "orientation": "portrait",
                    "background_color": "#000000",
                    "theme_color": "#000000",
                    "icons": [
                        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png",
                         "purpose": "any"},
                        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png",
                         "purpose": "any"},
                        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png",
                         "purpose": "maskable"},
                    ],
                },
                media_type="application/manifest+json",
            )

        @app.get("/sw.js")
        async def service_worker() -> Any:
            """Serve the offline shell worker (never behind the token gate)."""
            return Response(content=SERVICE_WORKER, media_type="application/javascript",
                            headers={"Cache-Control": "no-store, must-revalidate"})

        @app.get("/icon-{size}.png")
        async def icon(size: int) -> Any:
            """Render an app icon at the requested size."""
            if size not in (180, 192, 512):
                raise HTTPException(status_code=404, detail="no such icon")
            if size not in self._icons:
                self._icons[size] = render_icon(size)
            return Response(content=self._icons[size], media_type="image/png",
                            headers={"Cache-Control": "public, max-age=86400"})

        @app.post("/api/listen")
        async def listen(request: Request, token: str = Query(default="")) -> Any:
            """Transcribe a recording made in the browser.

            The phone has a microphone but no Whisper; this machine has
            Whisper. The browser posts the raw audio blob and gets text back.
            """
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            client = request.client.host if request.client else "unknown"
            if self._rate_limited(client):
                raise HTTPException(status_code=429, detail="slow down a moment, sir")

            audio = await request.body()
            if not audio:
                raise HTTPException(status_code=400, detail="no audio received")
            if len(audio) > self.max_audio_bytes:
                raise HTTPException(status_code=413, detail="that recording is too long")

            stt = await self._speech_to_text()
            if stt is None:
                raise HTTPException(
                    status_code=503,
                    detail="Speech recognition is not installed on the server. "
                           "pip install faster-whisper, sir.",
                )

            suffix = {
                "audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".mp4",
                "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
            }.get((request.headers.get("content-type", "").split(";")[0] or "").strip(),
                  ".webm")

            temporary = (Path(tempfile.gettempdir())
                         / f"jarvis-listen-{secrets.token_hex(6)}{suffix}")
            try:
                temporary.write_bytes(audio)
                text = await stt.transcribe_file(temporary)
            except Exception as exc:
                logger.warning("Browser transcription failed: %s", exc)
                raise HTTPException(status_code=500, detail="transcription failed") from exc
            finally:
                with contextlib.suppress(Exception):
                    temporary.unlink()

            logger.info("Transcribed %s of browser audio: %r",
                        human_bytes(len(audio)), truncate(text, 60))
            return JSONResponse({"text": text})

        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket) -> None:
            """Stream replies token-by-token to a connected browser."""
            token = websocket.query_params.get("token", "")
            if not self._authorised(token):
                await websocket.close(code=1008)
                return
            peer = websocket.client.host if websocket.client else "unknown"
            await websocket.accept()
            self._sockets.add(websocket)
            self._watch_the_brain()
            self.clients += 1
            logger.info("Web client connected (%d active).", self.clients)
            try:
                while True:
                    raw = await websocket.receive_text()
                    try:
                        message = json.loads(raw)
                    except Exception:
                        message = {"text": raw}

                    if message.get("command") == "cancel":
                        self.brain.cancel()
                        await websocket.send_text(
                            json.dumps({"type": "status", "text": "cancelled"})
                        )
                        continue

                    text = str(message.get("text", "")).strip()
                    if len(text) > MAX_MESSAGE_CHARS:
                        await websocket.send_text(json.dumps(
                            {"type": "error",
                             "text": f"That message is rather long, sir — keep it under "
                                     f"{MAX_MESSAGE_CHARS} characters."}
                        ))
                        continue
                    if text and self._rate_limited(peer):
                        await websocket.send_text(json.dumps(
                            {"type": "error",
                             "text": "That is a lot of questions for one minute, sir. "
                                     "Give me a moment."}
                        ))
                        continue
                    if not text:
                        continue
                    await self._handle_turn(websocket, text)
            except WebSocketDisconnect:
                pass
            except Exception as exc:
                logger.debug("WebSocket error: %s", truncate(str(exc), 160))
            finally:
                self._sockets.discard(websocket)
                self.clients = max(0, self.clients - 1)
                logger.info("Web client disconnected (%d active).", self.clients)

        return app

    async def _speech_to_text(self) -> Optional[Any]:
        """Return a loaded Whisper engine, sharing the voice pipeline's if there is one.

        Returns:
            A ``SpeechToText`` instance, or ``None`` when faster-whisper is
            not installed.
        """
        voice = getattr(self.brain, "voice", None)
        existing = getattr(voice, "stt", None) if voice is not None else None
        if existing is not None and getattr(existing, "available", False):
            return existing
        if self._stt is not None:
            return self._stt
        if self._stt_tried:
            return None
        self._stt_tried = True
        try:
            from interfaces.voice import SpeechToText

            engine = SpeechToText(self.config)
            if await engine.initialize():
                self._stt = engine
                return engine
        except Exception as exc:
            logger.warning("Could not start speech recognition for the web UI: %s", exc)
        return None

    async def broadcast(self, message: str, kind: str = "notice") -> None:
        """Push an unprompted message to every open browser tab.

        Reminders, timers and scheduled jobs fire whether or not anyone is
        typing, so they are pushed to connected clients instead of being lost.

        Args:
            message: The text to show.
            kind: Message type understood by the front-end (``notice``).
        """
        if not self._sockets:
            return
        payload = json.dumps({"type": kind, "text": message})
        for socket in list(self._sockets):
            try:
                await socket.send_text(payload)
            except Exception:
                self._sockets.discard(socket)

    def _watch_the_brain(self) -> None:
        """Relay the brain's internal events to connected browsers.

        The brain already announces which module it picked and which tools it
        ran; forwarding that turns the interface from a text box into
        something that shows its working.
        """
        events = getattr(self.brain, "events", None)
        if events is None or self._watching:
            return

        def relay(event: Any) -> None:
            """Push one event out to the sockets, best effort."""
            if event.name not in {"turn.intent", "tool.called", "tool.result",
                                  "error.raised"}:
                return
            payload = json.dumps({"type": "event", "name": event.name, "data": event.data})
            for socket in list(self._sockets):
                task = asyncio.ensure_future(self._send_quietly(socket, payload))
                self._relays.add(task)
                task.add_done_callback(self._relays.discard)

        events.subscribe("*", relay)
        self._watching = True

    async def _send_quietly(self, socket: Any, payload: str) -> None:
        """Send to one socket, dropping it if it has gone away.

        Args:
            socket: The WebSocket to write to.
            payload: The JSON text to send.
        """
        try:
            await socket.send_text(payload)
        except Exception:
            self._sockets.discard(socket)

    def _ask_over_websocket(self, websocket: Any) -> Any:
        """Build the security confirmation hook for one browser turn.

        Returns:
            An ``async (prompt) -> bool`` callable that renders an approval
            card in the browser and waits for the user's answer.
        """

        async def ask(prompt: str) -> bool:
            self._confirm_seq += 1
            seq = self._confirm_seq
            await websocket.send_text(json.dumps({
                "type": "confirm",
                "id": seq,
                "text": truncate(prompt, 600),
            }))
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 300.0
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return False
                try:
                    raw = await asyncio.wait_for(
                        websocket.receive_text(), timeout=remaining
                    )
                except Exception:
                    # Socket died or the user never answered — deny by default.
                    return False
                try:
                    message = json.loads(raw)
                except Exception:
                    continue
                if message.get("command") == "cancel":
                    return False
                if message.get("type") == "confirm" and message.get("id") == seq:
                    return bool(message.get("reply", False))
                # Anything else (a stray token command) is not the answer.

        return ask

    async def _handle_turn(self, websocket: Any, text: str) -> None:
        """Run one request, streaming tokens back to the browser."""
        loop = asyncio.get_running_loop()
        started = loop.time()
        queue: "asyncio.Queue[Optional[str]]" = asyncio.Queue()

        def on_token(token: str) -> None:
            """Hand a generated token to the sender task."""
            queue.put_nowait(token)

        async def pump() -> None:
            """Forward tokens to the socket in order."""
            while True:
                token = await queue.get()
                if token is None:
                    return
                try:
                    await websocket.send_text(json.dumps({"type": "token", "text": token}))
                except Exception:
                    return

        sender = asyncio.create_task(pump())
        security = getattr(self.brain, "security", None)
        try:
            # Dangerous tools (editing his own code, installing packages) ask
            # for approval. Over the web the terminal may not exist, so ask on
            # the socket this turn came in on; restore the previous hook (the
            # CLI's) afterwards. The lock keeps two browsers from answering
            # each other's prompts.
            async with self._confirm_lock:
                previous_hook = None
                if security is not None:
                    previous_hook = getattr(security, "_confirm_hook", None)
                    security.set_confirm_hook(self._ask_over_websocket(websocket))
                try:
                    reply = await self.brain.process(text, on_token=on_token)
                except Exception as exc:
                    logger.exception("Web turn failed")
                    reply = ""
                    with_error = {"type": "error", "text": truncate(str(exc), 200)}
                    await websocket.send_text(json.dumps(with_error))
                finally:
                    if security is not None:
                        security.set_confirm_hook(previous_hook)
        finally:
            queue.put_nowait(None)
            await sender

        intent = getattr(self.brain, "last_intent", None)
        await websocket.send_text(
            json.dumps(
                {
                    "type": "reply",
                    "text": reply,
                    "intent": getattr(intent, "module", "") if intent else "",
                    "seconds": round(loop.time() - started, 2),
                }
            )
        )

    # ----------------------------------------------------------------- server
    async def serve(self) -> None:
        """Run the HTTP server until :meth:`stop` is called."""
        try:
            import uvicorn
        except Exception as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "The web interface needs uvicorn: pip install 'uvicorn[standard]>=0.29'"
            ) from exc

        self._check_websocket_support()
        settings = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
            ws_ping_interval=20,
            ws_ping_timeout=20,
        )
        self._server = uvicorn.Server(settings)
        # uvicorn would otherwise steal Ctrl-C from the host application.
        self._server.install_signal_handlers = (  # type: ignore[method-assign,attr-defined]
            lambda: None
        )
        logger.info("Web interface on http://%s:%d", self.host, self.port)
        await self._server.serve()

    @staticmethod
    def _check_websocket_support() -> None:
        """Warn when uvicorn cannot do WebSockets, before it silently fails.

        Plain ``uvicorn`` (without the ``[standard]`` extra) serves HTTP fine and
        rejects every upgrade request, so the page loads, the orb spins and the
        status reads "connecting" forever — with the only clue buried in
        uvicorn's own warnings. Chat, streaming replies and spoken answers all
        ride that socket, so it is worth one explicit line at start-up.
        """
        try:
            import websockets  # noqa: F401
            return
        except Exception:
            pass
        try:
            import wsproto  # noqa: F401
            return
        except Exception:
            pass
        logger.warning(
            "No WebSocket library found — the page will load but chat will hang "
            "on 'connecting'. Fix with: pip install 'uvicorn[standard]>=0.29' "
            "(or: pip install websockets)"
        )

    async def stop(self) -> None:
        """Ask the server to shut down."""
        if self._server is not None:
            self._server.should_exit = True


def local_addresses(port: int) -> List[str]:
    """Best-effort list of URLs this machine can be reached on.

    Args:
        port: The port the server is listening on.

    Returns:
        A list of ``http://…`` URLs, LAN address first when discoverable.
    """
    import socket

    urls = [f"http://localhost:{port}/"]
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.settimeout(0.2)
        probe.connect(("8.8.8.8", 80))
        address = probe.getsockname()[0]
        probe.close()
        if address and not address.startswith("127."):
            urls.insert(0, f"http://{address}:{port}/")
    except Exception:
        pass
    return urls


__all__ = ["WebInterface", "local_addresses"]
