"""
Goals Tools - Long-term goals, milestones, accountability
Proactive 2.0 - JARVIS holds you accountable, Sir.
"""

from ..config import config

# Lazy singleton
_goals_tracker = None

def _get_goals():
    global _goals_tracker
    if _goals_tracker is None:
        try:
            from ..proactive.goals import GoalsTracker
            _goals_tracker = GoalsTracker()
        except Exception as e:
            print(f"GoalsTracker not available: {e}")
    return _goals_tracker


def add_goal(goal: str, deadline: str = None, milestones: str = None) -> str:
    """
    Add long-term goal with optional deadline and milestones
    JARVIS will track and hold you accountable
    """
    try:
        tracker = _get_goals()
        if not tracker:
            return "Goals tracker not available"
        
        milestone_list = []
        if milestones:
            # Split by comma or newline
            if "," in milestones:
                milestone_list = [m.strip() for m in milestones.split(",") if m.strip()]
            elif "\n" in milestones:
                milestone_list = [m.strip() for m in milestones.split("\n") if m.strip()]
            else:
                milestone_list = [milestones.strip()]
        
        entry = tracker.add_goal(goal=goal, deadline=deadline, milestones=milestone_list)
        
        return f"Goal added, Sir (ID: {entry['id']}):\nGoal: {goal}\nDeadline: {deadline or 'none'}\nMilestones: {len(milestone_list)} - {', '.join(milestone_list[:3])}\nI'll track and hold you accountable, Sir."
    except Exception as e:
        return f"Add goal failed: {e}"


def list_goals(include_completed: bool = False) -> str:
    try:
        tracker = _get_goals()
        if not tracker:
            return "Goals tracker not available"
        
        goals = tracker.get_goals(include_completed=include_completed)
        
        if not goals:
            return "No goals yet, Sir. Add one with add_goal. What shall we aim for?"
        
        output = [f"Goals ({len(goals)} active), Sir:\n"]
        for g in goals[:10]:
            status = "✓" if g.get("completed") else f"{g.get('progress',0)}%"
            deadline = g.get("deadline","no deadline")
            milestones = g.get("milestones",[])
            done_m = sum(1 for m in milestones if m.get("completed"))
            output.append(f"\n- [{g['id']}] {status} {g['goal'][:80]} (Deadline: {deadline}, Progress: {g.get('progress',0)}%, {done_m}/{len(milestones)} milestones)")
        
        # Add accountability check
        check = tracker.check_goals()
        if check["overdue"]:
            output.append(f"\n\n⚠️ Overdue: {len(check['overdue'])} goals")
        if check["due_soon"]:
            output.append(f"\n⏰ Due soon (3 days): {len(check['due_soon'])} goals")
        
        return "\n".join(output)
    except Exception as e:
        return f"List goals failed: {e}"


def update_goal_progress(goal_id: int, progress: int, note: str = None) -> str:
    try:
        tracker = _get_goals()
        if not tracker:
            return "Goals tracker not available"
        
        entry = tracker.update_progress(goal_id=goal_id, progress=progress, note=note or "")
        
        if not entry:
            return f"Goal {goal_id} not found, Sir."
        
        return f"Goal updated, Sir:\nID: {goal_id}\nGoal: {entry['goal'][:80]}\nProgress: {progress}%\nCompleted: {entry.get('completed',False)}\nNote: {note or 'none'}"
    except Exception as e:
        return f"Update progress failed: {e}"


def complete_milestone(goal_id: int, milestone_id: int) -> str:
    try:
        tracker = _get_goals()
        if not tracker:
            return "Goals tracker not available"
        
        entry = tracker.complete_milestone(goal_id=goal_id, milestone_id=milestone_id)
        
        if not entry:
            return f"Goal {goal_id} or milestone {milestone_id} not found, Sir."
        
        done = sum(1 for m in entry.get("milestones",[]) if m.get("completed"))
        total = len(entry.get("milestones",[]))
        
        return f"Milestone completed, Sir:\nGoal: {entry['goal'][:80]}\nMilestone {milestone_id} done\nProgress: {done}/{total} ({entry.get('progress',0)}%)"
    except Exception as e:
        return f"Complete milestone failed: {e}"


def complete_goal(goal_id: int) -> str:
    try:
        tracker = _get_goals()
        if not tracker:
            return "Goals tracker not available"
        
        entry = tracker.complete_goal(goal_id=goal_id)
        
        if not entry:
            return f"Goal {goal_id} not found, Sir."
        
        return f"🎉 Goal completed, Sir! ID: {goal_id}\nGoal: {entry['goal']}\nCongratulations, Sir. What's next?"
    except Exception as e:
        return f"Complete goal failed: {e}"


def check_goals() -> str:
    """Check goals for accountability - overdue, due soon, stalled, on track"""
    try:
        tracker = _get_goals()
        if not tracker:
            return "Goals tracker not available"
        
        check = tracker.check_goals()
        accountability = tracker.generate_accountability_message()
        
        output = f"""Goals Check, Sir:

Total: {check['total']} | Active: {check['active']} | Completed: {len(check['completed'])}

Overdue ({len(check['overdue'])}):
{chr(10).join(['- ' + g['goal'][:80] + f" (deadline {g.get('deadline')})" for g in check['overdue'][:3]]) or 'None, good job Sir!'}

Due soon (3 days) ({len(check['due_soon'])}):
{chr(10).join(['- ' + g['goal'][:80] for g in check['due_soon'][:3]]) or 'None'}

Stalled (no update 7 days) ({len(check['stalled'])}):
{chr(10).join(['- ' + g['goal'][:80] for g in check['stalled'][:3]]) or 'None'}

On track ({len(check['on_track'])}):
{chr(10).join(['- ' + g['goal'][:80] + f" ({g.get('progress',0)}%)" for g in check['on_track'][:3]]) or 'None'}

Accountability: {accountability or 'All good, Sir. Keep it up!'}
"""
        return output
    except Exception as e:
        return f"Check goals failed: {e}"


def delete_goal(goal_id: int) -> str:
    try:
        tracker = _get_goals()
        if not tracker:
            return "Goals tracker not available"
        
        success = tracker.delete_goal(goal_id=goal_id)
        
        if success:
            return f"Goal {goal_id} deleted, Sir."
        else:
            return f"Goal {goal_id} not found, Sir."
    except Exception as e:
        return f"Delete goal failed: {e}"
