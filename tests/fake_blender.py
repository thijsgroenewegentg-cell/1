#!/usr/bin/env python3
# /tests/fake_blender.py
"""A stand-in for the Blender executable, so the CLI integration can be tested.

Blender is a 300 MB application; CI machines and this project's own test run
do not have one. This script accepts the arguments ``modules/blender.py``
actually sends, behaves the way Blender behaves, and writes the files Blender
would write — which is exactly what needs testing: argument order, output
discovery, JSON extraction and the error paths.

It understands::

    fake_blender.py --version
    fake_blender.py -b [file.blend] --factory-startup -noaudio -P script.py
    fake_blender.py -b file.blend -E CYCLES -o /out/frame_ -F PNG -f 7
    fake_blender.py -b file.blend -o /out/frame_ -F PNG -a
    fake_blender.py -b file.blend --python-expr "import bpy; ..."

Scripts run against a small fake ``bpy`` module covering the API surface
JARVIS uses. A ``.blend`` here is a JSON document, so a test can describe a
scene in a sentence and assert on what comes back.

Nothing in the assistant imports this file; it is a test asset.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = "4.5.3"
BANNER = f"Blender {VERSION}\n\tbuild date: 2026-09-01\n\tbuild type: release"

SUFFIXES = {
    "PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "OPEN_EXR": ".exr",
    "TIFF": ".tif", "BMP": ".bmp", "FFMPEG": ".mp4", "AVI_JPEG": ".avi",
}


class FakeObject:
    """One object in the fake scene."""

    def __init__(self, name: str, kind: str = "MESH",
                 location: Optional[List[float]] = None) -> None:
        """Store the handful of attributes the inspection script reads."""
        self.name = name
        self.type = kind
        self.location = location or [0.0, 0.0, 0.0]
        self.hide_render = False


class FakeCollection(list):
    """A list that also supports ``.new()``/``.remove()`` like bpy collections."""

    def new(self, name: str = "Thing", *args: Any, **kwargs: Any) -> Any:
        """Append a named entry and return it."""
        entry = types.SimpleNamespace(name=name)
        self.append(entry)
        return entry

    def remove(self, item: Any) -> None:
        """Drop an entry if it is present."""
        if item in self:
            super().remove(item)


class FakeScene:
    """Enough of ``bpy.types.Scene`` for the scripts JARVIS writes."""

    def __init__(self) -> None:
        """Start from Blender's own defaults."""
        self.name = "Scene"
        self.frame_start = 1
        self.frame_end = 1
        self.frame_current = 1
        self.render = types.SimpleNamespace(
            engine="BLENDER_EEVEE_NEXT",
            resolution_x=1920,
            resolution_y=1080,
            resolution_percentage=100,
            fps=24,
            filepath="/tmp/",
            image_settings=types.SimpleNamespace(file_format="PNG"),
        )
        self.cycles = types.SimpleNamespace(samples=128)
        self.eevee = types.SimpleNamespace(taa_render_samples=64)
        self.collection = types.SimpleNamespace(objects=FakeCollection())

    def frame_set(self, frame: int) -> None:
        """Move the playhead."""
        self.frame_current = int(frame)


