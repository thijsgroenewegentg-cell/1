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
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.helpers import truncate
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
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

    HAS_FASTAPI = True
except Exception:  # pragma: no cover - optional dependency
    HAS_FASTAPI = False
    FastAPI = None  # type: ignore[assignment]

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b0f14">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #0b0f14; --panel: #121821; --line: #1e2836; --text: #e6edf3;
    --dim: #7d8da1; --accent: #38bdf8; --accent-dim: #0ea5e9; --user: #1d4ed8;
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg); color: var(--text); display: flex; flex-direction: column;
    font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Ubuntu, sans-serif;
  }
  header {
    display: flex; align-items: center; gap: 10px; padding: 14px 16px;
    border-bottom: 1px solid var(--line); background: var(--panel);
    padding-top: calc(14px + env(safe-area-inset-top));
  }
  header h1 { font-size: 17px; margin: 0; letter-spacing: .14em; font-weight: 600; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: #f87171; flex: none; }
  .dot.on { background: #34d399; box-shadow: 0 0 10px #34d39988; }
  #meta { margin-left: auto; color: var(--dim); font-size: 12px; text-align: right; }
  #log { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  .msg { max-width: 82%; padding: 10px 13px; border-radius: 14px; white-space: pre-wrap;
         word-wrap: break-word; overflow-wrap: anywhere; }
  .me { align-self: flex-end; background: var(--user); border-bottom-right-radius: 4px; }
  .ai { align-self: flex-start; background: var(--panel); border: 1px solid var(--line);
        border-bottom-left-radius: 4px; }
  .ai.pending::after { content: "▌"; color: var(--accent); animation: blink 1s steps(1) infinite; }
  @keyframes blink { 50% { opacity: 0; } }
  .sys { align-self: center; color: var(--dim); font-size: 13px; text-align: center; }
  .ai code, .me code { background: #0008; padding: 1px 5px; border-radius: 5px;
                       font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 90%; }
  .ai pre { background: #0b0f14; border: 1px solid var(--line); border-radius: 10px;
            padding: 10px; overflow-x: auto; }
  footer { border-top: 1px solid var(--line); background: var(--panel); padding: 10px;
           padding-bottom: calc(10px + env(safe-area-inset-bottom)); }
  form { display: flex; gap: 8px; align-items: flex-end; }
  textarea {
    flex: 1; resize: none; min-height: 44px; max-height: 140px; padding: 11px 13px;
    border-radius: 12px; border: 1px solid var(--line); background: #0b0f14;
    color: var(--text); font: inherit; outline: none;
  }
  textarea:focus { border-color: var(--accent-dim); }
  button { border: 0; border-radius: 12px; padding: 0 16px; height: 44px; font: inherit;
           font-weight: 600; background: var(--accent); color: #04121c; cursor: pointer; }
  button.ghost { background: transparent; color: var(--dim); border: 1px solid var(--line);
                 padding: 0 12px; font-weight: 400; }
  button:disabled { opacity: .5; cursor: default; }
  .row { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
  .chip { border: 1px solid var(--line); border-radius: 999px; padding: 5px 11px;
          color: var(--dim); font-size: 13px; background: transparent; cursor: pointer; height: auto; }
</style>
</head>
<body>
<header>
  <span class="dot" id="dot"></span>
  <h1>__TITLE__</h1>
  <span id="meta">connecting…</span>
</header>
<div id="log"></div>
<footer>
  <form id="form">
    <textarea id="input" rows="1" placeholder="Ask me something, sir…" autocomplete="off"></textarea>
    <button id="send" type="submit">Send</button>
    <button id="stop" class="ghost" type="button" title="Stop the current reply">Stop</button>
  </form>
  <div class="row">
    <button class="chip" type="button" data-say="What's the weather?">weather</button>
    <button class="chip" type="button" data-say="Give me my daily briefing">briefing</button>
    <button class="chip" type="button" data-say="What's on my calendar today?">calendar</button>
    <button class="chip" type="button" data-say="system stats">system</button>
    <button class="chip" type="button" id="speaker">🔊 speech: off</button>
  </div>
</footer>
<script>
const token = new URLSearchParams(location.search).get("token") || "";
const log = document.getElementById("log");
const dot = document.getElementById("dot");
const meta = document.getElementById("meta");
const input = document.getElementById("input");
const form = document.getElementById("form");
const sendButton = document.getElementById("send");
const speakerButton = document.getElementById("speaker");
let socket = null, pending = null, speech = false, busy = false;

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function render(text) {
  let html = escapeHtml(text);
  html = html.replace(/```([\\s\\S]*?)```/g, (m, code) => "<pre>" + code.trim() + "</pre>");
  html = html.replace(/`([^`\\n]+)`/g, "<code>$1</code>");
  html = html.replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>");
  return html;
}
function bubble(cls, text) {
  const node = document.createElement("div");
  node.className = "msg " + cls;
  node.innerHTML = render(text || "");
  log.appendChild(node);
  log.scrollTop = log.scrollHeight;
  return node;
}
function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(scheme + "://" + location.host + "/ws" + (token ? "?token=" + encodeURIComponent(token) : ""));
  socket.onopen = () => { dot.classList.add("on"); meta.textContent = "connected"; };
  socket.onclose = () => {
    dot.classList.remove("on"); meta.textContent = "reconnecting…";
    busy = false; sendButton.disabled = false; setTimeout(connect, 2000);
  };
  socket.onerror = () => { meta.textContent = "connection error"; };
  socket.onmessage = event => {
    const data = JSON.parse(event.data);
    if (data.type === "token") {
      if (!pending) pending = bubble("ai pending", "");
      pending.dataset.text = (pending.dataset.text || "") + data.text;
      pending.innerHTML = render(pending.dataset.text);
      log.scrollTop = log.scrollHeight;
    } else if (data.type === "reply") {
      const text = data.text || (pending && pending.dataset.text) || "";
      if (pending) { pending.className = "msg ai"; pending.innerHTML = render(text); }
      else bubble("ai", text);
      pending = null; busy = false; sendButton.disabled = false;
      meta.textContent = data.intent ? data.intent + " · " + (data.seconds || 0).toFixed(1) + "s" : "connected";
      if (speech && text) speak(text);
    } else if (data.type === "status") {
      meta.textContent = data.text;
    } else if (data.type === "error") {
      bubble("sys", "⚠ " + data.text); pending = null; busy = false; sendButton.disabled = false;
    }
  };
}
function speak(text) {
  const audio = new Audio("/api/tts?text=" + encodeURIComponent(text.slice(0, 900)) + (token ? "&token=" + encodeURIComponent(token) : ""));
  audio.play().catch(() => {});
}
function send(text) {
  if (!text.trim() || busy || !socket || socket.readyState !== 1) return;
  bubble("me", text);
  socket.send(JSON.stringify({ text }));
  busy = true; sendButton.disabled = true; meta.textContent = "thinking…";
  input.value = ""; input.style.height = "auto";
}
form.addEventListener("submit", event => { event.preventDefault(); send(input.value); });
input.addEventListener("input", () => {
  input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px";
});
input.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(input.value); }
});
document.getElementById("stop").addEventListener("click", () => {
  if (socket && socket.readyState === 1) socket.send(JSON.stringify({ command: "cancel" }));
  busy = false; sendButton.disabled = false;
});
document.querySelectorAll("[data-say]").forEach(chip =>
  chip.addEventListener("click", () => send(chip.dataset.say)));
speakerButton.addEventListener("click", () => {
  speech = !speech;
  speakerButton.textContent = "🔊 speech: " + (speech ? "on" : "off");
});
fetch("/api/status" + (token ? "?token=" + encodeURIComponent(token) : ""))
  .then(response => response.json())
  .then(data => bubble("sys", data.greeting || "JARVIS online."))
  .catch(() => bubble("sys", "JARVIS online."));
connect();
</script>
</body>
</html>
"""


class WebInterface:
    """FastAPI + WebSocket front-end that runs alongside the CLI."""

    def __init__(
        self,
        brain: Any,
        config: Any,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        """Args:
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
                if await engine.initialize():
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
        page = PAGE.replace("__TITLE__", self.title)

        @app.get("/", response_class=HTMLResponse)
        async def index(token: str = Query(default="")) -> Any:
            """Serve the chat page."""
            if not self._authorised(token):
                return HTMLResponse(
                    "<h1>401</h1><p>Append ?token=… to the URL.</p>", status_code=401
                )
            return HTMLResponse(page)

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

        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket) -> None:
            """Stream replies token-by-token to a connected browser."""
            token = websocket.query_params.get("token", "")
            if not self._authorised(token):
                await websocket.close(code=1008)
                return
            peer = websocket.client.host if websocket.client else "unknown"
            await websocket.accept()
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
            except Exception as exc:  # noqa: BLE001 - a dead socket must not kill the app
                logger.debug("WebSocket error: %s", truncate(str(exc), 160))
            finally:
                self.clients = max(0, self.clients - 1)
                logger.info("Web client disconnected (%d active).", self.clients)

        return app

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
        except Exception as exc:  # noqa: BLE001 - report, never crash
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
        self._server.install_signal_handlers = lambda: None  # type: ignore[assignment]
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
