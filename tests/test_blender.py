# /tests/test_blender.py
"""Unit tests for modules/blender.py.

Blender is a 300 MB application and CI has none, so these run against
``tests/fake_blender.py`` — a stand-in that accepts the same arguments and
writes the same files. What is under test is the part JARVIS owns: finding
the runtime, building Blender's command line in the order it expects,
noticing which frames were written, extracting the JSON our inspection script
prints, and failing legibly when Blender does.
"""

from __future__ import annotations

import json
import sys

import pytest

from modules.blender import ENGINES, EXPORTERS, FORMATS, Blender
from tests.conftest import PROJECT_ROOT, run

FAKE_BLENDER = PROJECT_ROOT / "tests" / "fake_blender.py"

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="the stand-in relies on a POSIX shebang",
)


@pytest.fixture
def blender(config, tmp_path):
    """A Blender module pointed at the stand-in executable."""
    config.set("blender.executable", str(FAKE_BLENDER))
    config.set("blender.output_dir", str(tmp_path / "renders"))
    return Blender(config)


@pytest.fixture
def scene(tmp_path):
    """A .blend file the stand-in understands: three objects, three frames."""
    path = tmp_path / "city.blend"
    path.write_text(json.dumps({
        "objects": [
            {"name": "Cube", "type": "MESH", "location": [0, 0, 0]},
            {"name": "Camera", "type": "CAMERA", "location": [7, -7, 5]},
            {"name": "Sun", "type": "LIGHT", "location": [4, 4, 9]},
        ],
        "materials": ["Concrete", "Glass"],
        "collections": ["Buildings"],
        "scene": {"name": "Scene", "frame_start": 1, "frame_end": 3,
                  "engine": "CYCLES", "fps": 25},
    }))
    return path


# ------------------------------------------------------------------ discovery
def test_the_configured_executable_is_used(blender):
    runtime = blender.find_runtime(refresh=True)
    assert runtime is not None
    assert runtime[0] == "executable"
    assert runtime[1] == str(FAKE_BLENDER)


def test_a_missing_blender_is_reported_helpfully(config, tmp_path):
    config.set("blender.executable", str(tmp_path / "nowhere" / "blender"))
    config.set("blender.allow_bpy_module", False)
    module = Blender(config)
    module._runtime = None
    if module.find_runtime(refresh=True) is not None:
        pytest.skip("a real Blender is installed on this machine")
    result = run(module.call_tool("blender_status", {}))
    assert not result.success
    assert "blender.org" in result.error or "pip install bpy" in result.error


def test_status_reports_the_version(blender):
    result = run(blender.call_tool("blender_status", {}))
    assert result.success
    assert "4.5" in result.output
    assert result.data["runtime"] == "executable"


# -------------------------------------------------------------------- routing
@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("render frame 4 of ~/scenes/city.blend", "render"),
        ("render the animation", "render"),
        ("what's in ~/models/chair.blend", "scene_info"),
        ("export chair.blend to glb", "export_model"),
        ("is blender installed", "blender_status"),
        ("make a 3d scene with a red cube", "make_scene"),
        ("run this in blender: import bpy", "run_script"),
    ],
)
def test_offline_router_recognises_blender_work(blender, phrase, expected):
    routed = blender.offline_router(phrase)
    assert routed is not None, f"{phrase!r} should route without an LLM"
    assert routed[0] == expected


def test_the_router_extracts_the_frame_number(blender):
    _tool, params = blender.offline_router("render frame 12 of city.blend")
    assert params["frame"] == 12
    assert params["blend_file"] == "city.blend"


def test_the_router_notices_an_animation(blender):
    _tool, params = blender.offline_router("render the animation of city.blend")
    assert params["animation"] is True


# --------------------------------------------------------------------- render
def test_a_single_frame_is_rendered(blender, scene):
    result = run(blender.call_tool("render", {"blend_file": str(scene), "frame": 2}))
    assert result.success
    written = result.data["files"]
    assert len(written) == 1
    assert written[0].endswith("0002.png")


def test_rendering_the_same_frame_twice_still_reports_it(blender, scene):
    # Diffing against "files that existed before" reported nothing the second
    # time, which reads as a failure.
    run(blender.call_tool("render", {"blend_file": str(scene), "frame": 2}))
    again = run(blender.call_tool("render", {"blend_file": str(scene), "frame": 2}))
    assert again.success
    assert len(again.data["files"]) == 1


def test_an_animation_renders_every_frame(blender, scene):
    result = run(blender.call_tool("render", {"blend_file": str(scene), "animation": True}))
    assert result.success
    assert len(result.data["files"]) == 3


