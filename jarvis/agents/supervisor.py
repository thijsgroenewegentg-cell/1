"""
Supervisor Agent - Decides which agent should do what, routes tasks
Like JARVIS himself supervising the team
"""

from typing import Dict
from .base import BaseAgent

SUPERVISOR_PROMPT = """
You are SUPERVISOR - you manage JARVIS multi-agent team.

Team:
- Planner: breaks big tasks into todos, assigns agents
- Researcher: deep research, web search, codebase analysis
- Coder: writes production code
- Reviewer: reviews, finds bugs, ensures quality

Your job:
- Understand user task
- Decide: is this simple (single agent) or complex (team)?
- If simple (e.g. "what time is it?", "read file"), answer directly or delegate to one agent
- If complex (e.g. "Add JWT auth", "Research and implement X"), call Planner to break down, then orchestrate team
- You are the router

You are British, decisive, efficient, you are JARVIS himself. You are calm and strategic.

You have access to all tools.

When given task, return JSON:
{
  "complexity": "simple" or "complex",
  "strategy": "direct" or "planner->researcher->coder->reviewer" etc,
  "reason": "why this strategy",
  "first_agent": "planner" or "coder" or "researcher" or "reviewer" or "none"
}

Return ONLY JSON, no other text.
"""

class SupervisorAgent(BaseAgent):
    def __init__(self, brain=None):
        super().__init__(
            name="Supervisor",
            role="Routes tasks to right agent(s), decides team strategy",
            system_prompt=SUPERVISOR_PROMPT,
            brain=brain
        )
    
    def route(self, task: str) -> Dict:
        """
        Decide routing for task
        Returns dict: complexity, strategy, first_agent, reason
        """
        # Simple heuristic first
        task_lower = task.lower()
        
        # Simple tasks - direct
        simple_keywords = ["what time", "weather", "remember", "recall", "list files", "read file", "what is", "who is", "search"]
        if any(kw in task_lower for kw in simple_keywords) and len(task.split()) < 15:
            return {
                "complexity": "simple",
                "strategy": "direct",
                "first_agent": "none",
                "reason": "Simple factual query, no need for team, Sir."
            }
        
        # Complex coding tasks - need team
        complex_keywords = ["implement", "add feature", "build", "create", "refactor", "fix bug", "research and implement", "add tests", "migrate", "integrate"]
        if any(kw in task_lower for kw in complex_keywords):
            return {
                "complexity": "complex",
                "strategy": "planner -> researcher -> coder -> reviewer",
                "first_agent": "planner",
                "reason": "Coding task requiring planning, research, implementation, review"
            }
        
        # Research tasks
        if "research" in task_lower or "compare" in task_lower or "best" in task_lower:
            return {
                "complexity": "complex",
                "strategy": "researcher -> planner -> coder",
                "first_agent": "researcher",
                "reason": "Research-heavy task, start with researcher"
            }
        
        # Code review
        if "review" in task_lower or "check" in task_lower and "code" in task_lower:
            return {
                "complexity": "simple",
                "strategy": "reviewer",
                "first_agent": "reviewer",
                "reason": "Review task, delegate to reviewer"
            }
        
        # Try LLM for ambiguous
        try:
            import json
            response = self.think(f"Task: {task}\nDecide routing, return JSON only.")
            # Try parse JSON
            start = response.find("{")
            end = response.rfind("}") + 1
            if start != -1 and end != -1:
                data = json.loads(response[start:end])
                if "complexity" in data and "first_agent" in data:
                    return data
        except Exception as e:
            print(f"Supervisor LLM routing failed: {e}")
        
        # Default: complex
        return {
            "complexity": "complex",
            "strategy": "planner -> coder -> reviewer",
            "first_agent": "planner",
            "reason": "Default to team for safety, Sir."
        }
