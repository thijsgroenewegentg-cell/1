"""
Second Brain - Unified search across everything
Codebase + Documents + Memory + Learnings + User Profile
JARVIS remembers everything, Sir.
"""

from typing import List, Dict
from pathlib import Path

from ..config import config
from .document_rag import DocumentRAG


class SecondBrain:
    def __init__(self):
        # Lazy load RAGs to avoid circular imports
        self._codebase_rag = None
        self._document_rag = None
        self._vector_store = None  # learning vectors
        self._memory_manager = None
    
    def _get_codebase_rag(self):
        if self._codebase_rag is None:
            try:
                from ..coding import CodebaseRAG
                self._codebase_rag = CodebaseRAG()
            except Exception as e:
                print(f"Codebase RAG not available for second brain: {e}")
        return self._codebase_rag
    
    def _get_document_rag(self):
        if self._document_rag is None:
            try:
                self._document_rag = DocumentRAG()
            except Exception as e:
                print(f"Document RAG not available: {e}")
        return self._document_rag
    
    def _get_learning_store(self):
        if self._vector_store is None:
            try:
                from ..learning import VectorStore
                self._vector_store = VectorStore()
            except:
                pass
        return self._vector_store
    
    def _get_memory(self):
        if self._memory_manager is None:
            try:
                from ..memory import MemoryManager
                self._memory_manager = MemoryManager()
            except:
                pass
        return self._memory_manager
    
    def search_everything(self, query: str, k: int = 5, include_code: bool = True, include_docs: bool = True, include_memory: bool = True) -> Dict:
        """
        Search across all brains:
        - Codebase
        - Documents (PDFs, markdown, Notion, Obsidian)
        - Memory (learnings, facts)
        - User profile
        
        Returns dict with results per category
        """
        results = {
            "query": query,
            "code": [],
            "documents": [],
            "learnings": [],
            "memories": [],
            "profile": None
        }
        
        # Codebase
        if include_code:
            try:
                rag = self._get_codebase_rag()
                if rag:
                    results["code"] = rag.search(query, k=k)
            except Exception as e:
                print(f"Code search failed: {e}")
        
        # Documents
        if include_docs:
            try:
                doc_rag = self._get_document_rag()
                if doc_rag:
                    results["documents"] = doc_rag.search(query, k=k)
            except Exception as e:
                print(f"Doc search failed: {e}")
        
        # Learnings (vector store from learning)
        if include_memory:
            try:
                vs = self._get_learning_store()
                if vs:
                    results["learnings"] = vs.search(query, k=k, threshold=0.05)
            except Exception as e:
                print(f"Learning search failed: {e}")
            
            # Old memory manager keyword search
            try:
                mm = self._get_memory()
                if mm:
                    # mm.search_memory is keyword, but we can try
                    from ..learning import MemoryManager
                    # Use its search if available, else get all and filter
                    mems = mm.get_all_memories()
                    query_lower = query.lower()
                    matched = []
                    for m in mems:
                        if query_lower in m.get("key","").lower() or query_lower in m.get("value","").lower():
                            matched.append(m)
                    results["memories"] = matched[:k]
            except Exception as e:
                print(f"Memory search failed: {e}")
        
        # Profile summary if query is about user
        if any(word in query.lower() for word in ["who am i", "what do you know about me", "my name", "about me", "profile"]):
            try:
                from ..learning import UserProfile
                up = UserProfile()
                results["profile"] = up.get()
            except:
                pass
        
        return results
    
    def search_knowledge(self, query: str, k: int = 5) -> List[Dict]:
        """Search only knowledge docs"""
        try:
            doc_rag = self._get_document_rag()
            if doc_rag:
                return doc_rag.search(query, k=k)
            return []
        except Exception as e:
            print(f"Knowledge search failed: {e}")
            return []
    
    def get_unified_context(self, query: str, k_per_category: int = 3) -> str:
        """
        Get unified context string for LLM injection
        Combines top results from all categories into one context block
        """
        results = self.search_everything(query, k=k_per_category)
        
        parts = []
        
        if results["code"]:
            code_str = "\n".join([f"- {r.get('metadata',{}).get('file_path')}: {r.get('text','')[:300]}..." for r in results["code"][:k_per_category]])
            parts.append(f"Codebase (relevant code):\n{code_str}")
        
        if results["documents"]:
            doc_str = "\n".join([f"- {r.get('metadata',{}).get('file_path')}: {r.get('text','')[:300]}..." for r in results["documents"][:k_per_category]])
            parts.append(f"Documents (knowledge base):\n{doc_str}")
        
        if results["learnings"]:
            learn_str = "\n".join([f"- {r.get('text','')[:200]} (score: {r.get('score',0):.2f})" for r in results["learnings"][:k_per_category]])
            parts.append(f"Learnings (past interactions):\n{learn_str}")
        
        if results["memories"]:
            mem_str = "\n".join([f"- {m.get('key')}: {m.get('value')}" for m in results["memories"][:k_per_category]])
            parts.append(f"Memories (explicit remembers):\n{mem_str}")
        
        if results["profile"]:
            prof = results["profile"]
            prof_str = f"Name: {prof.get('preferred_name') or prof.get('name')}, Facts: {len(prof.get('facts',[]))}, Interests: {prof.get('preferences',{}).get('topics_of_interest',[])[:5]}"
            parts.append(f"User Profile:\n{prof_str}")
        
        if not parts:
            return ""
        
        return "\n\n".join(parts)
    
    def index_all(self, force: bool = False) -> Dict:
        """Index both codebase and documents"""
        results = {}
        
        try:
            from ..coding import CodebaseRAG
            rag = CodebaseRAG()
            results["codebase"] = rag.index_workspace(force=force)
        except Exception as e:
            results["codebase"] = {"error": str(e)}
        
        try:
            doc_rag = self._get_document_rag()
            if doc_rag:
                results["documents"] = doc_rag.index_documents(force=force)
        except Exception as e:
            results["documents"] = {"error": str(e)}
        
        return results
    
    def get_overview(self) -> Dict:
        """Overview of entire second brain"""
        overview = {
            "codebase": {},
            "documents": {},
            "learnings": 0,
            "memories": 0
        }
        
        try:
            from ..coding import CodebaseRAG
            rag = CodebaseRAG()
            overview["codebase"] = rag.get_overview()
        except:
            pass
        
        try:
            doc_rag = self._get_document_rag()
            if doc_rag:
                overview["documents"] = doc_rag.get_overview()
        except:
            pass
        
        try:
            vs = self._get_learning_store()
            if vs:
                overview["learnings"] = len(vs.vectors)
        except:
            pass
        
        try:
            mm = self._get_memory()
            if mm:
                overview["memories"] = len(mm.get_all_memories())
        except:
            pass
        
        return overview
