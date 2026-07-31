"""
Document Second Brain - JARVIS remembers everything
Indexes PDFs, markdown, Notion, Obsidian, Gmail, Slack, etc into vector store
Search everything: code + docs + memory + emails
"""

from .document_rag import DocumentRAG
from .second_brain import SecondBrain

__all__ = ["DocumentRAG", "SecondBrain"]
