"""
J.A.R.V.I.S - Just A Rather Very Intelligent System
Ollama-powered local AI
"""
__version__ = "1.0.0"
__author__ = "Stark Industries"

from .brain import JarvisBrain
from .config import config
from .personality import JARVIS_SYSTEM_PROMPT

__all__ = ["JarvisBrain", "config", "JARVIS_SYSTEM_PROMPT"]