class FakeBpy:
    """The subset of ``bpy`` the assistant's scripts touch."""

    def __init__(self) -> None:
        """Build an empty document with one scene."""
        self.app = types.SimpleNamespace(version_string=VERSION, version=(4, 5, 3),
                                         binary_path=str(Path(__file__).resolve()))
        self.scene = FakeScene()
        self.data = types.SimpleNamespace(
            filepath="",
            objects=FakeCollection(),
            meshes=FakeCollection(),
            materials=FakeCollection(),
            images=FakeCollection(),
            collections=FakeCollection(),
            scenes=FakeCollection([self.scene]),
        )
        self.context = types.SimpleNamespace(scene=self.scene, view_layer=None,
                                             selected_objects=[], object=None)
        self.ops = self._build_ops()
        self.types = types.SimpleNamespace(Scene=FakeScene, Object=FakeObject)
        self.rendered: List[Path] = []

    # -- operators ---------------------------------------------------------
    def _build_ops(self) -> Any:
        """Assemble the ``bpy.ops.*`` namespaces used by the module."""

        def open_mainfile(filepath: str = "", **_: Any) -> Dict[str, str]:
            """Load a fake .blend (a JSON document) into this session."""
            path = Path(filepath)
            if not path.is_file():
                raise RuntimeError(f"Error: Cannot read file {filepath}")
            document = json.loads(path.read_text() or "{}")
            self.data.filepath = str(path)
            self.data.objects = FakeCollection(
                FakeObject(entry.get("name", "Object"), entry.get("type", "MESH"),
                           entry.get("location"))
                for entry in document.get("objects", [])
            )
            self.data.materials = FakeCollection(
                types.SimpleNamespace(name=name)
                for name in document.get("materials", [])
            )
            self.data.meshes = FakeCollection(
                obj for obj in self.data.objects if obj.type == "MESH"
            )
            self.data.collections = FakeCollection(
                types.SimpleNamespace(name=name)
                for name in document.get("collections", [])
            )
            scene = document.get("scene", {})
            self.scene.name = scene.get("name", "Scene")
            self.scene.frame_start = scene.get("frame_start", 1)
            self.scene.frame_end = scene.get("frame_end", 1)
            self.scene.render.engine = scene.get("engine", "BLENDER_EEVEE_NEXT")
            self.scene.render.fps = scene.get("fps", 24)
            return {"FINISHED"}

        def save_as_mainfile(filepath: str = "", **_: Any) -> Dict[str, str]:
            """Write the session out as a fake .blend."""
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "objects": [
                    {"name": obj.name, "type": obj.type, "location": list(obj.location)}
                    for obj in self.data.objects
                ],
                "materials": [material.name for material in self.data.materials],
                "scene": {"name": self.scene.name,
                          "frame_start": self.scene.frame_start,
                          "frame_end": self.scene.frame_end,
                          "engine": self.scene.render.engine,
                          "fps": self.scene.render.fps},
            }, indent=1))
            self.data.filepath = str(path)
            print(f"Info: Total files 1 | Saved {path}")
            return {"FINISHED"}

        def render(animation: bool = False, write_still: bool = False,
                   **_: Any) -> Dict[str, str]:
            """Write the image files a render would produce."""
            if not any(obj.type == "CAMERA" for obj in self.data.objects):
                raise RuntimeError("Error: No camera found in scene")
            suffix = SUFFIXES.get(self.scene.render.image_settings.file_format, ".png")
            frames = (range(self.scene.frame_start, self.scene.frame_end + 1)
                      if animation else [self.scene.frame_current])
            for frame in frames:
                self.rendered.append(write_frame(self.scene.render.filepath,
                                                 frame, suffix))
            return {"FINISHED"}

        def read_factory_settings(use_empty: bool = False, **_: Any) -> Dict[str, str]:
            """Reset the session, optionally to a completely empty document."""
            self.data.objects = FakeCollection()
            self.data.materials = FakeCollection()
            self.data.meshes = FakeCollection()
            if not use_empty:
                self.data.objects.extend([
                    FakeObject("Cube"), FakeObject("Camera", "CAMERA"),
                    FakeObject("Light", "LIGHT"),
                ])
            return {"FINISHED"}

        def add_primitive(kind: str) -> Any:
            """Return a ``primitive_*_add`` operator that adds a mesh."""

            def operator(**kwargs: Any) -> Dict[str, str]:
                """Add one primitive at the requested location."""
                obj = FakeObject(kind.title(), "MESH",
                                 list(kwargs.get("location", (0.0, 0.0, 0.0))))
                self.data.objects.append(obj)
                self.data.meshes.append(obj)
                self.context.object = obj
                return {"FINISHED"}

            return operator

        def add_object(kind: str) -> Any:
            """Return an ``object_add``-style operator for cameras and lights."""

            def operator(**kwargs: Any) -> Dict[str, str]:
                """Add one camera or light."""
                obj = FakeObject(kind.title(), kind.upper(),
                                 list(kwargs.get("location", (0.0, 0.0, 0.0))))
                self.data.objects.append(obj)
                self.context.object = obj
                return {"FINISHED"}

            return operator

        def exporter(default_suffix: str) -> Any:
            """Return an export operator that writes a small placeholder file."""

            def operator(filepath: str = "", **_: Any) -> Dict[str, str]:
                """Write the exported file."""
                path = Path(filepath or f"export{default_suffix}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fake-export\x00" + path.suffix.encode())
                print(f"Writing: {path}")
                return {"FINISHED"}

            return operator

        def select_all(action: str = "SELECT", **_: Any) -> Dict[str, str]:
            """Select or deselect everything."""
            self.context.selected_objects = (
                list(self.data.objects) if action == "SELECT" else []
            )
            return {"FINISHED"}

        def delete(**_: Any) -> Dict[str, str]:
            """Delete the selection."""
            for obj in list(self.context.selected_objects):
                if obj in self.data.objects:
                    self.data.objects.remove(obj)
            self.context.selected_objects = []
            return {"FINISHED"}

        return types.SimpleNamespace(
            wm=types.SimpleNamespace(
                open_mainfile=open_mainfile,
                save_as_mainfile=save_as_mainfile,
                read_factory_settings=read_factory_settings,
                obj_export=exporter(".obj"),
                stl_export=exporter(".stl"),
                ply_export=exporter(".ply"),
                usd_export=exporter(".usdz"),
                alembic_export=exporter(".abc"),
                quit_blender=lambda **_: {"FINISHED"},
            ),
            render=types.SimpleNamespace(render=render),
            object=types.SimpleNamespace(
                select_all=select_all, delete=delete,
                camera_add=add_object("camera"), light_add=add_object("light"),
                shade_smooth=lambda **_: {"FINISHED"},
            ),
            mesh=types.SimpleNamespace(**{
                f"primitive_{name}_add": add_primitive(name)
                for name in ("cube", "uv_sphere", "plane", "cylinder", "cone",
                             "torus", "monkey", "ico_sphere", "grid")
            }),
            export_scene=types.SimpleNamespace(
                gltf=exporter(".glb"), fbx=exporter(".fbx"), obj=exporter(".obj"),
            ),
        )


