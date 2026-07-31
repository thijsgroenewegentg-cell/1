"""
Multi-Agent Team - JARVIS is not one AI, he's a team
Coder, Researcher, Reviewer, Planner, Supervisor
Like Stark's lab with multiple AIs collaborating
"""

from .base import BaseAgent
from .coder import CoderAgent
from .researcher import ResearcherAgent
from .reviewer import ReviewerAgent
from .planner import PlannerAgent
from .team import AgentTeam
from .supervisor import SupervisorAgent

__all__ = ["BaseAgent", "CoderAgent", "ResearcherAgent", "ReviewerAgent", "PlannerAgent", "AgentTeam", "SupervisorAgent"]
