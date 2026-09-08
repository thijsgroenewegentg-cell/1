# /modules/blender.py
"""Drive Blender from its command line: render, script, inspect and export.

Blender ships a complete command-line interface and a Python API, which is
everything an assistant needs to be genuinely useful in 3D work::

    blender -b scene.blend -o //frame_ -F PNG -f 1     # render one frame
    blender -b -P build_scene.py                       # run Python headlessly
    blender -b scene.blend --python-expr "..."         # one-liners

This module wraps that. Nothing here needs a display: every call runs
headless (``-b``), so it works over SSH and on a machine with no GPU.

Two runtimes are supported, in this order:

* **The Blender application** — found on ``PATH``, at ``blender.executable``,
  or in the usual per-platform install locations. The full CLI, so rendering,
  the GUI and add-ons all work.
* **The ``bpy`` module** (``pip install bpy``) — Blender's Python API as a
  wheel, with no application and no GUI. Scripting and rendering still work,
  which is enough for most of what gets asked for, and it installs like any
  other dependency.

Scripts are executed, so they go through the same security guard as
``code_assistant``: the source is risk-assessed first, the process is given a
time limit and a memory ceiling, and it runs in a temporary directory.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.helpers import (
    IS_MACOS,
    IS_WINDOWS,
    ensure_dir,
    human_bytes,
    resolve_user_path,
    run_blocking,
    run_command,
    truncate,
)

#: Where Blender is normally installed, per platform. Globs are expanded.
COMMON_LOCATIONS: Dict[str, Tuple[str, ...]] = {
    "windows": (
        r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
        r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
        r"~\AppData\Local\Programs\Blender Foundation\Blender*\blender.exe",
    ),
    "macos": (
        "/Applications/Blender.app/Contents/MacOS/Blender",
        "~/Applications/Blender.app/Contents/MacOS/Blender",
        "/Applications/Blender/Blender.app/Contents/MacOS/Blender",
    ),
    "linux": (
        "/usr/bin/blender",
        "/usr/local/bin/blender",
        "/snap/bin/blender",
        "/var/lib/flatpak/exports/bin/org.blender.Blender",
        "~/.local/share/flatpak/exports/bin/org.blender.Blender",
        "~/blender/blender",
        "/opt/blender/blender",
    ),
}

#: Render engines Blender accepts on the command line, and friendly aliases.
ENGINES: Dict[str, str] = {
    "eevee": "BLENDER_EEVEE_NEXT",
    "eevee_next": "BLENDER_EEVEE_NEXT",
    "blender_eevee": "BLENDER_EEVEE",
    "blender_eevee_next": "BLENDER_EEVEE_NEXT",
    "cycles": "CYCLES",
    "workbench": "BLENDER_WORKBENCH",
}

#: Output formats worth offering by name.
FORMATS: Dict[str, str] = {
    "png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP",
    "exr": "OPEN_EXR", "tiff": "TIFF", "bmp": "BMP",
    "mp4": "FFMPEG", "ffmpeg": "FFMPEG", "avi": "AVI_JPEG",
}

#: Export formats and the ``bpy.ops`` operator that writes each one.
EXPORTERS: Dict[str, str] = {
    ".glb": "bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB')",
    ".gltf": "bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLTF_SEPARATE')",
    ".obj": "bpy.ops.wm.obj_export(filepath=OUT)",
    ".fbx": "bpy.ops.export_scene.fbx(filepath=OUT)",
    ".stl": "bpy.ops.wm.stl_export(filepath=OUT)",
    ".ply": "bpy.ops.wm.ply_export(filepath=OUT)",
    ".usdz": "bpy.ops.wm.usd_export(filepath=OUT)",
    ".usd": "bpy.ops.wm.usd_export(filepath=OUT)",
    ".abc": "bpy.ops.wm.alembic_export(filepath=OUT)",
}

#: Reads a .blend and prints a JSON summary. Kept as a template so the same
#: script works through the executable and through the bpy module.
INSPECT_SCRIPT = '''
import json, sys
import bpy

scene = bpy.context.scene
summary = {
    "file": bpy.data.filepath,
    "blender": bpy.app.version_string,
    "scene": scene.name,
    "engine": scene.render.engine,
    "resolution": [scene.render.resolution_x, scene.render.resolution_y,
                   scene.render.resolution_percentage],
    "frames": [scene.frame_start, scene.frame_end, scene.frame_current],
    "fps": scene.render.fps,
    "objects": [
        {"name": obj.name, "type": obj.type,
         "location": [round(value, 4) for value in obj.location],
         "visible": not obj.hide_render}
        for obj in bpy.data.objects
    ],
    "cameras": [obj.name for obj in bpy.data.objects if obj.type == "CAMERA"],
    "lights": [obj.name for obj in bpy.data.objects if obj.type == "LIGHT"],
    "materials": [material.name for material in bpy.data.materials],
    "collections": [collection.name for collection in bpy.data.collections],
    "counts": {
        "objects": len(bpy.data.objects),
        "meshes": len(bpy.data.meshes),
        "materials": len(bpy.data.materials),
        "images": len(bpy.data.images),
    },
}
print("JARVIS_JSON_START")
print(json.dumps(summary))
print("JARVIS_JSON_END")
'''




#: Finished-scene looks applied after the model's script builds the geometry.
#: Each is a small bpy snippet that sets world shading and light mood, so the
#: scene gets a coherent presentational look without knowing the object names.
LOOK_PRESETS: Dict[str, str] = {
    "studio": (
        "import bpy\n"
        "# studio: neutral backdrop, punchier lights\n"
        'world = bpy.data.worlds.get("World")\n'
        "if world is None:\n"
        '    world = bpy.data.worlds.new("World")\n'
        "    bpy.context.scene.world = world\n"
        "world.use_nodes = True\n"
        'bg = world.node_tree.nodes.get("Background")\n'
        "if bg is not None:\n"
        "    bg.inputs[0].default_value = (0.045, 0.045, 0.05, 1.0)\n"
        "    bg.inputs[1].default_value = 0.9\n"
        "for obj in bpy.data.objects:\n"
        '    if obj.type == "LIGHT":\n'
        "        obj.data.energy *= 1.5\n"
    ),
    "soft": (
        "import bpy\n"
        "# soft: warm, low-contrast morning light\n"
        'world = bpy.data.worlds.get("World")\n'
        "if world is None:\n"
        '    world = bpy.data.worlds.new("World")\n'
        "    bpy.context.scene.world = world\n"
        "world.use_nodes = True\n"
        'bg = world.node_tree.nodes.get("Background")\n'
        "if bg is not None:\n"
        "    bg.inputs[0].default_value = (0.06, 0.05, 0.045, 1.0)\n"
        "    bg.inputs[1].default_value = 0.7\n"
        "for obj in bpy.data.objects:\n"
        '    if obj.type == "LIGHT":\n'
        "        obj.data.energy *= 0.85\n"
    ),
    "sunset": (
        "import bpy\n"
        "# sunset: warm rim light against a cool dusk\n"
        'world = bpy.data.worlds.get("World")\n'
        "if world is None:\n"
        '    world = bpy.data.worlds.new("World")\n'
        "    bpy.context.scene.world = world\n"
        "world.use_nodes = True\n"
        'bg = world.node_tree.nodes.get("Background")\n'
        "if bg is not None:\n"
        "    bg.inputs[0].default_value = (0.02, 0.015, 0.045, 1.0)\n"
        "    bg.inputs[1].default_value = 0.6\n"
        "for obj in bpy.data.objects:\n"
        '    if obj.type == "LIGHT":\n'
        "        obj.data.energy *= 0.7\n"
    ),
    "minimal": (
        "import bpy\n"
        "# minimal: near-black backdrop, crisp single light\n"
        'world = bpy.data.worlds.get("World")\n'
        "if world is None:\n"
        '    world = bpy.data.worlds.new("World")\n'
        "    bpy.context.scene.world = world\n"
        "world.use_nodes = True\n"
        'bg = world.node_tree.nodes.get("Background")\n'
        "if bg is not None:\n"
        "    bg.inputs[0].default_value = (0.01, 0.01, 0.012, 1.0)\n"
        "    bg.inputs[1].default_value = 1.0\n"
        "for obj in bpy.data.objects:\n"
        '    if obj.type == "LIGHT":\n'
        "        obj.data.energy *= 1.2\n"
    ),
}


class Blender(BaseModule):
    """3D work: render scenes, run Blender Python, inspect and export models."""

    name = "blender"
    description = (
        "Blender: render .blend files and animations, run Blender Python (bpy) "
        "scripts headlessly, build scenes from a description, inspect what is "
        "inside a .blend, and export models to glTF/OBJ/FBX/STL."
    )
    intent_examples: ClassVar[List[str]] = [
        "render frame 1 of ~/scenes/city.blend",
        "what's inside product.blend",
        "make a 3d scene with a red cube on a plane",
        "export chair.blend to glb",
        "is blender installed",
    ]

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Read the Blender settings and prepare the output directory.

        Args:
            config: The global configuration object.
            llm: Optional LLM client, used to write bpy scripts.
            security: Optional security guard.
        """
        super().__init__(config, llm=llm, security=security)
        section = config.section("blender")
        self.configured_path: str = str(section.get("executable", "") or "")
        self.timeout: float = float(section.get("timeout", 300))
        self.render_timeout: float = float(section.get("render_timeout", 1800))
        self.memory_mb: int = int(section.get("memory_mb", 0) or 0)
        self.engine: str = str(section.get("engine", "") or "")
        self.samples: int = int(section.get("samples", 0) or 0)
        self.show_after_render: bool = bool(section.get("show_after_render", False))
        self.allow_scripts: bool = bool(section.get("allow_scripts", True))
        self.allow_bpy_module: bool = bool(section.get("allow_bpy_module", True))
        self.output_dir: Path = config.resolve(
            section.get("output_dir", "data/renders")
        )
        self.state_file: Path = config.resolve(
            section.get("state_file", "data/blender_state.json")
        )
        self._state: Dict[str, Any] = self._load_state()
        self.last_blend: str = str(self._state.get("last", "") or "")
        self._runtime: Optional[Tuple[str, str]] = None  # (kind, path)
        self._searched: bool = False
        self._bpy_state: Optional[bool] = None  # remembered by the last discovery
        ensure_dir(self.output_dir)

    # ------------------------------------------------------- scene memory
    def _load_state(self) -> Dict[str, Any]:
        """Read the remembered scenes and settings, tolerating a corrupt file."""
        try:
            if self.state_file.exists():
                data = json.loads(self.state_file.read_text("utf-8", errors="replace"))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {"last": "", "by_name": {}, "settings": {}}

    def _save_state(self) -> None:
        """Persist the scene memory so it survives a restart."""
        try:
            ensure_dir(self.state_file.parent)
            self.state_file.write_text(
                json.dumps(self._state, indent=2, default=str), "utf-8"
            )
        except Exception:
            pass

    def _remember(self, path: Path) -> None:
        """Remember this .blend as the most recent, keyed several ways."""
        try:
            resolved = path.resolve()
            self._state["last"] = str(resolved)
            by_name = self._state.setdefault("by_name", {})
            names = {
                str(resolved).lower(): str(resolved),
                resolved.name.lower(): str(resolved),
                resolved.stem.lower(): str(resolved),
            }
            by_name.update(names)
            self._save_state()
        except Exception:
            pass

    def _remembered_settings(self) -> Dict[str, Any]:
        """Render settings the user last chose, for use as defaults."""
        return dict(self._state.get("settings", {}) or {})

    def _record_settings(self, **settings: Any) -> None:
        """Store the settings actually used, dropping empty values."""
        current = self._remembered_settings()
        changed = False
        for key, value in settings.items():
            if value not in (None, "", 0, False):
                current[key] = value
                changed = True
        if changed:
            self._state["settings"] = current
            self._save_state()

    def _find_blend(self, given: str, use_last: bool = True) -> Optional[Path]:
        """Resolve a .blend the user may have named loosely.

        Tries, in order: the path as written, a remembered scene whose name
        matches, and the most recent scene. This is what lets "render the
        donut" find ``donut.blend`` from a previous session.

        Args:
            given: The file the user (or model) named; may be empty.
            use_last: Fall back to the most recent scene.

        Returns:
            An existing .blend path, or ``None``.
        """
        if (given or "").strip():
            direct = resolve_user_path(given)
            if direct.is_file():
                return direct
            stem = Path(given).stem.lower().strip()
            by_name = self._state.get("by_name", {}) or {}
            if stem in by_name:
                candidate = Path(by_name[stem])
                if candidate.is_file():
                    return candidate
            if (self.output_dir / f"{Path(given).stem}.blend").is_file():
                return self.output_dir / f"{Path(given).stem}.blend"
            return None
        if use_last and self.last_blend and Path(self.last_blend).is_file():
            return Path(self.last_blend)
        return None

    def _open_for_user(self, path: Path) -> str:
        """Show a finished render in the OS image viewer.

        Best effort by design: a headless box has no viewer, and that must
        never turn a good render into an error.

        Args:
            path: The file to open.

        Returns:
            Empty string on success, else a short reason the open failed.
        """
        import subprocess

        try:
            if IS_WINDOWS:
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif IS_MACOS:
                subprocess.Popen(
                    ["open", str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    ["xdg-open", str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            return ""
        except Exception as exc:
            return truncate(str(exc) or type(exc).__name__, 160)

    # ------------------------------------------------------------ discovery
    def find_runtime(self, refresh: bool = False) -> Optional[Tuple[str, str]]:
        """Locate Blender, preferring the application over the Python module.

        Discovery is cached — including a *miss*. A failed search used to be
        retried on every Blender request, and each retry could spend a minute
        probing whether the ``bpy`` module imports, which made "can't find
        Blender" feel like a hang. ``blender_status`` refreshes explicitly.

        Args:
            refresh: Ignore the cached answer and look again.

        Returns:
            ``("executable", path)`` or ``("bpy", interpreter)``, or ``None``
            when Blender is not installed at all.
        """
        if self._searched and not refresh:
            return self._runtime
        self._runtime = self._locate()
        self._searched = True
        return self._runtime

    def _locate(self) -> Optional[Tuple[str, str]]:
        """Walk every place Blender might be and return the first hit."""
        candidates: List[str] = []
        if self.configured_path:
            configured = Path(self.configured_path).expanduser()
            # Tolerate a folder in blender.executable ("C:\\...\\Blender"): it
            # is the obvious thing to paste from the file browser.
            if configured.is_dir():
                configured = configured / ("blender.exe" if IS_WINDOWS else "blender")
            candidates.append(str(configured))
        found = shutil.which("blender")
        if found:
            candidates.append(found)
        platform_key = "windows" if IS_WINDOWS else "macos" if IS_MACOS else "linux"
        for pattern in COMMON_LOCATIONS[platform_key]:
            expanded = Path(pattern).expanduser()
            if any(character in pattern for character in "*?"):
                candidates.extend(
                    str(match) for match in sorted(expanded.parent.glob(expanded.name))
                )
            else:
                candidates.append(str(expanded))
        # Steam installs Blender wherever a library lives — the common-locations
        # path above only covers the C: install Steam itself chose, and a
        # config path typed for another machine helps nobody. Ask Steam where
        # its libraries actually are.
        candidates.extend(self._steam_blender_candidates())

        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if not path.is_file():
                continue
            # Windows has no exec bit; os.access(…, X_OK) is unreliable there,
            # so an existing .exe counts as executable.
            executable = os.access(path, os.X_OK) or (
                IS_WINDOWS and path.suffix.lower() == ".exe"
            )
            if executable:
                return ("executable", str(path))

        if self.allow_bpy_module:
            self._bpy_state = self._bpy_importable()
            if self._bpy_state:
                return ("bpy", sys.executable)
        else:
            self._bpy_state = False
        return None

    # --------------------------------------------------------- Steam library
    def _steam_blender_candidates(self) -> List[str]:
        """Find ``steamapps/common/Blender`` in every Steam library on disk.

        Steam can keep games on any number of libraries (one per drive).
        ``libraryfolders.vdf`` inside the Steam install lists them all, so
        instead of guessing we read it and look for Blender in each library.

        Returns:
            Candidate paths to a Blender executable, existing or not (the
            caller checks existence); de-duplicated.
        """
        executable = "blender.exe" if IS_WINDOWS else "blender"
        output: List[str] = []
        seen = set()
        for root in self._steam_roots():
            for library in [root, *self._steam_library_folders(root)]:
                candidate = library / "steamapps" / "common" / "Blender" / executable
                key = str(candidate).lower()
                if key not in seen:
                    seen.add(key)
                    output.append(str(candidate))
        return output

    @staticmethod
    def _steam_roots() -> List[Path]:
        """Where Steam itself installs, per platform.

        Returns:
            Steam installation directories that actually exist (they contain a
            ``steamapps`` folder).
        """
        roots: List[Path] = []
        if IS_WINDOWS:
            program_files_x86 = os.environ.get(
                "PROGRAMFILES(X86)", r"C:\Program Files (x86)"
            )
            program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
            roots.extend([Path(program_files_x86) / "Steam", Path(program_files) / "Steam"])
        elif IS_MACOS:
            roots.append(Path.home() / "Library" / "Application Support" / "Steam")
        else:
            roots.extend([
                Path.home() / ".local" / "share" / "Steam",
                Path.home() / ".steam" / "steam",
                Path("/usr/share/steam"),
            ])
        return [root for root in roots if (root / "steamapps").is_dir()]

    @staticmethod
    def _steam_library_folders(steam_root: Path) -> List[Path]:
        """Read the extra libraries from ``steamapps/libraryfolders.vdf``.

        Args:
            steam_root: A Steam installation directory.

        Returns:
            The library folders Steam manages, excluding the install's own
            ``steamapps`` (that one is always searched first).
        """
        vdf = steam_root / "steamapps" / "libraryfolders.vdf"
        try:
            text = vdf.read_text("utf-8", errors="replace")
        except Exception:
            return []
        folders: List[Path] = []
        # Entries look like:  "path"  "D:\\SteamLibrary"   (the file escapes
        # backslashes, and single-slash variants are seen in the wild too).
        for match in re.finditer(r'^\s*"path"\s+"(.*?)"\s*$', text, re.MULTILINE):
            raw = match.group(1).replace("\\\\", "\\")
            if raw.strip():
                folders.append(Path(raw.strip()))
        return folders

    @staticmethod
    def _bpy_importable() -> bool:
        """Check whether ``import bpy`` works in this interpreter.

        Returns:
            True when the pip-installed Blender module is usable. The import
            is attempted in a subprocess: a broken wheel (missing system
            libraries, most often) must not take the assistant down with it.
            Twenty-five seconds is generous for a first import without making
            a missing Blender feel like a hang on every request.
        """
        import subprocess

        try:
            probe = subprocess.run(
                [sys.executable, "-c", "import bpy; print(bpy.app.version_string)"],
                capture_output=True, timeout=25, text=True,
            )
        except Exception:
            return False
        return probe.returncode == 0

    def _diagnose(self) -> str:
        """Explain exactly what was searched, so a miss is fixable.

        Uses the ``bpy`` probe result remembered by the last discovery run so
        the diagnosis never spawns its own slow import check.
        """
        configured = Path(self.configured_path).expanduser() if self.configured_path else None
        exists = bool(configured and (configured.is_file() or configured.is_dir()))
        steam_candidates = self._steam_blender_candidates()
        steam_notes = (
            "\n".join(f"      {candidate}" for candidate in steam_candidates[:4])
            if steam_candidates else "(no Steam install found)"
        )
        if len(steam_candidates) > 4:
            steam_notes += f"\n      …and {len(steam_candidates) - 4} more libraries"
        lines = [
            "I can't find Blender, sir. Here is what I checked:",
            "",
            f"  configured in config.yaml : {configured or '(none set)'}",
            f"      exists on disk        : {'yes' if exists else 'no'}",
            f"  Steam Blender candidates  : {steam_notes}",
            f"  on PATH as 'blender'      : "
            f"{'yes' if shutil.which('blender') else 'no'}",
            f"  pip 'bpy' module          : "
            f"{'imports fine' if self._bpy_state else 'not installed or broken'}",
            "",
            "Fix it by installing the application from blender.org (or Steam) and setting "
            "blender.executable in config.yaml to its blender.exe — a folder path is fine, "
            "I look for the executable inside it. For scripting only, run 'pip install bpy'.",
        ]
        return "\n".join(lines)

    def _missing(self) -> ModuleResult:
        """The standard "Blender isn't here" answer, with how to fix it."""
        return ModuleResult.fail(self._diagnose())

    # ---------------------------------------------------------- offline route
    def offline_router(self, command: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """Rule-based routing with parameter extraction (used without an LLM).

        Args:
            command: The user's utterance.

        Returns:
            ``(tool name, parameters)``, or ``None`` to let the LLM decide.
        """
        text = strip_command_prefix(command)
        lowered = text.lower()
        blend = self._first_path(text, (".blend",))

        if any(phrase in lowered for phrase in
               ("is blender installed", "blender version", "blender status",
                "which blender", "do you have blender", "connect to blender",
                "use blender", "can you use blender", "blender available",
                "is blender working", "find blender")):
            return "blender_status", {}

        # Launching the application itself ("open Blender") must not fall
        # through to make_scene or the generic keyword picker.
        if any(phrase in lowered for phrase in
               ("open blender", "launch blender", "start blender",
                "open up blender", "fire up blender")) and ".blend" not in lowered:
            return "open_blender", {"blend_file": ""}

        if any(phrase in lowered for phrase in
               ("what's in", "whats in", "what is in", "inspect", "contents of",
                "how many objects", "tell me about")) and blend:
            return "scene_info", {"blend_file": blend}

        if "export" in lowered or "convert" in lowered:
            target = ""
            for suffix in EXPORTERS:
                if suffix.lstrip(".") in lowered.split():
                    target = suffix
                    break
            if blend or target:
                return "export_model", {"blend_file": blend, "format": target or ".glb"}

        # Asking *about* renders must be checked before asking *for* one:
        # "what have you rendered" contains the word "render".
        if any(phrase in lowered for phrase in
               ("what have you rendered", "recent renders", "list the renders",
                "list renders", "renders so far", "render folder",
                "what did you render")):
            return "list_renders", {}

        if "render" in lowered:
            animation = any(word in lowered for word in
                            ("animation", "all frames", "every frame", "the sequence"))
            frame = re.search(r"frame\s+(\d+)", lowered)
            return "render", {
                "blend_file": blend,
                "frame": int(frame.group(1)) if frame else 0,
                "animation": animation,
            }

        if any(phrase in lowered for phrase in
               ("run this in blender", "blender script", "run the bpy",
                "execute in blender")):
            return "run_script", {"script": text}

        if any(phrase in lowered for phrase in
               ("3d scene", "3d model", "make a scene", "build a scene",
                "model of a", "in blender")):
            return "make_scene", {"description": text}

        return None

    @staticmethod
    def _first_path(text: str, suffixes: Tuple[str, ...]) -> str:
        """Pull the first path with one of ``suffixes`` out of a sentence.

        Args:
            text: The sentence.
            suffixes: Extensions to look for, e.g. ``(".blend",)``.

        Returns:
            The path as written, or an empty string.
        """
        pattern = "|".join(re.escape(suffix) for suffix in suffixes)
        match = re.search(rf"(\S+(?:{pattern}))", text, re.IGNORECASE)
        return match.group(1).strip("'\"" ) if match else ""

    # ------------------------------------------------------------- execution
    async def _run(self, args: List[str], timeout: float,
                   script: str = "") -> Tuple[int, str, str]:
        """Run Blender with ``args``, or the equivalent through ``bpy``.

        Args:
            args: Arguments *after* the executable, in Blender's own order.
            timeout: Seconds before the process is killed.
            script: The Python source, when one is being run. With the bpy
                module there is no application to pass ``-b -P`` to, so the
                script is handed to the interpreter directly.

        Returns:
            ``(exit code, stdout, stderr)``.
        """
        runtime = self.find_runtime()
        if runtime is None:
            return 127, "", "Blender is not installed"
        kind, path = runtime

        if kind == "executable":
            command = [path, *args]
        else:
            if not script:
                return 2, "", (
                    "The bpy module can only run scripts — it has no command line. "
                    "Install the Blender application for this."
                )
            command = [path, "-c", script]

        return await run_command(
            command, timeout=timeout, memory_mb=self.memory_mb,
            env={"BLENDER_USER_SCRIPTS": "", "PYTHONDONTWRITEBYTECODE": "1"},
        )

    async def _run_script(self, source: str, blend_file: str = "",
                          timeout: float = 0.0) -> Tuple[int, str, str]:
        """Execute Blender Python, optionally against an existing .blend.

        Args:
            source: The Python source to run.
            blend_file: A .blend to open first.
            timeout: Override for the configured script timeout.

        Returns:
            ``(exit code, stdout, stderr)``.
        """
        with tempfile.TemporaryDirectory(prefix="jarvis-blender-") as workdir:
            script_path = Path(workdir) / "jarvis_script.py"
            await run_blocking(script_path.write_text, source, "utf-8")
            args: List[str] = ["-b"]
            if blend_file:
                args.append(blend_file)
            args += ["--factory-startup", "-noaudio", "-P", str(script_path)]
            prelude = ""
            if blend_file:
                # The bpy module has no "-b file.blend", so open it in Python.
                prelude = (
                    "import bpy\n"
                    f"bpy.ops.wm.open_mainfile(filepath={blend_file!r})\n"
                )
            return await self._run(
                args, timeout or self.timeout, script=prelude + source
            )

    @staticmethod
    def _extract_json(output: str) -> Optional[Dict[str, Any]]:
        """Pull the JSON block our scripts print out of Blender's chatter.

        Args:
            output: Everything the process wrote to stdout.

        Returns:
            The parsed object, or ``None`` when the markers are absent.
        """
        match = re.search(
            r"JARVIS_JSON_START\s*(.+?)\s*JARVIS_JSON_END", output, re.DOTALL
        )
        if not match:
            return None
        try:
            parsed = json.loads(match.group(1))
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _blender_error(stdout: str, stderr: str) -> str:
        """Summarise why Blender failed, in one line where possible.

        Args:
            stdout: The process's standard output.
            stderr: The process's standard error.

        Returns:
            The most informative line available.
        """
        blob = f"{stderr}\n{stdout}".strip()
        for marker in ("Error:", "Traceback (most recent call last)", "error:"):
            index = blob.find(marker)
            if index >= 0:
                return truncate(blob[index:].strip().splitlines()[0], 300)
        return truncate(blob.splitlines()[-1] if blob.splitlines() else "no output", 300)

    # ----------------------------------------------------------------- status
    @tool(
        description="Report whether Blender is available, which runtime and version.",
        params={},
        keywords=["is blender installed", "blender version", "blender status",
                  "do you have blender"],
    )
    async def blender_status(self) -> ModuleResult:
        """Check for Blender and report what was found.

        Returns:
            A :class:`ModuleResult` naming the runtime, version and defaults.
        """
        runtime = self.find_runtime(refresh=True)
        if runtime is None:
            return self._missing()
        kind, path = runtime

        if kind == "executable":
            code, out, err = await run_command([path, "--version"], timeout=60)
            version = (out or err).strip().splitlines()[0] if (out or err) else "unknown"
        else:
            code, out, err = await run_command(
                [path, "-c", "import bpy; print('Blender', bpy.app.version_string)"],
                timeout=90,
            )
            version = (out or "").strip() or "unknown"
        if code != 0:
            return ModuleResult.fail(
                f"Blender is at {path} but would not start: {self._blender_error(out, err)}"
            )

        label = "the application" if kind == "executable" else "the bpy Python module"
        lines = [
            f"{version}",
            f"  runtime     {label}",
            f"  path        {path}",
            f"  renders to  {self.output_dir}",
            f"  engine      {self.engine or 'whatever the file specifies'}",
            f"  scripting   {'enabled' if self.allow_scripts else 'disabled in config'}",
        ]
        return ModuleResult(
            success=True,
            output="\n".join(lines),
            speak=f"{version}, ready.",
            data={"runtime": kind, "path": path, "version": version},
        )

    # ----------------------------------------------------------------- render
    @tool(
        description=(
            "Render a .blend file: a single frame, a specific frame, or the whole "
            "animation. Returns the paths written."
        ),
        params={
            "blend_file": {"type": "string", "description": "Path to the .blend",
                           "default": ""},
            "frame": {"type": "integer", "description": "Frame number (0 = the current one)",
                      "default": 0},
            "animation": {"type": "boolean", "description": "Render the whole frame range",
                          "default": False},
            "output": {"type": "string", "description": "Output file or directory",
                       "default": ""},
            "engine": {"type": "string", "description": "cycles, eevee or workbench",
                       "default": ""},
            "format": {"type": "string", "description": "png, jpg, webp, exr, mp4…",
                       "default": "png"},
            "resolution_percent": {"type": "integer",
                                   "description": "Scale, e.g. 50 for a fast preview",
                                   "default": 0},
            "samples": {"type": "integer", "description": "Cycles/EEVEE samples",
                        "default": 0},
            "show": {"type": "boolean",
                     "description": "Open the first frame in the OS image viewer "
                                    "afterwards ('render and show me')",
                     "default": False},
        },
        keywords=["render", "render the scene", "render frame", "render the animation",
                  "render and show", "show me the render"],
        examples=["render frame 12 of ~/scenes/city.blend at 50%",
                  "render the donut and show me"],
    )
    async def render(
        self,
        blend_file: str = "",
        frame: int = 0,
        animation: bool = False,
        output: str = "",
        engine: str = "",
        format: str = "png",
        resolution_percent: int = 0,
        samples: int = 0,
        show: bool = False,
    ) -> ModuleResult:
        """Render stills or an animation from a .blend file.

        Args:
            blend_file: The scene to render; defaults to the last one used.
            frame: A single frame number; 0 means the scene's current frame.
            animation: Render the whole frame range instead of one frame.
            output: Where to write; defaults to ``blender.output_dir``.
            engine: ``cycles``, ``eevee`` or ``workbench``.
            format: Image or video format.
            resolution_percent: Render scale — 50 halves it, which is the
                quickest way to preview a heavy scene.
            samples: Sample count, when the engine uses one.
            show: Open the first frame in the OS image viewer afterwards.

        Returns:
            A :class:`ModuleResult` listing the files written.
        """
        if self.find_runtime() is None:
            return self._missing()

        target = self._find_blend(blend_file)
        if target is None:
            if blend_file:
                return ModuleResult.fail(
                    f"No .blend matching '{blend_file}', sir. Name the file, "
                    "or tell me which scene to use and I'll remember it."
                )
            return ModuleResult.fail(
                "Which .blend should I render, sir? Name one, or say 'render "
                "the donut' if we made it before."
            )
        if not self._is_blend(target):
            return ModuleResult.fail(
                f"{target.name} isn't a Blender file, sir — I need a .blend."
            )
        self.last_blend = str(target)
        self._remember(target)

        kind, _ = self.find_runtime() or ("", "")
        if kind != "executable":
            return await self._render_via_bpy(
                target, frame, animation, output, engine, format,
                resolution_percent, samples, show,
            )

        stem = target.stem
        destination = Path(output).expanduser() if output else (self.output_dir / stem)
        prefix = destination if destination.suffix else destination / f"{stem}_"
        ensure_dir(prefix.parent)

        args: List[str] = ["-b", str(target)]
        # The engine and samples you chose last time are the defaults for the
        # next render — that is the "he learns how I work" part.
        remembered = self._remembered_settings()
        engine_choice = str(
            engine or self.engine or remembered.get("engine", "") or ""
        ).strip()
        resolved_engine = ENGINES.get(engine_choice.lower(), "")
        if resolved_engine:
            args += ["-E", resolved_engine]
        args += ["-o", str(prefix), "-F", FORMATS.get(format.strip().lower(), "PNG")]

        tweaks: List[str] = []
        if resolution_percent:
            tweaks.append(
                "bpy.context.scene.render.resolution_percentage = "
                f"{max(1, min(400, int(resolution_percent)))}"
            )
        sample_count = int(
            samples or self.samples or remembered.get("samples", 0) or 0
        )
        if sample_count:
            tweaks.append(
                "scene = bpy.context.scene\n"
                "if hasattr(scene, 'cycles'):\n"
                f"    scene.cycles.samples = {sample_count}\n"
                "if hasattr(scene, 'eevee'):\n"
                f"    scene.eevee.taa_render_samples = {sample_count}"
            )
        if tweaks:
            args += ["--python-expr", "import bpy\n" + "\n".join(tweaks)]

        # A second of slack: some filesystems keep whole-second mtimes, so a
        # render finishing within the same second would look untouched.
        started = time.time() - 1.0
        if animation:
            args.append("-a")
        else:
            args += ["-f", str(int(frame))] if frame else ["-f", "1"]

        code, out, err = await self._run(args, self.render_timeout)
        written = self._outputs_since(prefix, started)
        if code == -9:
            return ModuleResult.fail(
                f"The render was still going after {self.render_timeout:.0f}s, so I "
                "stopped it. Raise blender.render_timeout, drop the samples, or "
                "render at a lower resolution_percent."
            )
        if code != 0 and not written:
            return ModuleResult.fail(f"Blender failed: {self._blender_error(out, err)}")
        if not written:
            return ModuleResult.fail(
                "Blender finished without writing anything. Check the scene has a "
                "camera, and that the output path is writable."
            )

        total = sum(path.stat().st_size for path in written)
        self._record_settings(engine=engine_choice, samples=sample_count)
        listing = "\n".join(f"  {path} ({human_bytes(path.stat().st_size)})\n"
                            for path in written[:12])
        more = f"\n  …and {len(written) - 12} more" if len(written) > 12 else ""
        opened = ""
        if show or self.show_after_render:
            reason = self._open_for_user(written[0])
            if reason:
                opened = f"\n(I couldn't open {written[0].name}: {reason})"
            else:
                opened = f"\nOpened {written[0].name} for you."
        return ModuleResult(
            success=True,
            output=(f"Rendered {len(written)} frame(s), {human_bytes(total)}:\n"
                    f"{listing}{more}{opened}"),
            speak=f"Rendered {len(written)} frame{'s' if len(written) != 1 else ''}, sir.",
            data={"files": [str(path) for path in written], "bytes": total},
        )
    @staticmethod
    def _outputs_since(prefix: Path, since: float) -> List[Path]:
        """Find the frames a render just wrote.

        Comparing against a "files that existed before" snapshot looked
        obvious and was wrong: re-rendering a frame overwrites it, so a second
        run reported fewer frames than it produced — and re-rendering a single
        frame reported that nothing had been written at all. Modification time
        catches overwrites as well as new files.

        Args:
            prefix: The output prefix Blender was given.
            since: Unix timestamp taken just before the render started.

        Returns:
            Matching files touched at or after ``since``, in name order.
        """
        folder, stem = prefix.parent, prefix.name
        if not folder.is_dir():
            return []
        # Blender names frames "<prefix><4-digit frame><ext>". Matching the
        # prefix alone swept up anything that happened to sit there with a
        # recent timestamp, and reported it as freshly rendered.
        pattern = re.compile(rf"^{re.escape(stem)}\d{{3,}}\.[A-Za-z0-9]+$")
        return sorted(
            (path for path in folder.iterdir()
             if path.is_file() and pattern.match(path.name)
             and path.stat().st_mtime >= since),
            key=lambda path: path.name,
        )

    async def _render_via_bpy(
        self, target: Path, frame: int, animation: bool, output: str,
        engine: str, image_format: str, resolution_percent: int, samples: int,
        show: bool = False,
    ) -> ModuleResult:
        """Render through the bpy module, which has no command line.

        Args:
            target: The .blend file.
            frame: Frame number, 0 for the scene's current frame.
            animation: Render the whole range.
            output: Output path, blank for the configured directory.
            engine: Engine alias.
            image_format: Output format name.
            resolution_percent: Render scale.
            samples: Sample count.
            show: Open the first frame in the OS image viewer afterwards.

        Returns:
            A :class:`ModuleResult` listing what was written.
        """
        destination = Path(output).expanduser() if output else (
            self.output_dir / target.stem
        )
        ensure_dir(destination if not destination.suffix else destination.parent)
        prefix = destination if destination.suffix else destination / f"{target.stem}_"
        remembered = self._remembered_settings()
        engine_choice = str(
            engine or self.engine or remembered.get("engine", "") or ""
        ).strip()
        resolved_engine = ENGINES.get(engine_choice.lower(), "")
        sample_count = int(
            samples or self.samples or remembered.get("samples", 0) or 0
        )
        started = time.time() - 1.0

        script = f'''
import bpy
bpy.ops.wm.open_mainfile(filepath={str(target)!r})
scene = bpy.context.scene
scene.render.filepath = {str(prefix)!r}
scene.render.image_settings.file_format = {FORMATS.get(image_format.lower(), "PNG")!r}
'''
        if resolved_engine:
            script += f"scene.render.engine = {resolved_engine!r}\n"
        if resolution_percent:
            script += ("scene.render.resolution_percentage = "
                       f"{max(1, min(400, int(resolution_percent)))}\n")
        if sample_count:
            script += (
                "if hasattr(scene, 'cycles'):\n"
                f"    scene.cycles.samples = {sample_count}\n"
                "if hasattr(scene, 'eevee'):\n"
                f"    scene.eevee.taa_render_samples = {sample_count}\n"
            )
        if frame:
            script += f"scene.frame_set({int(frame)})\n"
        script += f"bpy.ops.render.render(animation={bool(animation)!r}, write_still=True)\n"

        code, out, err = await self._run([], self.render_timeout, script=script)
        written = self._outputs_since(prefix, started)
        if code != 0 and not written:
            return ModuleResult.fail(f"Blender failed: {self._blender_error(out, err)}")
        if not written:
            return ModuleResult.fail("Blender wrote no frames — is there a camera?")
        total = sum(path.stat().st_size for path in written)
        self._record_settings(engine=engine_choice, samples=sample_count)
        opened = ""
        if show or self.show_after_render:
            reason = self._open_for_user(written[0])
            if reason:
                opened = f"\n(I couldn't open {written[0].name}: {reason})"
            else:
                opened = f"\nOpened {written[0].name} for you."
        return ModuleResult(
            success=True,
            output=(f"Rendered {len(written)} frame(s), {human_bytes(total)}:\n"
                    + "\n".join(f"  {path}" for path in written[:12])
                    + opened),
            speak=f"Rendered {len(written)} frame(s), sir.",
            data={"files": [str(path) for path in written], "bytes": total},
        )
    # ------------------------------------------------------------- inspection
    @staticmethod
    def _is_blend(path: Path) -> bool:
        """Whether a path is plausibly a Blender file.

        Args:
            path: The file in question.

        Returns:
            True for ``.blend`` and its numbered backups (``.blend1``).
        """
        return path.suffix.lower().startswith(".blend")

    @tool(
        description="Report what is inside a .blend: objects, cameras, materials, frames.",
        params={
            "blend_file": {"type": "string", "description": "Path to the .blend",
                           "required": True},
        },
        untrusted=True,
        keywords=["what's in the blend", "inspect the blend", "scene info",
                  "how many objects", "contents of the blend"],
    )
    async def scene_info(self, blend_file: str = "") -> ModuleResult:
        """Open a .blend headlessly and summarise its contents.

        Args:
            blend_file: The file to inspect; empty (or a loose name like
                "the donut") recalls a scene we have seen before.

        Returns:
            A :class:`ModuleResult` with a readable summary, and the full
            structure in ``data``.
        """
        if self.find_runtime() is None:
            return self._missing()
        target = self._find_blend(blend_file)
        if target is None:
            if (blend_file or "").strip():
                return ModuleResult.fail(
                    f"No .blend matching '{blend_file}', sir. Name the file, "
                    "or say 'the donut' if we made it before."
                )
            return ModuleResult.fail(
                "Which .blend should I inspect, sir? Name one, or say 'the "
                "donut' if we made it before."
            )
        if not self._is_blend(target):
            return ModuleResult.fail(
                f"{target.name} isn't a Blender file, sir — I need a .blend."
            )
        self.last_blend = str(target)
        self._remember(target)

        _code, out, err = await self._run_script(INSPECT_SCRIPT, str(target))
        summary = self._extract_json(out)
        if summary is None:
            return ModuleResult.fail(
                f"I couldn't read {target.name}: {self._blender_error(out, err)}"
            )

        counts = summary.get("counts", {})
        frames = summary.get("frames", [1, 1, 1])
        resolution = summary.get("resolution", [0, 0, 100])
        objects = summary.get("objects", [])
        by_type: Dict[str, int] = {}
        for entry in objects:
            by_type[entry.get("type", "?")] = by_type.get(entry.get("type", "?"), 0) + 1
        listing = ", ".join(f"{count} {kind.lower()}" for kind, count in sorted(by_type.items()))

        lines = [
            f"{target.name} — {summary.get('blender', 'Blender')}",
            f"  scene       {summary.get('scene', '?')} on {summary.get('engine', '?')}",
            f"  resolution  {resolution[0]}×{resolution[1]} at {resolution[2]}%",
            f"  frames      {frames[0]}–{frames[1]} at {summary.get('fps', 24)} fps",
            f"  contents    {listing or 'nothing at all'}",
            f"  materials   {counts.get('materials', 0)}",
        ]
        named = ", ".join(entry["name"] for entry in objects[:10])
        if named:
            lines.append(f"  objects     {named}"
                         + (f" …and {len(objects) - 10} more" if len(objects) > 10 else ""))
        return ModuleResult(
            success=True,
            output="\n".join(lines),
            speak=f"{target.name} holds {counts.get('objects', 0)} objects "
                  f"across frames {frames[0]} to {frames[1]}.",
            data=summary,
        )

    # ---------------------------------------------------------------- scripts
    @tool(
        description=(
            "Run Blender Python (bpy) headlessly, optionally against a .blend file. "
            "Use for anything the other tools do not cover."
        ),
        params={
            "script": {"type": "string", "description": "Python source, or a path to a .py",
                       "required": True},
            "blend_file": {"type": "string", "description": "Open this .blend first",
                           "default": ""},
            "save_as": {"type": "string", "description": "Save the result to this .blend",
                        "default": ""},
        },
        keywords=["run this in blender", "blender script", "bpy script",
                  "execute in blender"],
    )
    async def run_script(self, script: str, blend_file: str = "",
                         save_as: str = "") -> ModuleResult:
        """Execute Blender Python and report what it printed.

        Args:
            script: Python source, or the path to a ``.py`` file.
            blend_file: A scene to open before running.
            save_as: Save the modified scene here afterwards.

        Returns:
            A :class:`ModuleResult` with the script's output.
        """
        if not self.allow_scripts:
            return ModuleResult.fail(
                "Blender scripting is switched off — set blender.allow_scripts: true."
            )
        if self.find_runtime() is None:
            return self._missing()

        source = await self._resolve_script(script)
        if not source.strip():
            return ModuleResult.fail("There's no script to run, sir.")

        if self.security is not None:
            assessment = self.security.assess_code(source)
            if assessment.blocked:
                return ModuleResult.fail(f"Refused: {assessment.reason}")
            if assessment.needs_confirmation and getattr(
                self.security, "confirm_dangerous", True
            ):
                approved = await self.security.confirm(
                    f"This Blender script {assessment.reason.lower()}. Run it?"
                )
                if not approved:
                    return ModuleResult.fail("Cancelled — you did not confirm.")

        if save_as:
            destination = resolve_user_path(save_as)
            refusal = await self.guard_path(destination, write=True, what="save a .blend to")
            if refusal is not None:
                return refusal
            ensure_dir(destination.parent)
            source += (
                "\n\nimport bpy\n"
                f"bpy.ops.wm.save_as_mainfile(filepath={str(destination)!r})\n"
                f"print('JARVIS_SAVED', {str(destination)!r})\n"
            )

        code, out, err = await self._run_script(source, blend_file)
        if code == -9:
            return ModuleResult.fail(
                f"The script was still running after {self.timeout:.0f}s, so I stopped it."
            )
        if code != 0:
            return ModuleResult.fail(
                f"The script failed: {self._blender_error(out, err)}"
            )

        printed = self._script_output(out)
        saved = " Saved." if "JARVIS_SAVED" in out else ""
        if save_as:
            self.last_blend = str(resolve_user_path(save_as))
        return ModuleResult(
            success=True,
            output=(printed or "The script ran cleanly with no output.") + saved,
            speak="Done, sir." + (" Scene saved." if saved else ""),
            data={"stdout": out, "saved": bool(saved)},
        )

    async def _resolve_script(self, script: str) -> str:
        """Accept either Python source or a path to a ``.py`` file.

        Args:
            script: Whatever the caller supplied.

        Returns:
            The source to execute.
        """
        candidate = script.strip()
        if candidate.endswith(".py") and "\n" not in candidate:
            path = resolve_user_path(candidate)
            if path.is_file():
                return await run_blocking(path.read_text, "utf-8", "replace")
        fenced = re.search(r"```(?:python)?\s*(.+?)```", script, re.DOTALL)
        return fenced.group(1).strip() if fenced else script

    @staticmethod
    def _script_output(stdout: str) -> str:
        """Strip Blender's own start-up chatter from a script's output.

        Args:
            stdout: Everything the process printed.

        Returns:
            Just the interesting lines.
        """
        noise = (
            "Blender quit", "found bundled python", "Read prefs:", "Warning: Falling back",
            "Color management:", "Writing:", "JARVIS_SAVED", "JARVIS_EXPORTED",
            "Info: Total files", "Read blend:", "Saved:", "Fra:", "Time:", "Saving:",
            "AL lib:", "Blender:",
        )
        lines = [
            line for line in stdout.splitlines()
            if line.strip() and not any(line.startswith(prefix) for prefix in noise)
            and not line.startswith("Blender ")
        ]
        return truncate("\n".join(lines), 3000)

    # ------------------------------------------------------------ scene build
    @tool(
        description=(
            "Build a 3D scene in Blender from a plain-English description, save it "
            "as a .blend and optionally render a preview."
        ),
        params={
            "description": {"type": "string", "description": "What to build",
                            "required": True},
            "save_as": {"type": "string", "description": "Where to save the .blend",
                        "default": ""},
            "preview": {"type": "boolean", "description": "Render a still afterwards",
                        "default": True},
            "look": {"type": "string",
                     "description": "Presentational look applied after the build: "
                                    "'studio', 'soft', 'sunset' or 'minimal'. "
                                    "Blank lets the model decide.",
                     "default": ""},
        },
        keywords=["make a 3d scene", "build a 3d", "model a", "create a scene in blender"],
        examples=["make a 3d scene with a red cube on a checkered plane",
                  "make a donut scene in a studio look"],
    )
    async def make_scene(self, description: str, save_as: str = "",
                         preview: bool = True, look: str = "") -> ModuleResult:
        """Have the LLM write a bpy script, run it, and save the result.

        Args:
            description: What the user wants built.
            save_as: Where to save the ``.blend``; a sensible name is chosen
                when this is empty.
            preview: Render a still once the scene is built.
            look: A finished-scene look from :data:`LOOK_PRESETS` applied after
                the build; blank lets the model choose its own lighting.

        Returns:
            A :class:`ModuleResult` naming the .blend and any preview image.
        """
        if self.find_runtime() is None:
            return self._missing()
        if self.llm is None or not getattr(self.llm, "available", False):
            return ModuleResult.fail(
                "Building a scene from a description needs the language model, sir. "
                "Start Ollama, or give me a bpy script and I'll run it."
            )
        preset = str(look or "").strip().lower()
        if preset and preset not in LOOK_PRESETS:
            return ModuleResult.fail(
                f"Unknown look '{look}', sir. Try {', '.join(sorted(LOOK_PRESETS))}."
            )

        prompt = (
            "Write a Blender Python (bpy) script for Blender 4.x that builds this "
            f"scene:\n\n{description}\n\n"
            "Rules:\n"
            "1. Start from an empty scene: delete the default objects first.\n"
            "2. Frame the subject properly: compute the object bounds, aim the \n"
            "camera at their centre from a three-quarter angle, and pull back so \n"
            "everything fits with margin; add at least one light.\n"
            "3. Use only bpy, bmesh, mathutils and the standard library — no "
            "downloads, no file reads, no add-ons.\n"
            "4. Set materials with nodes where colour is asked for.\n"
            "5. No rendering and no saving: I do that myself.\n"
            "6. Return one ```python block and nothing else."
        )
        raw = await self.llm.complete(prompt, temperature=0.2, max_tokens=1600)
        source = await self._resolve_script(raw)
        if not source.strip():
            return ModuleResult.fail("The model didn't give me a usable script.")
        if preset:
            source = f"{source}\n\n{LOOK_PRESETS[preset]}"

        # Judge the script the model actually wrote. A scene built from bpy
        # calls needs no confirmation; one that reaches for the filesystem or
        # the network does.
        if self.security is not None:
            assessment = self.security.assess_code(source)
            if assessment.blocked:
                return ModuleResult.fail(
                    f"I won't run the script it wrote: {assessment.reason}"
                )
            if assessment.needs_confirmation and getattr(
                self.security, "confirm_dangerous", True
            ):
                approved = await self.security.confirm(
                    f"The scene script {assessment.reason.lower()}. Run it?"
                )
                if not approved:
                    return ModuleResult.fail("Cancelled — you did not confirm.")

        target = resolve_user_path(save_as) if save_as else (
            self.output_dir / f"{self._slug(description)}.blend"
        )
        refusal = await self.guard_path(target, write=True, what="save a .blend to")
        if refusal is not None:
            return refusal
        ensure_dir(target.parent)

        build = (
            "import bpy\n"
            "bpy.ops.wm.read_factory_settings(use_empty=True)\n\n"
            f"{source}\n\n"
            f"bpy.ops.wm.save_as_mainfile(filepath={str(target)!r})\n"
            f"print('JARVIS_SAVED', {str(target)!r})\n"
        )
        code, out, err = await self._run_script(build)
        if code != 0 or not target.exists():
            return ModuleResult.fail(
                f"The scene didn't build: {self._blender_error(out, err)}"
            )
        self.last_blend = str(target)
        self._remember(target)

        message = f"Built {target.name} ({human_bytes(target.stat().st_size)}) at {target}."
        data: Dict[str, Any] = {"blend": str(target), "script": source}
        if preview:
            shot = await self.render(str(target), resolution_percent=50)
            if shot.success:
                message += f"\n{shot.output}"
                data["preview"] = shot.data.get("files", [])
            else:
                message += f"\nThe preview render didn't work: {shot.error}"
        return ModuleResult(success=True, output=message,
                            speak=f"Scene built and saved as {target.name}.", data=data)

    @staticmethod
    def _slug(text: str) -> str:
        """Turn a description into a short, safe file stem.

        Args:
            text: The description.

        Returns:
            A lower-case, hyphenated stem.
        """
        words = re.findall(r"[a-z0-9]+", text.lower())
        skip = {"a", "an", "the", "of", "with", "and", "make", "build", "create",
                "scene", "3d", "model", "me", "please", "in", "blender"}
        kept = [word for word in words if word not in skip][:5]
        return "-".join(kept) or "scene"

    # ---------------------------------------------------------------- export
    @tool(
        description="Export a .blend to glTF, OBJ, FBX, STL, PLY, USD or Alembic.",
        params={
            "blend_file": {"type": "string", "description": "Source .blend", "default": ""},
            "format": {"type": "string", "description": "glb, gltf, obj, fbx, stl, ply, usd",
                       "default": "glb"},
            "output": {"type": "string", "description": "Destination file", "default": ""},
            "selected_only": {"type": "boolean", "description": "Only selected objects",
                              "default": False},
        },
        keywords=["export the model", "convert the blend", "export to glb",
                  "export as obj", "save it as fbx"],
    )
    async def export_model(self, blend_file: str = "", format: str = "glb",
                           output: str = "", selected_only: bool = False) -> ModuleResult:
        """Convert a .blend into an interchange format.

        Args:
            blend_file: The scene to export; defaults to the last one used.
            format: Target format, with or without the leading dot.
            output: Destination path; defaults to the render directory.
            selected_only: Export only what is selected in the file.

        Returns:
            A :class:`ModuleResult` naming the file written.
        """
        if self.find_runtime() is None:
            return self._missing()
        target = self._find_blend(blend_file)
        if target is None:
            return ModuleResult.fail(
                "Which .blend should I export, sir? Name one — or say 'export "
                "the donut' if we made it before."
            )
        if not self._is_blend(target):
            return ModuleResult.fail(
                f"{target.name} isn't a Blender file, sir — I need a .blend."
            )
        self.last_blend = str(target)
        self._remember(target)

        suffix = ("." + format.strip().lower().lstrip(".")) if format else ".glb"
        operator = EXPORTERS.get(suffix)
        if operator is None:
            return ModuleResult.fail(
                f"I can't export {suffix} — try {', '.join(sorted(EXPORTERS))}."
            )

        destination = (
            resolve_user_path(output) if output
            else self.output_dir / f"{target.stem}{suffix}"
        )
        if destination.is_dir():
            destination = destination / f"{target.stem}{suffix}"
        refusal = await self.guard_path(destination, write=True, what="export to")
        if refusal is not None:
            return refusal
        ensure_dir(destination.parent)

        selection = (
            "bpy.ops.object.select_all(action='SELECT')\n"
            if not selected_only else ""
        )
        script = (
            "import bpy\n"
            f"OUT = {str(destination)!r}\n"
            f"{selection}"
            f"{operator}\n"
            f"print('JARVIS_EXPORTED', OUT)\n"
        )
        code, out, err = await self._run_script(script, str(target))
        if code != 0 or not destination.exists():
            return ModuleResult.fail(
                f"The export failed: {self._blender_error(out, err)}"
            )
        self.last_blend = str(target)
        size = human_bytes(destination.stat().st_size)
        return ModuleResult(
            success=True,
            output=f"Exported {target.name} to {destination} ({size}).",
            speak=f"Exported as {destination.name}.",
            data={"path": str(destination), "bytes": destination.stat().st_size},
        )

    # ------------------------------------------------------------------ misc
    @tool(
        description="Open a .blend in the Blender GUI (needs the application, not bpy).",
        params={"blend_file": {"type": "string", "description": "File to open",
                               "default": ""}},
        keywords=["open blender", "launch blender", "open it in blender"],
    )
    async def open_blender(self, blend_file: str = "") -> ModuleResult:
        """Launch the Blender application, optionally on a file.

        Args:
            blend_file: The scene to open; blank starts an empty Blender.

        Returns:
            A :class:`ModuleResult` confirming the launch.
        """
        runtime = self.find_runtime()
        if runtime is None:
            return self._missing()
        kind, path = runtime
        if kind != "executable":
            return ModuleResult.fail(
                "Only the bpy Python module is installed here, sir — it has no "
                "window. Install the Blender application to open scenes."
            )
        target = resolve_user_path(blend_file or self.last_blend) if (
            blend_file or self.last_blend
        ) else None
        if target is not None and not target.is_file():
            return ModuleResult.fail(f"No .blend file at {target}.")

        import subprocess

        try:
            await run_blocking(
                lambda: subprocess.Popen(
                    [path, *( [str(target)] if target else [] )],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=not IS_WINDOWS,
                )
            )
        except Exception as exc:
            return ModuleResult.fail(f"Blender wouldn't start: {exc}")
        where = f" with {target.name}" if target else ""
        return ModuleResult.ok(f"Blender is opening{where}, sir.")

    @tool(
        description="List the renders and exports JARVIS has produced.",
        params={"limit": {"type": "integer", "description": "How many", "default": 15}},
        keywords=["recent renders", "what have you rendered", "list renders",
                  "renders so far", "render folder"],
    )
    async def list_renders(self, limit: int = 15) -> ModuleResult:
        """Show the most recent files in the render directory.

        Args:
            limit: How many to list.

        Returns:
            A :class:`ModuleResult` with the newest first.
        """
        if not self.output_dir.is_dir():
            return ModuleResult(success=True, output="Nothing rendered yet, sir.",
                                data={"files": []})
        files = sorted(
            (path for path in self.output_dir.rglob("*") if path.is_file()),
            key=lambda path: path.stat().st_mtime, reverse=True,
        )[: max(1, int(limit))]
        if not files:
            return ModuleResult(success=True, output="Nothing rendered yet, sir.",
                                data={"files": []})
        listing = "\n".join(
            f"  {path.relative_to(self.output_dir)} ({human_bytes(path.stat().st_size)})"
            for path in files
        )
        return ModuleResult(
            success=True,
            output=f"{len(files)} file(s) in {self.output_dir}:\n{listing}",
            speak=f"{len(files)} renders on file.",
            data={"files": [str(path) for path in files]},
        )


__all__ = ["ENGINES", "EXPORTERS", "FORMATS", "Blender"]
