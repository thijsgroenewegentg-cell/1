from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.approval_policy import assess_tool, canonical_profile
from core.blender_workflows import build_plan, render_plan
from core.evaluation import EvaluationCase, evaluate_trace
from core.task_planner import clear, create, update
from core.task_runtime import TaskRuntime
from core.tool_contracts import ToolResult, normalize_result
from memory.memory_manager import format_memory_for_prompt, search_memory_details


class ContractAndRuntimeTests(unittest.TestCase):
    def test_contract_exposes_change_verification_and_recovery(self):
        result = normalize_result("A file was written.", "file_controller", {"action": "write", "path": "notes.txt"})
        result.changed_items = ["notes.txt"]
        result.verification = {"reported": True}
        text = result.as_text()
        self.assertIn("changed_items=notes.txt", text)
        self.assertIn("verification=yes", text)

    def test_runtime_persists_operation_and_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = TaskRuntime(Path(directory) / "runtime.json")
            turn = runtime.begin_turn("test task")
            operation = runtime.begin_operation("inspect", {"query": "scene"})
            runtime.finish_operation(operation, ToolResult(True, "Inspected", tool="inspect", verification={"reported": True}))
            snapshot = runtime.snapshot()
            self.assertEqual(snapshot["current"]["id"], turn)
            self.assertEqual(snapshot["current"]["operations"][0]["status"], "completed")
            runtime.hold("paused")
            self.assertEqual(runtime.snapshot()["current"]["status"], "paused")
            runtime.resume()
            self.assertEqual(runtime.snapshot()["current"]["status"], "active")
            runtime.end_turn()
            self.assertIsNone(runtime.snapshot()["current"])


class PlannerMemoryAndPolicyTests(unittest.TestCase):
    def tearDown(self):
        clear()

    def test_planner_enforces_dependencies(self):
        plan = create("dependent", [{"text": "inspect", "depends_on": []}, {"text": "change", "depends_on": [1]}])
        with self.assertRaises(ValueError):
            update(2, "running")
        update(1, "done")
        update(2, "running")
        self.assertEqual(plan["steps"][1]["depends_on"], [1])

    def test_memory_prompt_keeps_preferences_scoped_and_hides_expired(self):
        fixture = {
            "identity": {},
            "preferences": {"style": {"value": "concise", "scope": "global", "source": "explicit_user", "confidence": "high"}},
            "temporary": {"old": {"value": "stale", "expires": "2000-01-01"}},
        }
        prompt = format_memory_for_prompt(fixture)
        self.assertIn("explicit user preferences", prompt.lower())
        self.assertIn("scope=global", prompt)
        self.assertNotIn("stale", prompt)

    def test_policy_and_blender_plan_are_conservative(self):
        self.assertEqual(canonical_profile("strict"), "always_confirm")
        self.assertEqual(canonical_profile("confirm_once"), "confirm_once_per_task")
        self.assertEqual(canonical_profile("balanced"), "safe_read_only")
        self.assertEqual(assess_tool("system_status", {}).risk, "read_only")
        self.assertNotEqual(assess_tool("blender_control", {"action": "render"}).risk, "read_only")
        plan = build_plan("cinematic preview")
        self.assertTrue(plan.confirmation_points)
        self.assertIn("Verification", render_plan(plan))


class EvaluationTests(unittest.TestCase):
    def test_hallucination_regression_and_forbidden_tool(self):
        self.assertFalse(normalize_result({"ok": False, "summary": "No changes were made"}).ok)
        case = EvaluationCase("safety", "safe", expected_tools=("inspect",), forbidden_tools=("shell",))
        self.assertFalse(evaluate_trace(case, [{"tool": "shell"}]).passed)


if __name__ == "__main__":
    unittest.main()
