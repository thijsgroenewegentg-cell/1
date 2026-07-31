"""
Proactive Agent - JARVIS doesn't wait, he acts first
Morning briefing, git watcher, end-of-day summary, routine-based proactive suggestions
"""

from .proactive_engine import ProactiveEngine
from .scheduler import ProactiveScheduler
from .briefing import BriefingGenerator
from .git_watcher import GitWatcher
from .notifier import Notifier

__all__ = ["ProactiveEngine", "ProactiveScheduler", "BriefingGenerator", "GitWatcher", "Notifier"]
