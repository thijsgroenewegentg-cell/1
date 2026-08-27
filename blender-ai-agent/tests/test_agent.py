"""
Tests for the Blender AI agent. No Blender or LLM needed: the Blender socket
server and the LLM HTTP API are both mocked. Run with:  python3 tests/test_agent.py
"""

import contextlib
import io
import json
import os
import socket
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent  # noqa: E402


# --------------------------------------------------------------------------
# Mock of the addon.py Blender bridge server
# --------------------------------------------------------------------------

class MockBlenderServer:
    def __init__(self):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.namespace = {}
        self.commands = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        conn, _ = self.srv.accept()
        buf = b""
        while True:
            try:
                chunk = conn.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                request = json.loads(line.decode("utf-8"))
                reply = self._handle(request)
                conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
        conn.close()

    def _handle(self, request):
        cmd = request.get("cmd")
        args = request.get("args") or {}
        self.commands.append(cmd)
        if cmd == "ping":
            return {"id": request["id"], "ok": True,
                    "result": {"blender": "mock-4.2", "scene": "Scene"}}
        if cmd == "exec":
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    exec(compile(args["code"], "<test>", "exec"), self.namespace)
                return {"id": request["id"], "ok": True,
                        "result": {"stdout": out.getvalue(), "error": None}}
            except Exception:
                return {"id": request["id"], "ok": True,
                        "result": {"stdout": out.getvalue(), "error": traceback.format_exc()}}
        if cmd == "scene_info":
            return {"id": request["id"], "ok": True,
                    "result": {"blender": "mock-4.2", "scene": "Scene", "objects": []}}
        if cmd == "render":
            return {"id": request["id"], "ok": True,
                    "result": {"filepath": "/tmp/mock_render.png"}}
        if cmd == "undo":
            return {"id": request["id"], "ok": True, "result": {"ok": True}}
        return {"id": request["id"], "ok": False, "error": "unknown command: %s" % cmd}


# --------------------------------------------------------------------------
# Mock of the OpenAI-compatible LLM HTTP API (Ollama/Groq/Gemini shape)
# --------------------------------------------------------------------------

SCRIPTED_REPLIES = []


class MockLLMHandler(BaseHTTPRequestHandler):
    request_count = 0
    last_payload = None

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        MockLLMHandler.last_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        MockLLMHandler.request_count += 1
        message = SCRIPTED_REPLIES.pop(0)
        body = json.dumps({"choices": [{"message": message}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def tool_call(call_id, name, arguments):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }],
    }


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def test_bridge_ping_and_exec():
    mock = MockBlenderServer()
    bridge = agent.BlenderBridge("127.0.0.1", mock.port)
    try:
        ping = bridge.call("ping")
        assert ping["ok"] and ping["result"]["blender"] == "mock-4.2"

        reply = bridge.call("exec", code="print(2 + 2)")
        assert reply["ok"], reply
        assert reply["result"]["stdout"].strip() == "4"
        assert reply["result"]["error"] is None

        # namespace persists across calls
        bridge.call("exec", code="x = 41")
        reply = bridge.call("exec", code="print(x + 1)")
        assert reply["result"]["stdout"].strip() == "42"

        # errors come back as tracebacks, not protocol failures
        reply = bridge.call("exec", code="raise RuntimeError('boom')")
        assert reply["ok"] and "RuntimeError: boom" in reply["result"]["error"]

        info = bridge.call("scene_info")
        assert info["result"]["objects"] == []
    finally:
        bridge.close()
    print("PASS: bridge ping/exec/persistent-namespace/error handling")


def test_llm_client_parsing():
    server = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    SCRIPTED_REPLIES.append(tool_call("c1", "get_scene_info", {}))
    try:
        llm = agent.LLMClient(provider="ollama",
                              base_url="http://127.0.0.1:%d/v1" % port,
                              model="mock-model")
        msg = llm.chat([{"role": "user", "content": "hi"}], tools=agent.TOOLS)
        assert msg["tool_calls"][0]["function"]["name"] == "get_scene_info"
        payload = MockLLMHandler.last_payload
        assert payload["model"] == "mock-model"
        assert len(payload["tools"]) == len(agent.TOOLS)
    finally:
        server.shutdown()
    print("PASS: LLM client request/response + tool schema")


def test_full_agent_loop():
    mock_blender = MockBlenderServer()

    httpd = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    # Script the model: look at the scene, build something, then finish.
    SCRIPTED_REPLIES.extend([
        tool_call("c1", "get_scene_info", {}),
        tool_call("c2", "execute_blender_code",
                  {"code": "obj_count = 1\nprint('built a cube:', obj_count)"}),
        tool_call("c3", "task_complete", {"summary": "built a cube"}),
    ])

    bridge = agent.BlenderBridge("127.0.0.1", mock_blender.port)
    llm = agent.LLMClient(provider="ollama",
                          base_url="http://127.0.0.1:%d/v1" % port,
                          model="mock-model")
    logs = []
    try:
        summary = agent.run_task("build a cube", bridge, llm,
                                 max_iters=10, log=lambda *a: logs.append(" ".join(map(str, a))))
    finally:
        bridge.close()
        httpd.shutdown()

    assert "cube" in summary.lower()
    # the LLM's three tool calls reached Blender in order
    assert mock_blender.commands[:3] == ["scene_info", "exec", "task_complete"] or \
           mock_blender.commands[:2] == ["scene_info", "exec"]
    # the exec actually ran server-side with persistent state
    assert mock_blender.namespace.get("obj_count") == 1
    # stdout from Blender was fed back to the model in a tool message
    tool_msgs = [m for m in MockLLMHandler.last_payload["messages"]
                 if m.get("role") == "tool"]
    assert any("built a cube: 1" in m["content"] for m in tool_msgs)
    print("PASS: full agent loop (scene -> exec -> complete, feedback wired up)")


def test_recovery_from_python_error():
    mock_blender = MockBlenderServer()
    httpd = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    SCRIPTED_REPLIES.extend([
        tool_call("c1", "execute_blender_code", {"code": "print(undefined_var)"}),
        tool_call("c2", "execute_blender_code", {"code": "print('recovered')"}),
        tool_call("c3", "task_complete", {"summary": "recovered"}),
    ])

    bridge = agent.BlenderBridge("127.0.0.1", mock_blender.port)
    llm = agent.LLMClient(provider="ollama",
                          base_url="http://127.0.0.1:%d/v1" % port,
                          model="mock-model")
    try:
        summary = agent.run_task("try then fix", bridge, llm,
                                 max_iters=10, log=lambda *a: None)
    finally:
        bridge.close()
        httpd.shutdown()

    assert "recovered" in summary
    tool_msgs = [m for m in MockLLMHandler.last_payload["messages"]
                 if m.get("role") == "tool"]
    assert any("NameError" in m["content"] for m in tool_msgs), \
        "traceback must be returned to the model so it can self-correct"
    print("PASS: Python tracebacks are fed back to the model for self-correction")


def test_provider_presets():
    assert agent.PROVIDERS["ollama"]["base_url"].endswith("/v1")
    assert agent.PROVIDERS["ollama"]["model"]
    # groq/gemini need env keys but must be constructible with explicit key
    llm = agent.LLMClient(provider="groq", api_key="test", model="m")
    assert llm.api_key == "test" and llm.model == "m"
    print("PASS: provider presets")


if __name__ == "__main__":
    test_bridge_ping_and_exec()
    test_llm_client_parsing()
    test_full_agent_loop()
    test_recovery_from_python_error()
    test_provider_presets()
    print("\nAll tests passed.")
