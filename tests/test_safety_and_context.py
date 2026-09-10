import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.blender_bridge import _MCPProcess, validate_arguments
from core.project_context import describe
from memory import memory_manager


class BlenderSafetyTests(unittest.TestCase):
    def test_only_bounded_external_tool_names_are_admitted(self):
        self.assertTrue(_MCPProcess._safe_tool_name("get_scene_info"))
        self.assertTrue(_MCPProcess._safe_tool_name("create_object"))
        self.assertFalse(_MCPProcess._safe_tool_name("execute_blender_code"))
        self.assertFalse(_MCPProcess._safe_tool_name("arbitrary_operation"))

    def test_code_like_arguments_are_rejected(self):
        self.assertIsNone(validate_arguments({"location": [0, 1, 2]}))
        self.assertIsNotNone(validate_arguments({"script": "bpy.ops.mesh.primitive_cube_add()"}))

    def test_advertised_schema_with_code_property_is_not_safe(self):
        self.assertFalse(_MCPProcess._safe_tool_definition({
            "name": "modify_object",
            "description": "Modify a bounded object",
            "inputSchema": {
                "type": "object",
                "properties": {"script": {"type": "string"}},
            },
        }))


class ProjectContextTests(unittest.TestCase):
    def test_context_is_an_inventory_and_project_memory_is_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("private source is not read", encoding="utf-8")
            (root / "secret.txt").write_text("private source is not read", encoding="utf-8")
            text = describe(root)
            self.assertIn("README.md", text)
            self.assertNotIn("secret.txt", text)
            self.assertNotIn("private source is not read", text)

    def test_project_event_redacts_secret_like_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(memory_manager, "PROJECT_MEMORY_DIR", Path(directory)):
                memory_manager.record_project_event(
                    Path(directory) / "demo",
                    "session",
                    "summary",
                    summary="Used api_key=do-not-store to test the build",
                )
                prompt = memory_manager.project_context_prompt(Path(directory) / "demo")
                self.assertIn("api_key=<redacted>", prompt)
                self.assertNotIn("do-not-store", prompt)


if __name__ == "__main__":
    unittest.main()
