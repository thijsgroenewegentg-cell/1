"""
J.A.R.V.I.S - Just A Rather Very Intelligent System
Ollama-powered local AI - Minimal + Self-Learning
"""
__version__ = "2.0.0"
__author__ = "Stark Industries"

from .brain import JarvisBrain
from .config import config
from .personality import JARVIS_SYSTEM_PROMPT

try:
    from .learning import LearningEngine
except ImportError:
    LearningEngine = None

__all__ = ["JarvisBrain", "config", "JARVIS_SYSTEM_PROMPT", "LearningEngine"]
