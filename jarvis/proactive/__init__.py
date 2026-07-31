"""
Proactive Agent - JARVIS doesn't wait, he acts first
Morning briefing, git watcher, end-of-day summary, routine-based proactive suggestions
"""

from .proactive_engine import ProactiveEngine, get_proactive_engine
from .scheduler import ProactiveScheduler
from .briefing import BriefingGenerator
from .git_watcher import GitWatcher
from .notifier import Notifier
from .goals import GoalsTracker

__all__ = ["ProactiveEngine", "get_proactive_engine", "ProactiveScheduler", "BriefingGenerator", "GitWatcher", "Notifier", "GoalsTracker"]
