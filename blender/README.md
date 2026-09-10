# Existing Blender MCP integration

MARK is designed to use the **Blender MCP** add-on already installed in Blender. The add-on shown in the Blender sidebar normally listens on `127.0.0.1:9876`; MARK does not need another Blender add-on or a second socket server.

## Connect the existing add-on

1. In Blender, open a 3D View and press **N**.
2. Open the **Blender MCP** tab.
3. Leave **Port** at `9876` unless you deliberately changed it.
4. Enable only the integrations you want, such as Poly Haven or Sketchfab.
5. Click **Connect to MCP server**.
6. In MARK, open **Plugin Settings → BLENDER — EXISTING MCP SERVER**.
7. Use:
   - Host: `127.0.0.1`
   - Port: `9876`
   - MCP launcher: `uvx`
8. Click **TEST EXISTING BLENDER MCP**.

MARK launches the fixed `uvx blender-mcp` stdio MCP server. That server connects to the Blender add-on on port 9876 and exposes its tools to MARK. `uvx` must be installed and available to the process that launches MARK.

If MARK reports that `uvx` is unavailable, install `uv` and restart MARK. The alternative launcher `python` is supported when the `blender_mcp` package is installed in the same Python environment as MARK.

## Safety boundary

MARK discovers the tools advertised by the existing MCP server, but filters out tools that execute arbitrary Python, shell commands, terminals, or eval expressions. Read-only tools such as scene inspection are immediate. Object changes, asset downloads, renders, saves and other mutations require MARK's normal confirmation card.

The existing MCP server may expose optional integrations such as Poly Haven, Sketchfab, Hyper3D Rodin and Hunyuan3D. Those may use Internet services or credentials managed by the Blender add-on; MARK does not copy those credentials into its own configuration.

## Troubleshooting

- **Connection refused:** click **Connect to MCP server** in Blender first and confirm the port is `9876`.
- **`uvx` not found:** install `uv`, then launch MARK from a process that can see it on `PATH`.
- **No tools discovered:** restart MARK after the add-on is connected and use **TEST EXISTING BLENDER MCP** again.
- **Tool blocked:** MARK intentionally blocks arbitrary-code tools to preserve the no-unrestricted-Python policy. Use the add-on's named scene and asset tools instead.

`mark_bridge.py` in this folder is an older optional MARK-owned bridge. It is not required when using the Blender MCP add-on shown in the user's Blender panel.
