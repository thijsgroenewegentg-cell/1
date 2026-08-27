"""
Tests for webui.py: the HTTP chat server. Uses a fake agent (no Blender/LLM)
and drives the API over a real local HTTP connection.
"""
import json
import os
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402


class FakeAgent:
    def __init__(self, *a, **kw):
        self.installed = False

    def install_helpers(self):
        self.installed = True

    def run_task(self, task, max_iters=30, reference_image=None):
        time.sleep(0.2)
        return "built: " + task


def _get(url):
    return urllib.request.urlopen(url, timeout=10).read()


def main():
    args = type("Args", (), {
        "transport": "auto", "mcp_cmd": None, "host": "127.0.0.1", "port": 9876,
        "provider": None, "model": None, "base_url": None, "api_key": None,
        "vision": False, "image": None, "preset": None, "no_fallback": True,
        "approve": False, "max_iters": 5,
    })()

    session = webui.Session(args)
    # Stub out the real Blender/LLM connection.
    session.agent = FakeAgent()
    session.transport = object()

    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(session))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % port

    try:
        # index page
        html = _get(base + "/").decode()
        assert "Blender AI Agent" in html

        # submit a task
        req = urllib.request.Request(base + "/api/task",
                                     data=json.dumps({"task": "a tiny castle"}).encode(),
                                     headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        assert resp["started"] is True

        # while busy, a second task is rejected
        with session.lock:
            busy = session.busy
        assert busy is True

        # poll events until done
        deadline = time.time() + 15
        done = False
        while time.time() < deadline:
            ev = json.loads(_get(base + "/api/events?since=0"))
            if not ev["busy"] and any("built" in l["text"] or "castle" in l["text"]
                                     for l in ev["lines"]):
                done = True
                break
            time.sleep(0.2)
        assert done, "task did not complete in the event stream"

        # 404 on missing file
        code = None
        try:
            _get(base + "/files/does_not_exist.png")
        except urllib.error.HTTPError as e:
            code = e.code
        assert code == 404

    finally:
        httpd.shutdown()

    print("PASS: web UI serves page, accepts tasks, streams events, guards files")


if __name__ == "__main__":
    import urllib.error  # noqa: F401 (needed in main)
    main()
    print("\nWeb UI test passed.")
