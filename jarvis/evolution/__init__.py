"""
JARVIS Evolution - Self-Improving AI
- Self-critic, tool forger, self-editor, performance tracker
- JARVIS makes himself better automatically
"""
from .evolution_engine import EvolutionEngine
from .self_critic import SelfCritic
from .tool_forger import ToolForger
from .self_editor import SelfEditor
from .performance_tracker import PerformanceTracker

__all__ = ["EvolutionEngine", "SelfCritic", "ToolForger", "SelfEditor", "PerformanceTracker"]
