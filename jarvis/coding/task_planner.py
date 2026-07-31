"""
Task Planner - JARVIS breaks big coding tasks into small todos
Like a senior engineer planning sprint
"""

from typing import List, Dict
from ..config import config


class TaskPlanner:
    def __init__(self):
        pass
    
    def plan(self, task: str, codebase_overview: Dict = None) -> List[Dict]:
        """
        Break down task into todos using LLM
        Returns list of {id, title, description, status, files}
        """
        try:
            import requests
            import json
            
            overview_str = ""
            if codebase_overview:
                overview_str = f"Codebase: {json.dumps(codebase_overview)[:1000]}"
            
            prompt = f"""You are a senior engineer planning a coding task. Break it down into 3-7 small, actionable todos.

Task: "{task}"
{overview_str}

Return JSON array of todos, each with:
- id: 1,2,3...
- title: short title (3-6 words)
- description: 1 sentence what to do
- files: array of files likely to edit (guess)
- type: one of [analysis, coding, testing, docs, git]

Rules:
- First todo should be analysis/understanding codebase
- Middle todos are coding
- Second last is testing
- Last is git commit/pr if needed
- Keep todos small, 1 file or 1 feature each

Return ONLY JSON array, no other text.

Example for "Add JWT auth":
[
  {{"id": 1, "title": "Analyze existing auth", "description": "Search codebase for current auth implementation", "files": ["jarvis/brain.py"], "type": "analysis"}},
  {{"id": 2, "title": "Create JWT middleware", "description": "Implement JWT verification middleware", "files": ["web/auth.py"], "type": "coding"}},
  {{"id": 3, "title": "Write tests", "description": "Add unit tests for JWT", "files": ["tests/test_auth.py"], "type": "testing"}}
]

Now break down task above.

JSON:"""
            
            resp = requests.post(
                f"{config.OLLAMA_HOST}/api/generate",
                json={
                    "model": config.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.4, "num_predict": 800}
                },
                timeout=20
            )
            
            if resp.status_code == 200:
                result = resp.json().get("response", "[]")
                start = result.find("[")
                end = result.rfind("]") + 1
                if start != -1 and end != -1:
                    try:
                        todos = json.loads(result[start:end])
                        # Validate and add status
                        validated = []
                        for i, todo in enumerate(todos):
                            if isinstance(todo, dict) and "title" in todo:
                                validated.append({
                                    "id": todo.get("id", i+1),
                                    "title": todo.get("title", f"Task {i+1}"),
                                    "description": todo.get("description", ""),
                                    "files": todo.get("files", []),
                                    "type": todo.get("type", "coding"),
                                    "status": "pending"  # pending, in_progress, done, failed
                                })
                        if validated:
                            return validated
                    except Exception as e:
                        print(f"Planner JSON parse failed: {e}")
        
        except Exception as e:
            print(f"Task planner LLM failed: {e}")
        
        # Fallback: simple heuristic plan
        return self._fallback_plan(task)
    
    def _fallback_plan(self, task: str) -> List[Dict]:
        task_lower = task.lower()
        
        # Generic fallback
        todos = [
            {"id": 1, "title": "Analyze codebase", "description": f"Understand current code relevant to: {task[:80]}", "files": [], "type": "analysis", "status": "pending"},
        ]
        
        if "test" in task_lower:
            todos.append({"id": 2, "title": "Write tests", "description": f"Implement tests for: {task}", "files": ["tests/"], "type": "testing", "status": "pending"})
        elif "fix" in task_lower or "bug" in task_lower:
            todos.append({"id": 2, "title": "Reproduce issue", "description": "Find and reproduce the bug", "files": [], "type": "analysis", "status": "pending"})
            todos.append({"id": 3, "title": "Fix bug", "description": task[:100], "files": [], "type": "coding", "status": "pending"})
            todos.append({"id": 4, "title": "Verify fix", "description": "Run tests to confirm fix works", "files": [], "type": "testing", "status": "pending"})
        else:
            todos.append({"id": 2, "title": "Implement feature", "description": task[:120], "files": [], "type": "coding", "status": "pending"})
            todos.append({"id": 3, "title": "Test implementation", "description": "Run tests and manual verification", "files": [], "type": "testing", "status": "pending"})
        
        todos.append({"id": len(todos)+1, "title": "Commit changes", "description": "Git add, commit, and summary", "files": [], "type": "git", "status": "pending"})
        
        return todos
