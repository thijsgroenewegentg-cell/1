"""
Coder Agent - Writes code, autonomous like Devin
Uses coding agent loop but as part of team
"""

from .base import BaseAgent

CODER_PROMPT = """
You are CODER - an expert senior full-stack engineer in JARVIS multi-agent team.

Your expertise:
- Write clean, production-ready code
- Python, JS/TS, FastAPI, React, etc
- You get context from Researcher and Plan from Planner
- You focus on coding only, not planning or research
- You use tools: file_write, file_read, search_codebase, read_code_file, git_diff, git_status, run_tests, format_code, execute_python, shell_command

You are British, efficient, you write code that works first time.

When given todo:
- Read relevant files
- Understand context
- Write/edit files using file_write
- Format with format_code
- Run tests with run_tests
- If fail, fix yourself
- Return summary of what you did: files edited, tests result

Be concise in explanation, but thorough in code. No fluff.
"""

class CoderAgent(BaseAgent):
    def __init__(self, brain=None):
        super().__init__(
            name="Coder",
            role="Writes production code, implements features, fixes bugs",
            system_prompt=CODER_PROMPT,
            brain=brain
        )
    
    def code(self, todo: dict, main_task: str, context: str = "") -> str:
        """
        Implement a coding todo
        todo: {id, title, description, files, etc}
        """
        task_str = f"""Main project task: {main_task}

Your todo:
- Title: {todo.get('title')}
- Description: {todo.get('description')}
- Files hint: {todo.get('files', [])}
- Type: {todo.get('type', 'coding')}

Context from previous agents / research:
{context[:4000]}

Your job as Coder:
1. Search codebase for relevant files if needed (search_codebase)
2. Read current files (read_code_file)
3. Write/edit files (file_write) - full content, production-ready
4. Format (format_code)
5. Test if needed (run_tests)
6. Return summary

Implement now, Sir.
"""
        return self.think(task_str, context)
