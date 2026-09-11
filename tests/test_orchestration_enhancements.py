from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.authority import AuthorityEngine
from core.llm_client import parse_tool_calls, recover_tool_output
from core.task_runtime import TaskRuntime


class DurableTaskEnvelopeTests(unittest.TestCase):
    def test_clarification_survives_restart_and_resume_does_not_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            first = TaskRuntime(path)
            task_id = first.begin_task(
                "Create a Blender preview",
                request={"original_message": "Create a Blender preview", "intent": "preview"},
                language="en",
                task_type="multi_step",
            )
            operation = first.begin_operation("scene_summary")
            first.finish_operation(operation, {"ok": True, "summary": "Scene inspected"})
            first.request_clarification("Which camera should I use?", ["Active camera", "Camera 2"], first.conversation())

            restarted = TaskRuntime(path)
            snapshot = restarted.snapshot()["current"]
            self.assertEqual(snapshot["id"], task_id)
            self.assertEqual(snapshot["status"], "needs_input")
            self.assertEqual(snapshot["question"], "Which camera should I use?")
            self.assertEqual(len(snapshot["operations"]), 1)

            restarted.answer_clarification("Active camera")
            resumed = restarted.snapshot()["current"]
            self.assertEqual(resumed["status"], "active")
            self.assertEqual(len(resumed["operations"]), 1)
            self.assertEqual(resumed["resume_count"], 1)
            self.assertEqual(resumed["conversation"][-1]["content"], "Active camera")

    def test_running_task_is_reconciled_but_paused_task_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            running = TaskRuntime(path)
            running.begin_task("Running task")
            reconciled = TaskRuntime(path)
            self.assertIsNone(reconciled.snapshot()["current"])
            self.assertEqual(reconciled.snapshot(include_history=True)["history"][-1]["status"], "interrupted")

            pending = TaskRuntime(path)
            pending.begin_task("Approval task")
            pending_operation = pending.begin_operation("file_controller", risk="reversible_mutation", requires_confirmation=True)
            pending.finish_operation(pending_operation, "[CONFIRMATION_PENDING] review")
            pending.hold("waiting_confirmation")
            after_pending_restart = TaskRuntime(path)
            self.assertEqual(after_pending_restart.snapshot()["current"]["status"], "needs_input")
            self.assertEqual(after_pending_restart.snapshot()["current"]["operations"][0]["status"], "interrupted")

            paused = TaskRuntime(path)
            paused.begin_task("Paused task")
            paused.hold("paused")
            after_restart = TaskRuntime(path)
            self.assertEqual(after_restart.snapshot()["current"]["status"], "paused")


class AuthorityTests(unittest.TestCase):
    def test_emergency_gate_blocks_execution_and_keeps_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = AuthorityEngine(Path(directory) / "authority.json")
            authority.begin_task("task-1")
            mutation = authority.decide("file_controller", {"action": "write"}, task_id="task-1")
            self.assertTrue(mutation.requires_approval)
            self.assertEqual(mutation.execution_mode, "inline")
            external = authority.decide("send_message", {"action": "send"}, task_id="task-1")
            self.assertEqual(external.execution_mode, "deferred")
            authority.set_emergency("pause", "manual test", actor="test")
            blocked = authority.decide("file_controller", {"action": "write"}, task_id="task-1")
            self.assertFalse(blocked.allowed)
            self.assertEqual(blocked.execution_mode, "blocked")
            inspection = authority.decide("system_status", {}, task_id="task-1")
            self.assertTrue(inspection.allowed)
            authority.set_emergency("normal", "cleared", actor="test")
            self.assertTrue(authority.decide("file_controller", {"action": "write"}, task_id="task-1").allowed)
            self.assertGreaterEqual(len(authority.audit()), 3)

    def test_task_grant_only_covers_reversible_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = AuthorityEngine(Path(directory) / "authority.json")
            authority.grant_task("task-1", tool="file_controller")
            granted = authority.decide("file_controller", {"action": "write"}, task_id="task-1")
            self.assertFalse(granted.requires_approval)
            destructive = authority.decide("send_message", {"action": "send"}, task_id="task-1")
            self.assertTrue(destructive.requires_approval)


class ToolOutputRecoveryTests(unittest.TestCase):
    def test_json_and_slash_tool_calls_are_recovered_without_speaking_payload(self):
        names = ["system_status", "screen_process"]
        calls = parse_tool_calls('/system_status{"detail": {"full": true}}', names)
        self.assertEqual(calls[0]["function"]["name"], "system_status")
        nested = parse_tool_calls('{"tool_calls":[{"function":{"name":"screen_process","arguments":{}}}]}', names)
        self.assertEqual(nested[0]["function"]["name"], "screen_process")
        content, recovered = recover_tool_output(
            'I will inspect this now. {"name":"system_status","arguments":{}}', names
        )
        self.assertEqual(len(recovered), 1)
        self.assertEqual(content, "I will inspect this now.")
        self.assertNotIn("arguments", content)
        fenced, fenced_calls = recover_tool_output('```json\n{"name":"system_status","arguments":{}}\n```', names)
        self.assertEqual(fenced, "")
        self.assertEqual(len(fenced_calls), 1)


if __name__ == "__main__":
    unittest.main()