def write_frame(prefix: str, frame: int, suffix: str) -> Path:
    """Write one rendered frame where Blender would put it.

    Args:
        prefix: The ``-o`` prefix, which may name a directory or a file stem.
        frame: The frame number, zero-padded to four digits like Blender's.
        suffix: The file extension for the chosen format.

    Returns:
        The path written.
    """
    base = Path(prefix)
    if str(prefix).endswith(("/", "\\")) or base.is_dir():
        target = base / f"{frame:04d}{suffix}"
    else:
        target = base.with_name(f"{base.name}{frame:04d}{suffix}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake pixels" * 8)
    print(f"Saved: '{target}'")
    return target


def run_script(source: str, bpy: FakeBpy) -> int:
    """Execute a script the way Blender's ``-P`` does.

    Args:
        source: The Python source.
        bpy: The fake module to expose as ``bpy``.

    Returns:
        A process exit code: 0, or 1 when the script raised.
    """
    sys.modules["bpy"] = bpy  # type: ignore[assignment]
    sys.modules.setdefault("bmesh", types.ModuleType("bmesh"))
    mathutils = types.ModuleType("mathutils")
    mathutils.Vector = lambda values=(0, 0, 0): list(values)  # type: ignore[attr-defined]
    mathutils.Euler = lambda values=(0, 0, 0), order="XYZ": list(values)  # type: ignore[attr-defined]
    sys.modules.setdefault("mathutils", mathutils)
    namespace: Dict[str, Any] = {"__name__": "__main__", "bpy": bpy}
    try:
        exec(compile(source, "<blender script>", "exec"), namespace)
    except Exception as error:
        import traceback

        print("Traceback (most recent call last):", file=sys.stderr)
        traceback.print_exc()
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


def main(argv: List[str]) -> int:
    """Parse Blender's command line and act on it.

    Args:
        argv: Arguments after the executable name.

    Returns:
        The process exit code.
    """
    if "--version" in argv or "-v" in argv:
        print(BANNER)
        return 0

    bpy = FakeBpy()
    blend_file = ""
    script_path = ""
    expressions: List[str] = []
    output_prefix = ""
    image_format = "PNG"
    frame: Optional[int] = None
    animation = False

    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument in ("-b", "--background", "--factory-startup", "-noaudio", "-y"):
            pass
        elif argument in ("-P", "--python"):
            index += 1
            script_path = argv[index]
        elif argument == "--python-expr":
            index += 1
            expressions.append(argv[index])
        elif argument in ("-o", "--render-output"):
            index += 1
            output_prefix = argv[index]
        elif argument in ("-F", "--render-format"):
            index += 1
            image_format = argv[index]
        elif argument in ("-E", "--engine"):
            index += 1
            bpy.scene.render.engine = argv[index]
        elif argument in ("-f", "--render-frame"):
            index += 1
            frame = int(argv[index])
        elif argument in ("-a", "--render-anim"):
            animation = True
        elif argument in ("-s", "--frame-start"):
            index += 1
            bpy.scene.frame_start = int(argv[index])
        elif argument in ("-e", "--frame-end"):
            index += 1
            bpy.scene.frame_end = int(argv[index])
        elif not argument.startswith("-") and argument.endswith(".blend"):
            blend_file = argument
        index += 1

    print(BANNER.splitlines()[0])
    if blend_file:
        try:
            bpy.ops.wm.open_mainfile(filepath=blend_file)
        except Exception as error:
            print(str(error), file=sys.stderr)
            return 1
        print(f"Read blend: \"{blend_file}\"")

    for expression in expressions:
        code = run_script(expression, bpy)
        if code:
            return code

    if script_path:
        source = Path(script_path).read_text(encoding="utf-8")
        code = run_script(source, bpy)
        if code:
            return code

    if output_prefix and (frame is not None or animation):
        suffix = SUFFIXES.get(image_format.upper(), ".png")
        if not any(obj.type == "CAMERA" for obj in bpy.data.objects):
            print("Error: No camera found in scene", file=sys.stderr)
            return 1
        frames = (range(bpy.scene.frame_start, bpy.scene.frame_end + 1)
                  if animation else [frame or bpy.scene.frame_current])
        for number in frames:
            write_frame(output_prefix, number, suffix)

    print("Blender quit")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
