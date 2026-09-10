"""Visible, interruptible task plans for multi-step MARK requests.

The planner is deliberately separate from tool execution. It records intent and
progress; every actual tool call still passes through MARK's normal policy and
confirmation gates. This keeps a plan useful without creating a second hidden
executor.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PLAN_PATH = BASE_DIR / "memory" / "active_plan.json"
_lock = threading.RLock()
_active: dict | None = None


def _load() -> dict | None:
    global _active
    if _active is not None:
        return dict(_active)
    try:
        data = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        _active = data if isinstance(data, dict) and data.get("steps") else None
    except Exception:
        _active = None
    return dict(_active) if _active else None


def _save(plan: dict | None) -> None:
    global _active
    _active = dict(plan) if plan else None
    if plan is None:
        try:
            PLAN_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        return
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PLAN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PLAN_PATH)


def create(title: str, steps: list[str], owner: str = "user") -> dict:
    clean = [str(step).strip() for step in steps if str(step).strip()]
    if not clean:
        raise ValueError("A plan needs at least one step.")
    if len(clean) > 12:
        raise ValueError("A plan is limited to 12 steps so it stays readable.")
    plan = {
        "id": uuid.uuid4().hex[:10],
        "title": str(title or "MARK task").strip()[:160],
        "owner": str(owner or "user")[:40],
        "created": datetime.now().isoformat(timespec="seconds"),
        "status": "active",
        "cursor": 0,
        "steps": [
            {"index": i + 1, "text": step, "status": "pending", "started": "", "finished": ""}
            for i, step in enumerate(clean)
        ],
    }
    with _lock:
        _save(plan)
    return dict(plan)


def current() -> dict | None:
    with _lock:
        plan = _load()
        return dict(plan) if plan else None


def update(index: int, status: str, note: str = "") -> dict | None:
    status = str(status or "pending").lower().strip()
    if status not in {"pending", "running", "done", "failed", "skipped", "confirmation"}:
        raise ValueError("Step status must be pending, running, done, failed, skipped or confirmation.")
    with _lock:
        plan = _load()
        if not plan:
            return None
        try:
            index = int(index)
        except (TypeError, ValueError):
            raise ValueError("Step index must be an integer.")
        step = next((s for s in plan["steps"] if s["index"] == index), None)
        if step is None:
            raise ValueError("That plan step does not exist.")
        now = datetime.now().isoformat(timespec="seconds")
        step["status"] = status
        if status == "running":
            step["started"] = step.get("started") or now
            plan["status"] = "active"
            plan["cursor"] = index
        elif status == "confirmation":
            plan["status"] = "waiting_confirmation"
            plan["cursor"] = index
            if note:
                step["note"] = str(note)[:500]
        elif status in {"done", "failed", "skipped"}:
            step["finished"] = now
            if status == "failed":
                plan["status"] = "failed"
            if note:
                step["note"] = str(note)[:500]
            pending = [s["index"] for s in plan["steps"] if s["status"] == "pending"]
            plan["cursor"] = pending[0] if pending else len(plan["steps"])
            if not pending and all(s["status"] in {"done", "skipped"} for s in plan["steps"]):
                plan["status"] = "completed"
        _save(plan)
        return dict(plan)


def pause() -> dict | None:
    with _lock:
        plan = _load()
        if plan and plan.get("status") not in {"completed", "cancelled"}:
            plan["status"] = "paused"
            _save(plan)
        return dict(plan) if plan else None


def resume() -> dict | None:
    with _lock:
        plan = _load()
        if plan and plan.get("status") in {"paused", "waiting_confirmation", "failed"}:
            plan["status"] = "active"
            _save(plan)
        return dict(plan) if plan else None


def rollback(index: int | None = None) -> dict | None:
    """Roll a checklist back; actual side effects require undo/checkpoint tools."""
    with _lock:
        plan = _load()
        if not plan:
            return None
        start = int(index or 1)
        for step in plan.get("steps", []):
            if step.get("index", 0) >= start:
                step["status"] = "pending"
                step.pop("note", None)
                step["started"] = ""
                step["finished"] = ""
        plan["status"] = "active"
        plan["cursor"] = start
        _save(plan)
        return dict(plan)


def cancel() -> dict | None:
    with _lock:
        plan = _load()
        if plan:
            plan["status"] = "cancelled"
            _save(plan)
        return dict(plan) if plan else None


def clear() -> None:
    with _lock:
        _save(None)


def render(plan: dict | None = None) -> str:
    plan = plan or current()
    if not plan:
        return "No active task plan."
    lines = [f"PLAN [{plan['status'].upper()}] {plan['title']}  ·  {plan['id']}"]
    for step in plan.get("steps", []):
        icon = {"pending": "○", "running": "▶", "done": "✓", "failed": "!", "skipped": "—", "confirmation": "?"}.get(step.get("status"), "○")
        note = f" — {step['note']}" if step.get("note") else ""
        lines.append(f"{icon} {step['index']}. {step['text']} [{step['status']}]" + note)
    return "\n".join(lines)