def test_the_output_path_is_honoured(blender, scene, tmp_path):
    destination = tmp_path / "elsewhere"
    result = run(blender.call_tool(
        "render", {"blend_file": str(scene), "frame": 1, "output": str(destination)}
    ))
    assert result.success
    assert all(str(destination) in path for path in result.data["files"])


def test_the_format_is_honoured(blender, scene):
    result = run(blender.call_tool(
        "render", {"blend_file": str(scene), "frame": 1, "format": "jpg"}
    ))
    assert result.success
    assert result.data["files"][0].endswith(".jpg")


def test_rendering_without_a_file_asks_which_one(blender):
    result = run(blender.call_tool("render", {}))
    assert not result.success
    assert "which" in result.error.lower()


def test_rendering_a_missing_file_fails_politely(blender, tmp_path):
    result = run(blender.call_tool("render", {"blend_file": str(tmp_path / "ghost.blend")}))
    assert not result.success
    assert "no .blend" in result.error.lower()


def test_a_scene_with_no_camera_is_explained(blender, tmp_path):
    headless = tmp_path / "nocam.blend"
    headless.write_text(json.dumps({"objects": [{"name": "Cube", "type": "MESH"}]}))
    result = run(blender.call_tool("render", {"blend_file": str(headless), "frame": 1}))
    assert not result.success
    assert "camera" in (result.error + result.output).lower()


# ----------------------------------------------------------------- inspection
def test_a_blend_file_is_summarised(blender, scene):
    result = run(blender.call_tool("scene_info", {"blend_file": str(scene)}))
    assert result.success
    assert "CYCLES" in result.output
    assert "1–3" in result.output
    assert result.data["counts"]["objects"] == 3
    assert result.data["cameras"] == ["Camera"]
    assert "Concrete" in result.data["materials"]


def test_inspecting_a_missing_file_fails_politely(blender, tmp_path):
    result = run(blender.call_tool("scene_info", {"blend_file": str(tmp_path / "no.blend")}))
    assert not result.success


def test_scene_contents_are_treated_as_untrusted(blender):
    # A .blend can carry object names written by someone else.
    assert blender.tools["scene_info"].untrusted


# -------------------------------------------------------------------- scripts
def test_a_script_runs_and_its_output_comes_back(blender, scene):
    result = run(blender.call_tool("run_script", {
        "script": "import bpy\nprint('objects:', len(bpy.data.objects))",
        "blend_file": str(scene),
    }))
    assert result.success
    assert result.output.strip() == "objects: 3"


def test_blender_chatter_is_stripped_from_script_output(blender, scene):
    result = run(blender.call_tool("run_script", {
        "script": "print('just this')", "blend_file": str(scene),
    }))
    assert result.output.strip() == "just this"


def test_a_failing_script_reports_the_error(blender):
    result = run(blender.call_tool("run_script", {"script": "raise ValueError('boom')"}))
    assert not result.success
    assert "boom" in result.error


def test_a_script_can_save_the_result(blender, scene, tmp_path):
    destination = tmp_path / "modified.blend"
    result = run(blender.call_tool("run_script", {
        "script": "import bpy\nbpy.ops.mesh.primitive_cube_add(location=(1, 2, 3))",
        "blend_file": str(scene),
        "save_as": str(destination),
    }))
    assert result.success
    assert destination.is_file()
    assert json.loads(destination.read_text())["objects"]


def test_scripting_can_be_switched_off(config, tmp_path):
    config.set("blender.executable", str(FAKE_BLENDER))
    config.set("blender.allow_scripts", False)
    module = Blender(config)
    result = run(module.call_tool("run_script", {"script": "print(1)"}))
    assert not result.success
    assert "switched off" in result.error


def test_an_empty_script_is_refused(blender):
    assert not run(blender.call_tool("run_script", {"script": "   "})).success


def test_fenced_code_is_unwrapped(blender):
    result = run(blender.call_tool("run_script", {
        "script": "Here you go:\n```python\nprint('unwrapped')\n```",
    }))
    assert result.success
    assert "unwrapped" in result.output


# --------------------------------------------------------------------- export
@pytest.mark.parametrize("fmt", ["glb", "obj", "fbx", "stl", "ply"])
def test_a_model_exports(blender, scene, fmt):
    result = run(blender.call_tool(
        "export_model", {"blend_file": str(scene), "format": fmt}
    ))
    assert result.success, result.error
    assert result.data["path"].endswith(f".{fmt}")


def test_an_unknown_export_format_is_refused(blender, scene):
    result = run(blender.call_tool(
        "export_model", {"blend_file": str(scene), "format": "dwg"}
    ))
    assert not result.success
    assert "glb" in result.error


