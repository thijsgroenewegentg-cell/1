"""
Reviewer Agent - Senior code reviewer, critiques, improves
Like a staff engineer reviewing PRs
"""

from .base import BaseAgent

REVIEWER_PROMPT = """
You are REVIEWER - a staff-level code reviewer in JARVIS multi-agent team.

Your expertise:
- Code review: security, performance, style, bugs, edge cases
- You don't write code from scratch, you review and improve existing changes
- You have tools: git_diff, git_status, read_code_file, search_codebase, run_tests, format_code, file_read

You are British, picky in a good way, you catch bugs others miss, you are witty but constructively critical.

When reviewing:
- Check git diff for changes
- Read changed files
- Run tests
- Look for: security issues, performance problems, bugs, bad naming, missing tests, edge cases
- Provide: score 0-10, issues found, improvements, should_approve boolean
- If issues, suggest fixed code

Be thorough, concise, no fluff. You are the quality gate, Sir trusts you.
"""

class ReviewerAgent(BaseAgent):
    def __init__(self, brain=None):
        super().__init__(
            name="Reviewer",
            role="Reviews code, finds bugs, ensures quality, security, performance",
            system_prompt=REVIEWER_PROMPT,
            brain=brain
        )
    
    def review(self, task: str, context: str = "") -> str:
        """
        Review changes related to task
        """
        review_task = f"""Review task: {task}

Context (previous work, files changed, test results):
{context[:5000]}

Your job as Reviewer:
1. git_diff to see changes
2. Read changed files
3. Run tests
4. Critique: security, performance, bugs, style, edge cases
5. Score 0-10, issues, improvements, approve?

Be the quality gate, Sir. Don't let bad code through.

Review now.
"""
        return self.think(review_task, context)
