"""
JARVIS Self-Learning System
- Vector memory with embeddings
- User profiling
- Auto memory extraction
- Self-reflection & adaptive personality
"""
from .engine import LearningEngine
from .user_profile import UserProfile
from .vector_store import VectorStore
from .auto_memory import AutoMemoryExtractor
from .reflection import ReflectionEngine

__all__ = ["LearningEngine", "UserProfile", "VectorStore", "AutoMemoryExtractor", "ReflectionEngine"]
