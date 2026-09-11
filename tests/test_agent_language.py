from __future__ import annotations

import unittest
from unittest.mock import patch

from core.agent_orchestrator import AgentOrchestrator, analyze_request, build_preview, get_orchestrator
from core.i18n import detect_language, edge_voice, language_instruction, tr
from core.blender_bridge import connection_status
from core.approval_policy import assess_tool


class AgentAndLanguageTests(unittest.TestCase):
    def test_dutch_detection_prompt_and_voice_are_local(self):
        self.assertEqual(detect_language("Verbind MARK met Blender alsjeblieft"), "nl")
        self.assertEqual(edge_voice("nl", "Fenna"), "nl-NL-FennaNeural")
        self.assertIn("Dutch", language_instruction("nl"))
        self.assertEqual(tr("TASK PLAN", "nl"), "TAKENSPLAN")

    def test_orchestrator_creates_bounded_multistep_profile(self):
        profile = analyze_request(
            "Open Blender en maak daarna een productfoto met driepuntsbelichting",
            "auto",
        )
        self.assertEqual(profile.language, "nl")
        self.assertTrue(profile.requires_plan)
        self.assertIn("blender", profile.domains)
        self.assertLessEqual(profile.estimated_steps, 8)
        self.assertGreaterEqual(len(profile.suggested_steps), 2)

    def test_preview_never_executes_and_is_localized(self):
        profile = analyze_request("render dit in Blender", "nl")
        preview = build_preview("blender_control", {"action": "render"}, profile)
        self.assertIn("geen wijziging uitgevoerd", preview)
        self.assertIn("dry-run", preview)

    def test_orchestrator_records_tool_lifecycle(self):
        orchestrator = AgentOrchestrator()
        orchestrator.begin("Inspecteer Blender en controleer de render", "nl")
        orchestrator.tool_started("blender_control", {"action": "status"})
        orchestrator.tool_finished("blender_control", "scene verified", True)
        rendered = orchestrator.render()
        self.assertIn("REQUEST PREFLIGHT", rendered)
        self.assertIn("tool_finished", rendered)

    def test_agent_control_can_inspect_live_orchestrator(self):
        self.assertIs(get_orchestrator(), get_orchestrator())
        get_orchestrator().begin("Inspecteer de Blender-scene", "nl")
        from actions.agent_control import run
        self.assertIn("REQUEST PREFLIGHT", run({"action": "status"}))

    def test_dynamic_blender_mutations_remain_confirmation_gated(self):
        self.assertEqual(assess_tool("blender_mcp_get_scene_info", {}).risk, "read_only")
        self.assertEqual(assess_tool("blender_control", {"action": "mcp_call", "mcp_tool": "get_scene_info"}).risk, "read_only")
        self.assertNotEqual(assess_tool("blender_mcp_create_cube", {}).risk, "read_only")

    def test_bridge_status_is_loopback_by_default(self):
        status = connection_status()
        self.assertIn(status["state"], {"disconnected", "connecting", "connected", "stale", "failed"})
        self.assertIn(status["host"], {"127.0.0.1", "localhost", "::1"})
        self.assertEqual(int(status["port"]), 9876)

    def test_dry_run_config_is_read_without_network_or_execution(self):
        with patch("core.agent_orchestrator._load_config", return_value={"dry_run": True}):
            from core.agent_orchestrator import get_dry_run
            self.assertTrue(get_dry_run())


if __name__ == "__main__":
    unittest.main()
