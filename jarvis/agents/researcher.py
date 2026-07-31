"""
Researcher Agent - Deep research, web search, docs, codebase analysis
Like Tony's research AI
"""

from .base import BaseAgent

RESEARCHER_PROMPT = """
You are RESEARCHER - a deep research specialist in JARVIS multi-agent team.

Your expertise:
- Web search, documentation reading, StackOverflow
- Codebase analysis via search_codebase and analyze_codebase
- Technical research: compare libraries, find best practices
- You don't write final code, you research and provide analysis, options, recommendations

You are British, thorough, concise, you love finding the best solution.

You have tools: search_web, search_codebase, analyze_codebase, read_code_file, search_docs (via search_web), file_read, shell_command

When given task, research deeply and return:
- Summary of findings
- Options with pros/cons
- Recommendation
- Relevant code snippets / docs links
- What files to edit for next agent (coder)

Be concise but thorough. No fluff.
"""

class ResearcherAgent(BaseAgent):
    def __init__(self, brain=None):
        super().__init__(
            name="Researcher",
            role="Deep research, web search, codebase analysis, finds best solutions",
            system_prompt=RESEARCHER_PROMPT,
            brain=brain
        )
    
    def research(self, task: str, context: str = "") -> str:
        """
        Deep research on task
        """
        # Enhance prompt for research
        full_task = f"""Research task: {task}

Context: {context[:2000]}

Your job as Researcher:
1. Search codebase for relevant files (use search_codebase tool)
2. Search web for best practices / libraries / docs (use search_web)
3. Analyze codebase overview (analyze_codebase)
4. Provide summary with:
   - What exists now
   - Best libraries / approaches with pros/cons
   - Recommendation
   - Files that need editing
   - Potential pitfalls

Research deeply, be the expert, Sir is counting on you.
"""
        return self.think(full_task, context)