def test_export_remembers_the_last_file(blender, scene):
    run(blender.call_tool("scene_info", {"blend_file": str(scene)}))
    result = run(blender.call_tool("export_model", {"format": "glb"}))
    assert result.success


# ------------------------------------------------------------------ inventory
def test_renders_are_listed_newest_first(blender, scene):
    run(blender.call_tool("render", {"blend_file": str(scene), "animation": True}))
    result = run(blender.call_tool("list_renders", {}))
    assert result.success
    assert "3 file" in result.output or "file(s)" in result.output


def test_listing_with_nothing_rendered_is_calm(blender):
    result = run(blender.call_tool("list_renders", {}))
    assert result.success


# ------------------------------------------------------------------- mappings
def test_the_engine_aliases_are_blender_identifiers():
    for identifier in ENGINES.values():
        assert identifier.isupper()
        assert identifier.startswith(("BLENDER_", "CYCLES"))


def test_every_exporter_names_an_operator():
    for suffix, call in EXPORTERS.items():
        assert suffix.startswith(".")
        assert call.startswith("bpy.ops.")
        assert "OUT" in call


def test_the_common_formats_are_offered():
    for name in ("png", "jpg", "webp", "exr", "mp4"):
        assert name in FORMATS


def test_asking_about_renders_is_not_a_request_to_render(blender):
    # "what have you rendered" contains the word "render".
    routed = blender.offline_router("what have you rendered")
    assert routed is not None and routed[0] == "list_renders"


def test_a_scene_is_built_from_a_description(blender, tmp_path, monkeypatch):
    """make_scene: the model writes bpy, JARVIS runs it and saves the result."""
    class FakeLLM:
        available = True

        async def complete(self, prompt: str, **kwargs: object) -> str:
            assert "bpy" in prompt
            return (
                "```python\n"
                "import bpy\n"
                "bpy.ops.mesh.primitive_cube_add(location=(0, 0, 1))\n"
                "bpy.ops.object.camera_add(location=(6, -6, 4))\n"
                "bpy.ops.object.light_add(location=(3, 3, 8))\n"
                "```"
            )

    blender.llm = FakeLLM()
    destination = tmp_path / "cube.blend"
    result = run(blender.call_tool("make_scene", {
        "description": "a red cube on a plane",
        "save_as": str(destination),
        "preview": True,
    }))
    assert result.success, result.error
    assert destination.is_file()
    saved = json.loads(destination.read_text())
    assert {entry["type"] for entry in saved["objects"]} >= {"MESH", "CAMERA", "LIGHT"}
    assert result.data.get("preview"), "a preview render was requested"


def test_building_a_scene_without_a_model_says_so(blender):
    result = run(blender.call_tool("make_scene", {"description": "a castle"}))
    assert not result.success
    assert "language model" in result.error.lower()


def test_a_description_becomes_a_sensible_filename(blender):
    assert blender._slug("make me a 3d scene of a red sports car") == "red-sports-car"
    assert blender._slug("!!!") == "scene"


# ------------------------------------------------------- files that are not scenes
def test_a_text_file_is_not_a_scene(blender, tmp_path):
    junk = tmp_path / "notes.txt"
    junk.write_text("this is not a blender file")
    for name, params in (("scene_info", {"blend_file": str(junk)}),
                         ("render", {"blend_file": str(junk)}),
                         ("export_model", {"blend_file": str(junk), "format": "glb"})):
        result = run(blender.call_tool(name, params))
        assert not result.success, name
        assert "blender file" in result.error.lower()


def test_blend_backups_are_still_accepted(blender, scene, tmp_path):
    backup = tmp_path / "city.blend1"
    backup.write_text(scene.read_text())
    result = run(blender.call_tool("scene_info", {"blend_file": str(backup)}))
    assert result.success


def test_unrelated_files_are_not_counted_as_rendered(blender, scene, tmp_path):
    # A recent file sharing the output prefix was reported as a rendered frame.
    destination = tmp_path / "out"
    destination.mkdir()
    intruder = destination / "city_notes.txt"
    intruder.write_text("nothing to do with the render")

    result = run(blender.call_tool(
        "render", {"blend_file": str(scene), "frame": 1, "output": str(destination)}
    ))
    assert result.success
    assert all(path.endswith((".png", ".jpg")) for path in result.data["files"])
    assert not any("notes" in path for path in result.data["files"])


def test_every_tool_is_still_registered(blender):
    # A helper wedged between @tool and its function silently unregisters it.
    for name in ("blender_status", "render", "scene_info", "run_script",
                 "make_scene", "export_model", "open_blender", "list_renders"):
        assert name in blender.tools, name
