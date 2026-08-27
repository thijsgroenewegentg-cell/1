#!/usr/bin/env python3
"""
Local web chat UI for the Blender AI agent. Stdlib only.

    python webui.py                 # http://localhost:8765
    python webui.py --vision --transport blendermcp

It reuses agent.py exactly (same flags), runs tasks in a background thread,
streams the log to the browser, and shows the agent's renders/screenshots
inline. Files in output/ are downloadable.
"""

import argparse
import html
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import agent as agent_mod

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = agent_mod.DEFAULT_OUT_DIR


class Session:
    def __init__(self, args):
        self.args = args
        self.log_lines = []
        self.lock = threading.Lock()
        self.busy = False
        self.transport = None
        self.agent = None
        self._init_lock = threading.Lock()

    def log(self, *parts):
        line = " ".join(str(p) for p in parts)
        with self.lock:
            self.log_lines.append({"t": time.time(), "text": line})

    def ensure_agent(self):
        with self._init_lock:
            if self.agent is None:
                t = agent_mod.connect_blender(self.args)
                primary = agent_mod.detect_provider(self.args.provider)
                text_clients = agent_mod._chain(primary, self.args, vision=False)
                vision_clients = (agent_mod._chain(primary, self.args, vision=True)
                                  if self.args.vision else text_clients)
                self.transport = t
                self.agent = agent_mod.BlenderAgent(
                    t, text_clients, vision_clients,
                    vision=self.args.vision, approve=False, log=self.log)
                if self.args.preset:
                    self.agent.install_helpers()
                    out = self.agent._exec(agent_mod.preset_code(self.args.preset))
                    self.log("[preset]", self.args.preset,
                             (out.get("stdout") or out.get("error") or "").strip())
            return self.agent

    def submit(self, task):
        with self.lock:
            if self.busy:
                return False
            self.busy = True
            self.log_lines.append({"t": time.time(), "text": "you > " + task, "you": True})
        threading.Thread(target=self._run, args=(task,), daemon=True).start()
        return True

    def _run(self, task):
        try:
            ag = self.ensure_agent()
            ag.run_task(task, max_iters=self.args.max_iters,
                        reference_image=self.args.image)
        except Exception as exc:
            self.log("[fatal error]", exc)
        finally:
            with self.lock:
                self.busy = False


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Blender AI Agent</title>
<style>
 :root { color-scheme: dark; }
 body { margin:0; font-family: system-ui, sans-serif; background:#0f1115; color:#e6e6e6;
        display:flex; flex-direction:column; height:100vh; }
 header { padding:10px 16px; background:#171a21; border-bottom:1px solid #262a33;
          display:flex; align-items:center; gap:12px; }
 header h1 { font-size:16px; margin:0; font-weight:600; }
 #status { font-size:12px; color:#8b93a7; }
 #main { flex:1; overflow-y:auto; padding:16px; }
 .line { white-space:pre-wrap; word-break:break-word; font-size:13px; line-height:1.45;
          padding:2px 0; font-family: ui-monospace, Menlo, Consolas, monospace; }
 .line.you { color:#7fd0ff; }
 .line.ai { color:#9be29b; }
 .line.err { color:#ff8080; }
 .shot { max-width:480px; width:100%; border-radius:8px; margin:8px 0; border:1px solid #2a2f3a; }
 .filelink { color:#ffd479; text-decoration:none; }
 footer { padding:12px 16px; background:#171a21; border-top:1px solid #262a33; display:flex; gap:8px; }
 #task { flex:1; background:#0f1115; border:1px solid #2d323d; border-radius:8px;
         color:#e6e6e6; padding:10px 12px; font-size:14px; }
 button { background:#3b82f6; border:none; color:#fff; border-radius:8px; padding:10px 18px;
          font-size:14px; cursor:pointer; }
 button:disabled { background:#374151; cursor:wait; }
 .hint { color:#8b93a7; font-size:12px; }
</style></head>
<body>
<header>
  <h1>🤖 Blender AI Agent</h1>
  <span id="status">connecting…</span>
</header>
<div id="main"></div>
<footer>
  <input id="task" placeholder='Describe what to build, e.g. "a low-poly windmill on a hill"' autofocus>
  <button id="send">Build</button>
</footer>
<script>
const main = document.getElementById('main');
const statusEl = document.getElementById('status');
const sendBtn = document.getElementById('send');
const taskInput = document.getElementById('task');
let since = 0, busy = false;

function esc(s){ const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function renderLine(l){
  const div = document.createElement('div');
  let cls = 'line';
  let text = l.text;
  if (l.you) cls += ' you';
  if (/^AI:/.test(text)) cls += ' ai';
  if (/error|fail|traceback/i.test(text)) cls += ' err';
  div.className = cls;

  // link files in output/ and auto-show images
  const m = text.match(/(?:screenshot|render|Saved|Exported)[^:]*:\s*(\S+\\.(png|blend|glb|stl|fbx|obj))/i)
         || text.match(/(\S*output[\\/]\S+\\.(png|blend|glb|stl|fbx|obj))/i);
  let htmlText = esc(text);
  htmlText = htmlText.replace(/(\\S*output[\\/][^\\s]+\\.(png|blend|glb|stl|fbx|obj))/g,
    (f) => '<a class="filelink" href="/files/'+encodeURIComponent(f.split(/[\\\\/]/).pop())+'">'+f+'</a>');
  div.innerHTML = htmlText;
  main.appendChild(div);

  const img = text.match(/(?:screenshot|render)[^:]*:\\s*(\\S+\\.png)/i);
  if (img){
    const name = img[1].split(/[\\\\/]/).pop();
    const im = document.createElement('img');
    im.className = 'shot'; im.src = '/files/' + encodeURIComponent(name) + '?t=' + Date.now();
    main.appendChild(im);
  }
}

async function poll(){
  try{
    const r = await fetch('/api/events?since=' + since);
    const data = await r.json();
    since = data.since;
    busy = data.busy;
    statusEl.textContent = data.status;
    sendBtn.disabled = busy;
    for (const l of data.lines) renderLine(l);
    main.scrollTop = main.scrollHeight;
  }catch(e){}
}
setInterval(poll, 800); poll();

function send(){
  const task = taskInput.value.trim();
  if (!task || busy) return;
  fetch('/api/task', {method:'POST', headers:{'Content-Type':'application/json'},
                      body: JSON.stringify({task})});
  taskInput.value = '';
}
sendBtn.onclick = send;
taskInput.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
</script>
</body></html>"""


def make_handler(session):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.startswith("/api/events"):
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                since = 0
                for part in qs.split("&"):
                    if part.startswith("since="):
                        since = int(part.split("=", 1)[1])
                with session.lock:
                    lines = session.log_lines[since:]
                    total = len(session.log_lines)
                    busy = session.busy
                status = "building…" if busy else "ready"
                self._send(200, json.dumps({"lines": lines, "since": total,
                                            "busy": busy, "status": status}),
                           "application/json")
                return
            if self.path.startswith("/files/"):
                name = os.path.basename(self.path.split("/files/", 1)[1].split("?", 1)[0])
                path = os.path.join(OUT_DIR, name)
                if not os.path.isfile(path) or not os.path.abspath(path).startswith(os.path.abspath(OUT_DIR)):
                    self._send(404, "not found", "text/plain")
                    return
                ctype = "image/png" if name.endswith(".png") else "application/octet-stream"
                with open(path, "rb") as fh:
                    self._send(200, fh.read(), ctype)
                return
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE)
                return
            self._send(404, "not found", "text/plain")

        def do_POST(self):
            if not self.path.startswith("/api/task"):
                self._send(404, "not found", "text/plain")
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                task = (payload.get("task") or "").strip()
            except Exception:
                task = ""
            if not task:
                self._send(400, json.dumps({"error": "empty task"}), "application/json")
                return
            started = session.submit(task)
            self._send(200, json.dumps({"started": started,
                                        "busy": True if started else "already busy"}),
                       "application/json")

    return Handler


def main(argv=None):
    p = argparse.ArgumentParser(description="Web chat UI for the Blender AI agent.")
    # Web server
    p.add_argument("--web-host", default="0.0.0.0")
    p.add_argument("--web-port", type=int, default=8765)
    # Blender connection (consumed by agent.connect_blender via args.host/args.port)
    p.add_argument("--host", default="127.0.0.1", help="Blender bridge host")
    p.add_argument("--port", type=int, default=9876, help="Blender bridge port")
    p.add_argument("--transport", default="auto",
                   choices=["auto", "bridge", "blendermcp", "mcp-stdio"])
    p.add_argument("--mcp-cmd", default=None)
    p.add_argument("--provider", default=None, choices=sorted(agent_mod.PROVIDERS.keys()))
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("--api-key", default=None)
    p.add_argument("--vision", action="store_true")
    p.add_argument("--image", default=None)
    p.add_argument("--preset", choices=sorted(agent_mod.PRESETS))
    p.add_argument("--no-fallback", action="store_true")
    p.add_argument("--approve", action="store_true", default=False)
    p.add_argument("--max-iters", type=int, default=30)
    args = p.parse_args(argv)

    os.makedirs(OUT_DIR, exist_ok=True)
    session = Session(args)
    session.log("Web UI ready. Connecting to Blender on first task…")
    session.log("Transport: %s | vision: %s" % (args.transport, "on" if args.vision else "off"))

    httpd = ThreadingHTTPServer((args.web_host, args.web_port), make_handler(session))
    print("Web UI: http://localhost:%d  (Blender via %s)"
          % (httpd.server_address[1], args.transport))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
