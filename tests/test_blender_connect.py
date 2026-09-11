from __future__ import annotations

import unittest
from unittest.mock import patch

from core.approval_policy import assess_tool
from plugins import blender_control


class BlenderConnectWorkflowTests(unittest.TestCase):
    def test_connect_runs_bounded_ui_sequence_then_verifies_tools(self):
        ui_results = iter(
            [
                "Focused window: Blender",
                "Pressed: n",
                "Waited 0.7s",
                "Clicked 'the existing Blender MCP panel tab' at (100, 100)",
                "Waited 0.7s",
                "Clicked 'the Blender MCP add-on connection control' at (100, 100)",
                "Waited 1.0s",
            ]
        )
        ui_calls: list[dict] = []

        def fake_ui(parameters, player=None):
            ui_calls.append(dict(parameters))
            return next(ui_results)

        with (
            patch.object(blender_control, "_blender_is_running", return_value=False),
            patch("actions.open_app.open_app", return_value="Opened Blender."),
            patch.object(blender_control, "_computer_step", side_effect=fake_ui),
            patch.object(blender_control.time, "sleep"),
            patch.object(
                blender_control,
                "test_connection",
                return_value=(True, "Blender MCP tools:\n- get_scene_info"),
            ) as verify,
        ):
            result = blender_control._connect_existing_blender()

        self.assertIn("connected successfully", result.lower())
        verify.assert_called_once_with()
        self.assertEqual(
            [call["action"] for call in ui_calls],
            ["focus_window", "press", "wait", "screen_click", "wait", "screen_click", "wait"],
        )
        self.assertEqual(ui_calls[1]["key"], "n")
        self.assertIn("existing Blender MCP panel", ui_calls[3]["description"])
        self.assertIn("Connect to MCP server", ui_calls[5]["description"])

    def test_connect_reports_panel_failure_without_claiming_mcp_success(self):
        ui_results = iter(
            [
                "Focused window: Blender",
                "Pressed: n",
                "Waited 0.7s",
                "Element not found on screen: 'the existing Blender MCP panel tab'",
            ]
        )

        with (
            patch.object(blender_control, "_blender_is_running", return_value=False),
            patch("actions.open_app.open_app", return_value="Opened Blender."),
            patch.object(blender_control, "_computer_step", side_effect=lambda *args, **kwargs: next(ui_results)),
            patch.object(blender_control.time, "sleep"),
            patch.object(blender_control, "test_connection") as verify,
        ):
            result = blender_control._connect_existing_blender()

        self.assertIn("could not locate", result.lower())
        self.assertNotIn("connected successfully", result.lower())
        verify.assert_not_called()

    def test_connect_is_confirmation_gated_by_runtime_policy(self):
        decision = assess_tool("blender_control", {"action": "connect"})
        self.assertTrue(decision.requires_confirmation)
        self.assertNotEqual(decision.risk, "read_only")


if __name__ == "__main__":
    unittest.main()
