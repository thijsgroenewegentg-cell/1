#!/usr/bin/env python3
"""A tiny fake MCP server over stdio (newline-delimited JSON-RPC 2.0).

Used by tests to exercise MCPStdioTransport without installing anything.
Implements: initialize, notifications/initialized, tools/list, tools/call.
"""
import base64
import json
import sys

# 1x1 transparent PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

TOOLS = [
    {"name": "get_scene_info", "description": "scene info",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "execute_code", "description": "run code",
     "inputSchema": {"type": "object",
                     "properties": {"code": {"type": "string"}},
                     "required": ["code"]}},
    {"name": "get_viewport_screenshot", "description": "screenshot",
     "inputSchema": {"type": "object", "properties": {"max_size": {"type": "integer"}}}},
]


def reply(msg_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            reply(mid, {"protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "fake-blender-mcp", "version": "0"},
                        "capabilities": {"tools": {}}})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            reply(mid, {"tools": TOOLS})
        elif method == "tools/call":
            params = msg.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "get_scene_info":
                content = [{"type": "text",
                            "text": json.dumps({"name": "Scene", "object_count": 0})}]
            elif name == "execute_code":
                content = [{"type": "text",
                            "text": "executed: %s" % args.get("code", "")[:40]}]
            elif name == "get_viewport_screenshot":
                data_url = "data:image/png;base64," + base64.b64encode(PNG).decode()
                content = [{"type": "text", "text": "screenshot taken"},
                           {"type": "image", "data": data_url}]
            else:
                content = [{"type": "text", "text": "unknown tool"}]
            reply(mid, {"content": content, "isError": False})
        elif method == "exit":
            break


if __name__ == "__main__":
    main()
