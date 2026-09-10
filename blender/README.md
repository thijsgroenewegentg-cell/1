# MARK Blender Bridge

`mark_bridge.py` is a small Blender add-on that gives MARK an authenticated local Model Context Protocol connection without exposing Blender's Python console or accepting arbitrary `bpy` code. The add-on exposes a Streamable HTTP-style MCP endpoint at `POST http://127.0.0.1:8765/mcp` and keeps the older MARK newline transport as a temporary compatibility fallback.

## Install

1. In Blender, open **Edit → Preferences → Add-ons → Install**.
2. Select `blender/mark_bridge.py`. If an older MARK Bridge is installed, reinstall this file so the MCP 2.0 endpoint is loaded.
3. Enable **MARK Local Bridge**.
4. Set a long random token in the add-on preferences or the **MARK** sidebar panel.
5. Set the same value as `MARK_BLENDER_TOKEN` in the environment used to launch MARK. The variable must be visible to the MARK process; setting it only inside Blender is not enough.
   - PowerShell: `$env:MARK_BLENDER_TOKEN = "your-long-random-token"; python main.py`
   - Windows cmd: `set MARK_BLENDER_TOKEN=your-long-random-token && python main.py`
   - Linux/macOS: `MARK_BLENDER_TOKEN="your-long-random-token" python main.py`
6. Open the 3D View sidebar with **N**, choose the **MARK** tab, and click **Start MARK Bridge**.

The MCP server listens only on `127.0.0.1` (default port `8765`). MARK's **PLUGIN SETTINGS → BLENDER — LOCAL BRIDGE** panel lets you change the non-secret host and port. MARK now initializes MCP, discovers the `blender_control` tools, and calls Blender through MCP. The same endpoint can be registered in another MCP client with a Bearer token equal to the configured bridge token.

## Available operations

- Inspect scene status and list objects
- Inspect a named object
- Create a cube, sphere, cylinder, camera, or light
- Set a named object's transform
- Assign a material color/metallic/roughness
- Add a bounded modifier such as bevel, subdivision, solidify, array, mirror, or decimate
- Delete a named object
- Render the current scene
- Save a `.blend` file under the user home folder

Mutating operations require confirmation in MARK. The bridge does not expose arbitrary Python, expressions, shell commands, file reads, network access, or Blender operators outside this list. Stop the bridge when it is not needed.
