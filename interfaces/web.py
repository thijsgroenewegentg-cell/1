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

    A dark rounded square with a cyan reactor ring — enough for a home-screen
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
    background = (11, 15, 20)
    ring = (56, 189, 248)

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
            "<!doctype html><meta charset=utf-8><style>body{background:#0b0f14;color:#7d8da1;"
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

#: Shown only if that file is missing from an installation.
FALLBACK_PAGE = """<!doctype html><meta charset="utf-8">
<title>__TITLE__</title>
<body style="background:#070b11;color:#e8eef6;font:16px system-ui;padding:40px">
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
                # the browser plays what we synthesise; the server needs no speaker
                if await engine.initialize(needs_player=False):
                    self._tts = engine
            except Exception as exc:
                logger.debug("Web TTS unavailable: %s", exc)
                self._tts = None
        return self._tts

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
            """Serve the chat page."""
            if not self._authorised(token):
                return HTMLResponse(
                    "<h1>401</h1><p>Append ?token=… to the URL.</p>", status_code=401
                )
            return HTMLResponse(rendered_page())

        @app.get("/api/status")
        async def status(token: str = Query(default="")) -> Any:
            """Report assistant status and a greeting."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            report = await self.brain.status_report()
            return JSONResponse(
                {
                    "greeting": await self.brain.greeting(),
                    "llm": report.get("llm", {}),
                    "modules": report.get("modules", []),
                    "memory": report.get("memory", {}),
                    "clients": self.clients,
                }
            )

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

        @app.get("/api/memory")
        async def memory_list(
            token: str = Query(default=""),
            keyword: str = Query(default=""),
            limit: int = Query(default=60),
        ) -> Any:
            """List what JARVIS remembers, for the memory pane."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            memory = getattr(self.brain, "memory", None)
            if memory is None:
                return JSONResponse({"facts": [], "summary": ""})
            facts = await memory.search_facts(keyword, max(1, min(200, int(limit))))
            return JSONResponse(
                {
                    "facts": facts,
                    "summary": getattr(memory, "conversation_summary", "") or "",
                }
            )

        @app.post("/api/remember")
        async def remember(request: Request, token: str = Query(default="")) -> Any:
            """Store a durable memory on request ("remember this")."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            try:
                payload: Dict[str, Any] = await request.json()
            except Exception:
                payload = {}
            text = str(payload.get("text", "")).strip()
            if not text:
                raise HTTPException(status_code=400, detail="missing 'text'")
            memory = getattr(self.brain, "memory", None)
            ok = bool(memory is not None and await memory.remember(
                text, category=str(payload.get("category", "note")), source="web"))
            return JSONResponse({"ok": ok})

        @app.post("/api/forget")
        async def forget(request: Request, token: str = Query(default="")) -> Any:
            """Delete memories matching a keyword."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            try:
                payload: Dict[str, Any] = await request.json()
            except Exception:
                payload = {}
            keyword = str(payload.get("keyword", "")).strip()
            if not keyword:
                raise HTTPException(status_code=400, detail="missing 'keyword'")
            memory = getattr(self.brain, "memory", None)
            removed = int(await memory.forget(keyword)) if memory is not None else 0
            return JSONResponse({"removed": removed})

        @app.get("/api/tts")
        async def tts(text: str = Query(...), token: str = Query(default="")) -> Any:
            """Render text to speech and return an audio file."""
            if not self._authorised(token):
                raise HTTPException(status_code=401, detail="bad token")
            engine = await self._tts_engine()
            if engine is None:
                raise HTTPException(status_code=503, detail="tts unavailable")
            if self._rate_limited("tts"):
                raise HTTPException(status_code=429, detail="too much speech")
            path: Optional[Path] = await engine.synthesize(text[:1500])
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
                    "background_color": "#0b0f14",
                    "theme_color": "#0b0f14",
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
            return Response(content=SERVICE_WORKER, media_type="application/javascript")

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
        try:
            reply = await self.brain.process(text, on_token=on_token)
        except Exception as exc:
            logger.exception("Web turn failed")
            reply = ""
            with_error = {"type": "error", "text": truncate(str(exc), 200)}
            await websocket.send_text(json.dumps(with_error))
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
                "The web interface needs uvicorn: pip install 'uvicorn>=0.29'"
            ) from exc

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
