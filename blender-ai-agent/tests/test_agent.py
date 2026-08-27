"""
Tests for the agent loop, vision routing, JSON repair, presets and watch mode.
Blender and LLM are mocked. Run: python3 tests/test_agent.py
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub mathutils so HELPERS_SOURCE can be exec'd outside Blender.
if "mathutils" not in sys.modules:
    mu = type(sys)("mathutils")

    class Vector(tuple):
        def __new__(cls, xyz):
            return tuple.__new__(cls, xyz)

        def __sub__(self, other):
            return Vector(tuple(a - b for a, b in zip(self, other)))

        def to_track_quat(self, *a):
            class Q:
                def to_euler(self_):
                    return (0, 0, 0)
            return Q()

    mu.Vector = Vector
    sys.modules["mathutils"] = mu

import agent  # noqa: E402


# --- mock Blender backend (transport interface) ----------------------------

class MockBackend:
    name = "mock"
    PERSISTENT_NAMESPACE = True

    def __init__(self, fresh_namespace=False):
        self.namespace = {}
        self.calls = []
        if fresh_namespace:
            self.PERSISTENT_NAMESPACE = False

    def ping(self):
        return {"blender": "mock-4.2", "scene": "Scene"}

    def scene_info(self):
        return {"blender": "mock-4.2", "scene": "Scene", "objects": []}

    def exec_code(self, code):
        self.calls.append(("exec", code))
        if not self.PERSISTENT_NAMESPACE:
            ns = {}
        else:
            ns = self.namespace
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                exec(compile(code, "<agent>", "exec"), ns)
            return {"stdout": out.getvalue(), "error": None, "extra": {}}
        except Exception:
            import traceback
            return {"stdout": out.getvalue(), "error": traceback.format_exc(), "extra": {}}

    def viewport_screenshot(self, filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\nfake")
        self.calls.append(("screenshot", filepath))
        return filepath

    def render(self, filepath):
        return self.viewport_screenshot(filepath)

    def save(self, filepath):
        self.calls.append(("save", filepath))
        open(filepath, "w").close()
        return filepath

    def export(self, filepath, fmt):
        self.calls.append(("export", fmt))
        open(filepath, "w").close()
        return filepath

    def undo(self):
        self.calls.append(("undo", None))

    def close(self):
        pass


# --- mock LLM HTTP API ------------------------------------------------------

SCRIPTED = []


class LLMHandler(BaseHTTPRequestHandler):
    last_payload = None

    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        LLMHandler.last_payload = json.loads(self.rfile.read(length).decode())
        message = SCRIPTED.pop(0)
        body = json.dumps({"choices": [{"message": message}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def tool_call(cid, name, arguments):
    return {"role": "assistant", "content": "", "tool_calls": [{
        "id": cid, "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def mock_llm_server():
    httpd = HTTPServer(("127.0.0.1", 0), LLMHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def make_llm(httpd, model="mock", vision=False):
    return agent.LLMClient(provider="ollama",
                           base_url="http://127.0.0.1:%d/v1" % httpd.server_address[1],
                           model=model, vision=vision)


# --- tests ------------------------------------------------------------------

def test_full_loop_with_vision():
    backend = MockBackend()
    httpd = mock_llm_server()
    SCRIPTED.extend([
        tool_call("c1", "get_scene_info", {}),
        tool_call("c2", "execute_blender_code", {"code": "print('built a cube')"}),
        tool_call("c3", "render_and_inspect", {"note": "check cube"}),
        tool_call("c4", "task_complete", {"summary": "cube done"}),
    ])
    ag = agent.BlenderAgent(backend, [make_llm(httpd)], [make_llm(httpd, vision=True)],
                            vision=True, log=lambda *a: None)
    summary = ag.run_task("build a cube", max_iters=8)
    assert "cube" in summary.lower()
    # screenshot happened and was attached to the conversation
    payload = LLMHandler.last_payload
    has_image = any(isinstance(m.get("content"), list) and
                    any(p.get("type") == "image_url" for p in m["content"])
                    for m in payload["messages"])
    assert has_image, "vision screenshot must be attached"
    assert any(c[0] == "screenshot" for c in backend.calls)
    httpd.shutdown()
    print("PASS: full agent loop incl. vision screenshot feedback")


def test_helpers_installed_persistent():
    backend = MockBackend()
    ag = agent.BlenderAgent(backend, [], [], log=lambda *a: None)
    ag.install_helpers()
    out = backend.exec_code("print(add_primitive.__name__)")
    assert "add_primitive" in out["stdout"] and not out["error"]
    print("PASS: helper toolkit available in persistent namespace")


def test_helpers_prepended_fresh_namespace():
    backend = MockBackend(fresh_namespace=True)
    ag = agent.BlenderAgent(backend, [], [], log=lambda *a: None)
    ag.install_helpers()
    out = ag._exec("print('step')")
    # each call must carry the helper source (BlenderMCP fresh-namespace mode)
    assert "def add_camera" in backend.calls[-1][1]
    assert "step" in out["stdout"]
    print("PASS: helpers prepended on every call for fresh-namespace backends")


def test_apply_preset_dispatch():
    class Stub:
        def exec_code(self, code):
            return {"stdout": "Preset 'product' applied.", "error": None}
        PERSISTENT_NAMESPACE = True
    ag = agent.BlenderAgent(Stub(), [], [], log=lambda *a: None)
    ag.helpers_installed = True
    text, extra = ag.dispatch("apply_preset", {"name": "product"})
    assert "product" in text and extra == []
    bad, _ = ag.dispatch("apply_preset", {"name": "nope"})
    assert "Unknown preset" in bad
    print("PASS: apply_preset dispatch + validation")


def test_presets_and_helpers_compile():
    from blender_helpers import HELPERS_SOURCE
    compile(HELPERS_SOURCE, "<helpers>", "exec")
    from presets import PRESETS
    for name, meta in PRESETS.items():
        compile(meta["code"], "<preset:%s>" % name, "exec")
    print("PASS: helpers and all %d presets compile" % len(PRESETS))


def test_json_repair():
    assert agent._repair_json('{"code": "x=1"}') == {"code": "x=1"}
    assert agent._repair_json("") == {}
    assert agent._repair_json('blah {"code": "y=2",} trailing').get("code") == "y=2"
    print("PASS: malformed tool-call JSON is repaired")


def test_vision_routing():
    seen = []

    class FakeLLM:
        def __init__(self, tag, fail=False):
            self.tag, self.fail, self.provider, self.model = tag, fail, tag, tag

        def chat(self, messages, tools):
            seen.append(self.tag)
            if self.fail:
                raise RuntimeError("boom")
            return tool_call("t", "task_complete", {"summary": "ok"})

    text = [FakeLLM("text")]
    vision = [FakeLLM("vision-fail", fail=True), FakeLLM("vision-ok")]
    # plain conversation -> text model
    msg = agent.chat_route(text, vision, [{"role": "user", "content": "hi"}],
                           [], vision_enabled=True, log=lambda *a: None)
    assert seen[-1] == "text"
    # conversation containing an image -> vision chain (with fallback)
    image_msg = {"role": "user", "content": [
        {"type": "text", "text": "look"}, {"type": "image_url", "image_url": {"url": "data:..."}}]}
    seen.clear()
    msg = agent.chat_route(text, vision, [image_msg], [], vision_enabled=True,
                           log=lambda *a: None)
    assert seen == ["vision-fail", "vision-ok"]
    print("PASS: image context routes to vision models, with fallback")


def test_save_export_undo_tools():
    backend = MockBackend()
    ag = agent.BlenderAgent(backend, [], [], log=lambda *a: None)
    text, _ = ag.dispatch("save_blend", {})
    assert "Saved" in text and any(c[0] == "save" for c in backend.calls)
    text, _ = ag.dispatch("export_model", {"format": "STL"})
    assert "Exported STL" in text
    ag.dispatch("undo_blender", {})
    assert ("undo", None) in backend.calls
    print("PASS: save / export / undo tools")


def test_watch_mode_stdin():
    tasks = []

    class FakeAgent:
        def run_task(self, task, max_iters=30, reference_image=None):
            tasks.append(task)

    old_stdin = sys.stdin
    sys.stdin = io.StringIO("build a cube\n\n# comment line\nbuild a sphere\n")
    try:
        agent.watch_loop("-", FakeAgent(), 5, log=lambda *a: None)
    finally:
        sys.stdin = old_stdin
    assert tasks == ["build a cube", "build a sphere"], tasks
    print("PASS: watch mode runs queued tasks (blanks/comments skipped)")


def test_provider_chain_skips_missing_keys(monkeypatch_env=None):
    os.environ.pop("GROQ_API_KEY", None)
    os.environ.pop("GEMINI_API_KEY", None)

    class Args:
        provider = "ollama"; model = None; base_url = None; api_key = None
        no_fallback = False
    chain = agent._chain("ollama", Args, vision=False)
    # without keys, only ollama is usable
    assert [c.provider for c in chain] == ["ollama"]
    os.environ["GROQ_API_KEY"] = "fake"
    try:
        chain = agent._chain("ollama", Args, vision=False)
        assert [c.provider for c in chain] == ["ollama", "groq"]
    finally:
        os.environ.pop("GROQ_API_KEY", None)
    print("PASS: provider fallback chain built correctly")


if __name__ == "__main__":
    test_full_loop_with_vision()
    test_helpers_installed_persistent()
    test_helpers_prepended_fresh_namespace()
    test_apply_preset_dispatch()
    test_presets_and_helpers_compile()
    test_json_repair()
    test_vision_routing()
    test_save_export_undo_tools()
    test_watch_mode_stdin()
    test_provider_chain_skips_missing_keys()
    print("\nAll agent tests passed.")
