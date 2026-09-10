"""Bounded, high-level Blender workflow plans.

These plans describe safe sequences; they do not run Blender calls. Execution
still happens through the existing advertised MCP tools, confirmation gate,
checkpoint policy and scene verification in plugins/blender_control.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowPlan:
    name: str
    goal: str
    steps: tuple[str, ...]
    confirmation_points: tuple[str, ...]
    verification: tuple[str, ...]


_PLANS = {
    "cinematic": WorkflowPlan(
        "cinematic",
        "Prepare a cinematic Blender scene",
        (
            "Inspect scene, camera, lights and render settings",
            "Propose camera framing and a bounded lighting adjustment",
            "Ask for confirmation before scene mutations",
            "Apply only the exact advertised Blender MCP operations",
            "Render a bounded preview",
            "Inspect the preview and compare it with the requested look",
        ),
        ("camera or lighting changes", "render or save"),
        ("scene snapshot after mutation", "preview or viewport screenshot"),
    ),
    "preview": WorkflowPlan(
        "preview",
        "Create and review a safe render preview",
        (
            "Inspect the active camera and render settings",
            "Ask for confirmation before rendering",
            "Render once using the configured local settings",
            "Inspect the returned image or one bounded viewport screenshot",
        ),
        ("render"),
        ("render result or viewport screenshot",),
    ),
    "inspect": WorkflowPlan(
        "inspect",
        "Inspect the current Blender scene",
        (
            "Read scene and object metadata",
            "Request a viewport screenshot when visual context is needed",
            "Report visible facts and uncertainty without changing the scene",
        ),
        (),
        ("scene metadata", "viewport screenshot when available"),
    ),
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def build_plan(goal: str = "", workflow: str = "") -> WorkflowPlan:
    value = _key(workflow or goal)
    if any(word in value for word in ("cinematic", "film", "dramatic", "lighting")):
        return _PLANS["cinematic"]
    if any(word in value for word in ("render", "preview", "image")):
        return _PLANS["preview"]
    return _PLANS["inspect"]


def render_plan(plan: WorkflowPlan) -> str:
    lines = [f"BLENDER WORKFLOW [{plan.name.upper()}] {plan.goal}"]
    for index, step in enumerate(plan.steps, 1):
        lines.append(f"{index}. {step}")
    if plan.confirmation_points:
        lines.append("Confirmation points: " + "; ".join(plan.confirmation_points))
    lines.append("Verification: " + "; ".join(plan.verification))
    lines.append("Safety: no arbitrary Python, shell or unrestricted MCP forwarding.")
    return "\n".join(lines)


def workflow_names() -> list[str]:
    return sorted(_PLANS)
