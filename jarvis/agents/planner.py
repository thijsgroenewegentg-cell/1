"""
Planner Agent - Breaks big tasks into small todos
Like a project manager, senior architect
"""

from .base import BaseAgent

PLANNER_PROMPT = """
You are PLANNER - a senior project manager and architect in JARVIS team.

Your job:
- Take big, vague tasks and break them into 3-7 small, actionable todos
- Each todo should have: id, title, description, files_hint, assigned_agent (coder, researcher, reviewer), type
- Order them logically: analysis first, then coding, then testing, then review
- Be precise, no fluff
- You don't code, you plan

You are part of JARVIS multi-agent team. You are British, concise, strategic.

Return JSON array of todos only, no other text, example:
[
  {"id": 1, "title": "Analyze existing auth", "description": "Search codebase for current auth", "files": ["jarvis/brain.py"], "agent": "researcher", "type": "analysis"},
  {"id": 2, "title": "Create JWT middleware", "description": "Implement JWT verification", "files": ["web/auth.py"], "agent": "coder", "type": "coding"}
]
"""

class PlannerAgent(BaseAgent):
    def __init__(self, brain=None):
        super().__init__(
            name="Planner",
            role="Plans complex tasks into todos, assigns to specialized agents",
            system_prompt=PLANNER_PROMPT,
            brain=brain
        )
    
    def plan(self, task: str, context: str = "") -> list:
        """
        Break task into todos using LLM, with agent assignment
        """
        try:
            # Use task planner from coding module for robust planning
            from ..coding import TaskPlanner
            planner = TaskPlanner()
            todos = planner.plan(task, {"context": context})
            
            # Enhance with agent assignment
            for todo in todos:
                ttype = todo.get("type", "coding")
                if ttype == "analysis":
                    todo["agent"] = "researcher"
                elif ttype == "coding":
                    todo["agent"] = "coder"
                elif ttype == "testing":
                    todo["agent"] = "coder"
                elif ttype == "review":
                    todo["agent"] = "reviewer"
                elif ttype == "research":
                    todo["agent"] = "researcher"
                else:
                    todo["agent"] = "coder"
            
            return todos
        except Exception as e:
            print(f"PlannerAgent failed, using fallback: {e}")
            # Fallback simple plan
            return [
                {"id": 1, "title": "Analyze task", "description": task[:100], "files": [], "agent": "researcher", "type": "analysis", "status": "pending"},
                {"id": 2, "title": "Implement", "description": task[:100], "files": [], "agent": "coder", "type": "coding", "status": "pending"},
                {"id": 3, "title": "Test & Review", "description": "Test and review implementation", "files": [], "agent": "reviewer", "type": "review", "status": "pending"},
            ]
