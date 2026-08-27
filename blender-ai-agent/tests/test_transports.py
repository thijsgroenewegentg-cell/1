"""
Tests for all three transports. No Blender needed:
- BridgeTransport     -> mock of our addon (JSON lines)
- BlenderMCPTransport -> mock of the BlenderMCP addon (raw JSON framing)
- MCPStdioTransport   -> spawns tests/fake_mcp_server.py (JSON-RPC over stdio)
"""
import base64
import json
import os
import socket
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import transports  # noqa: E402


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --- mock: our own bridge addon --------------------------------------------

def serve_bridge(port):
    """Minimal JSON-lines server mimicking addon.py (accepts repeatedly)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(5)
    srv.settimeout(15)
    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                break
            buf = b""
            with conn:
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        req = json.loads(line.decode())
                        cmd, args = req["cmd"], req.get("args") or {}
                        if cmd == "ping":
                            res = {"blender": "4.2-fake", "scene": "Scene"}
                        elif cmd == "exec":
                            res = {"stdout": "ok: " + args["code"][:10], "error": None}
                        elif cmd == "scene_info":
                            res = {"scene": "Scene", "objects": []}
                        else:
                            res = {}
                        conn.sendall((json.dumps({"id": req["id"], "ok": True,
                                                  "result": res}) + "\n").encode())
    finally:
        srv.close()


def test_bridge_transport():
    port = _free_port()
    threading.Thread(target=serve_bridge, args=(port,), daemon=True).start()
    t = transports.BridgeTransport("127.0.0.1", port, timeout=10)
    try:
        assert t.ping()["blender"] == "4.2-fake"
        out = t.exec_code("print(1)")
        assert out["stdout"].startswith("ok:") and not out["error"]
        assert t.scene_info()["scene"] == "Scene"
    finally:
        t.close()
    print("PASS: BridgeTransport (our addon, JSON lines)")


# --- mock: BlenderMCP addon (raw JSON) --------------------------------------

def serve_blendermcp(port, shot_path):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(5)
    srv.settimeout(15)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                break
            conn.settimeout(10)
            buf = b""
            with conn:
                while True:
                    try:
                        chunk = conn.recv(65536)
                    except socket.timeout:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    text = buf.decode("utf-8", "replace").lstrip()
                    try:
                        req, idx = json.JSONDecoder().raw_decode(text)
                        buf = text[idx:].encode()
                    except json.JSONDecodeError:
                        continue
                    ctype = req.get("type")
                    params = req.get("params") or {}
                    if ctype == "ping":
                        resp = {"status": "success", "result": {"pong": True}}
                    elif ctype == "get_scene_info":
                        resp = {"status": "success",
                                "result": {"name": "Scene", "object_count": 1,
                                           "objects": [{"name": "Cube", "type": "MESH",
                                                        "location": [0, 0, 0]}]}}
                    elif ctype == "execute_code":
                        resp = {"status": "success",
                                "result": {"executed": True, "result": "printed output"}}
                    elif ctype == "get_viewport_screenshot":
                        fp = params["filepath"]
                        os.makedirs(os.path.dirname(fp), exist_ok=True)
                        with open(fp, "wb") as fh:
                            fh.write(png)
                        resp = {"status": "success",
                                "result": {"success": True, "filepath": fp}}
                    else:
                        resp = {"status": "error", "message": "Unknown: %s" % ctype}
                    conn.sendall(json.dumps(resp).encode())
    finally:
        srv.close()


def test_blendermcp_transport():
    import tempfile
    port = _free_port()
    shot = os.path.join(tempfile.gettempdir(), "bmcp_shot.png")
    threading.Thread(target=serve_blendermcp, args=(port, shot), daemon=True).start()
    t = transports.BlenderMCPTransport("127.0.0.1", port, timeout=10)
    try:
        assert t.ping()["pong"] is True
        info = t.scene_info()
        assert info["object_count"] == 1 and info["objects"][0]["name"] == "Cube"
        out = t.exec_code("print('x')")
        assert out["stdout"] == "printed output" and not out["error"]
        path = t.viewport_screenshot(shot)
        assert os.path.exists(path) and os.path.getsize(path) > 0
        # error handling path
        bad = t.exec_code("raise RuntimeError('x')")
    finally:
        t.close()
    print("PASS: BlenderMCPTransport (BlenderMCP addon, raw JSON)")


# --- MCP stdio transport ----------------------------------------------------

def test_mcp_stdio_transport():
    server = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "fake_mcp_server.py")
    t = transports.MCPStdioTransport([sys.executable, server], timeout=30)
    try:
        assert "execute_code" in t.tools
        assert "get_scene_info" in t.tools
        info = t.scene_info()
        assert info.get("name") == "Scene"
        text, _structured, err = t.call_tool("execute_code", {"code": "print(1)"})
        assert "executed" in text and not err
        import tempfile
        shot = os.path.join(tempfile.gettempdir(), "mcp_stdio_shot.png")
        path = t.viewport_screenshot(shot)
        assert os.path.exists(path) and os.path.getsize(path) > 0
    finally:
        t.close()
    print("PASS: MCPStdioTransport (generic MCP server over stdio)")


# --- auto detection ---------------------------------------------------------

def test_auto_detect_blendermcp():
    port = _free_port()
    import tempfile
    shot = os.path.join(tempfile.gettempdir(), "auto_shot.png")
    threading.Thread(target=serve_blendermcp, args=(port, shot), daemon=True).start()
    import time
    time.sleep(0.2)
    t = transports.connect("auto", "127.0.0.1", port)
    try:
        assert isinstance(t, transports.BlenderMCPTransport), type(t)
    finally:
        t.close()
    print("PASS: auto-detect finds the BlenderMCP addon")


def test_auto_detect_bridge():
    port = _free_port()
    threading.Thread(target=serve_bridge, args=(port,), daemon=True).start()
    import time
    time.sleep(0.2)
    t = transports.connect("auto", "127.0.0.1", port)
    try:
        assert isinstance(t, transports.BridgeTransport), type(t)
    finally:
        t.close()
    print("PASS: auto-detect finds our bridge addon")


if __name__ == "__main__":
    test_bridge_transport()
    test_blendermcp_transport()
    test_mcp_stdio_transport()
    test_auto_detect_blendermcp()
    test_auto_detect_bridge()
    print("\nAll transport tests passed.")
