"""
Goals Tracker - JARVIS tracks long-term goals, milestones, accountability
Proactive 2.0 - He holds you accountable, Sir.

Like Stark's project management but for your life.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from ..config import config


class GoalsTracker:
    def __init__(self, goals_path: Path = None):
        self.goals_path = goals_path or config.MEMORY_FILE.parent / "goals.json"
        self.goals_path.parent.mkdir(parents=True, exist_ok=True)
        self.goals = self._load()
    
    def _load(self) -> List[Dict]:
        if self.goals_path.exists():
            try:
                data = json.loads(self.goals_path.read_text())
                return data if isinstance(data, list) else []
            except:
                return []
        return []
    
    def _save(self):
        try:
            self.goals_path.write_text(json.dumps(self.goals, indent=2))
        except Exception as e:
            print(f"Goals save failed: {e}")
    
    def add_goal(self, goal: str, deadline: str = None, milestones: List[str] = None) -> Dict:
        """
        Add long-term goal
        deadline: e.g. "2026-12-31" or "in 2 weeks" or "next month"
        milestones: list of sub-goals
        """
        # Parse deadline
        deadline_date = None
        if deadline:
            try:
                # Try parse YYYY-MM-DD
                if "-" in deadline and len(deadline) >= 8:
                    # Simple parse
                    import re
                    match = re.search(r'(\d{4})-(\d{2})-(\d{2})', deadline)
                    if match:
                        deadline_date = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
                    else:
                        # Try relative
                        now = datetime.now()
                        if "week" in deadline.lower():
                            weeks = 1
                            m = re.search(r'(\d+)\s*week', deadline.lower())
                            if m:
                                weeks = int(m.group(1))
                            deadline_date = (now + timedelta(weeks=weeks)).strftime("%Y-%m-%d")
                        elif "month" in deadline.lower():
                            months = 1
                            m = re.search(r'(\d+)\s*month', deadline.lower())
                            if m:
                                months = int(m.group(1))
                            deadline_date = (now + timedelta(days=30*months)).strftime("%Y-%m-%d")
                        elif "day" in deadline.lower():
                            days = 1
                            m = re.search(r'(\d+)\s*day', deadline.lower())
                            if m:
                                days = int(m.group(1))
                            deadline_date = (now + timedelta(days=days)).strftime("%Y-%m-%d")
                        else:
                            deadline_date = deadline
                else:
                    deadline_date = deadline
            except:
                deadline_date = deadline
        
        goal_entry = {
            "id": int(datetime.now().timestamp() * 1000),
            "goal": goal,
            "deadline": deadline_date,
            "milestones": [{"id": i+1, "title": m, "completed": False} for i, m in enumerate(milestones or [])],
            "progress": 0,  # 0-100
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "completed": False,
            "notes": []
        }
        
        self.goals.append(goal_entry)
        self._save()
        
        return goal_entry
    
    def get_goals(self, include_completed: bool = False) -> List[Dict]:
        if include_completed:
            return self.goals
        return [g for g in self.goals if not g.get("completed")]
    
    def get_goal(self, goal_id: int) -> Optional[Dict]:
        for g in self.goals:
            if g["id"] == goal_id:
                return g
        return None
    
    def update_progress(self, goal_id: int, progress: int, note: str = "") -> Optional[Dict]:
        """Update goal progress 0-100"""
        for g in self.goals:
            if g["id"] == goal_id:
                g["progress"] = max(0, min(100, progress))
                g["updated_at"] = datetime.now().isoformat()
                if note:
                    g["notes"].append({"timestamp": datetime.now().isoformat(), "note": note})
                if progress >= 100:
                    g["completed"] = True
                self._save()
                return g
        return None
    
    def complete_milestone(self, goal_id: int, milestone_id: int) -> Optional[Dict]:
        for g in self.goals:
            if g["id"] == goal_id:
                for m in g.get("milestones", []):
                    if m["id"] == milestone_id:
                        m["completed"] = True
                        # Update progress based on milestones
                        total = len(g["milestones"])
                        done = sum(1 for mm in g["milestones"] if mm["completed"])
                        if total > 0:
                            g["progress"] = int((done / total) * 100)
                        g["updated_at"] = datetime.now().isoformat()
                        self._save()
                        return g
        return None
    
    def add_note(self, goal_id: int, note: str) -> Optional[Dict]:
        for g in self.goals:
            if g["id"] == goal_id:
                g["notes"].append({"timestamp": datetime.now().isoformat(), "note": note})
                g["updated_at"] = datetime.now().isoformat()
                self._save()
                return g
        return None
    
    def complete_goal(self, goal_id: int) -> Optional[Dict]:
        return self.update_progress(goal_id, 100, "Completed, Sir!")
    
    def delete_goal(self, goal_id: int) -> bool:
        original_len = len(self.goals)
        self.goals = [g for g in self.goals if g["id"] != goal_id]
        self._save()
        return len(self.goals) < original_len
    
    def check_goals(self) -> Dict:
        """
        Check goals for accountability - which are overdue, due soon, stalled, etc
        Returns dict with categories
        """
        now = datetime.now()
        overdue = []
        due_soon = []  # due in 3 days
        stalled = []  # no update in 7 days
        on_track = []
        completed = [g for g in self.goals if g.get("completed")]
        
        for g in self.goals:
            if g.get("completed"):
                continue
            
            deadline_str = g.get("deadline")
            updated_str = g.get("updated_at")
            
            # Check overdue
            if deadline_str:
                try:
                    deadline_date = datetime.fromisoformat(deadline_str.replace("Z","").split("T")[0])
                    if deadline_date.date() < now.date():
                        overdue.append(g)
                        continue
                    elif (deadline_date - now).days <= 3:
                        due_soon.append(g)
                        continue
                except:
                    pass
            
            # Check stalled (no update in 7 days)
            try:
                updated = datetime.fromisoformat(g.get("updated_at",""))
                if (now - updated).days >= 7:
                    stalled.append(g)
                    continue
            except:
                pass
            
            # On track
            on_track.append(g)
        
        return {
            "overdue": overdue,
            "due_soon": due_soon,
            "stalled": stalled,
            "on_track": on_track,
            "completed": completed,
            "total": len(self.goals),
            "active": len([g for g in self.goals if not g.get("completed")])
        }
    
    def generate_accountability_message(self) -> Optional[str]:
        """Generate accountability message for proactive briefing"""
        check = self.check_goals()
        
        if check["total"] == 0:
            return None
        
        messages = []
        
        if check["overdue"]:
            messages.append(f"You have {len(check['overdue'])} overdue goals, Sir. Including: {', '.join([g['goal'][:50] for g in check['overdue'][:2]])}")
        
        if check["due_soon"]:
            messages.append(f"{len(check['due_soon'])} goals due soon: {', '.join([g['goal'][:50] for g in check['due_soon'][:2]])}")
        
        if check["stalled"]:
            messages.append(f"{len(check['stalled'])} goals stalled (no update in 7 days), Sir. Need attention.")
        
        if not messages and check["on_track"]:
            # Positive
            return None  # No need to nag if on track
        
        if messages:
            return " Accountability: " + " ".join(messages[:2])
        
        return None
    
    def get_summary_for_briefing(self) -> str:
        """Get summary for morning briefing"""
        check = self.check_goals()
        active = check["active"]
        if active == 0:
            return "No active goals, Sir. What shall we aim for today?"
        
        summary = f"{active} active goals. "
        
        if check["overdue"]:
            summary += f"{len(check['overdue'])} overdue. "
        if check["due_soon"]:
            summary += f"{len(check['due_soon'])} due soon. "
        
        # Most recent goal
        recent = sorted([g for g in self.goals if not g.get("completed")], key=lambda x: x.get("created_at",""), reverse=True)
        if recent:
            summary += f"Focus: {recent[0]['goal'][:80]} ({recent[0]['progress']}% done)"
        
        return summary
