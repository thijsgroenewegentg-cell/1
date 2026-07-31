"""
Knowledge Tools - Second Brain - Document RAG - Search everything
JARVIS remembers everything, Sir.
100% free, local, no API keys
"""

from pathlib import Path
from typing import List

from ..config import config

# Lazy singletons
_doc_rag = None
_second_brain = None

def _get_doc_rag():
    global _doc_rag
    if _doc_rag is None:
        try:
            from ..knowledge import DocumentRAG
            _doc_rag = DocumentRAG()
        except Exception as e:
            print(f"DocumentRAG not available: {e}")
    return _doc_rag

def _get_second_brain():
    global _second_brain
    if _second_brain is None:
        try:
            from ..knowledge import SecondBrain
            _second_brain = SecondBrain()
        except Exception as e:
            print(f"SecondBrain not available: {e}")
    return _second_brain


def search_knowledge(query: str, max_results: int = 5) -> str:
    """
    Search knowledge base - PDFs, markdown, Notion, Obsidian, docs
    Second brain that remembers everything
    """
    try:
        rag = _get_doc_rag()
        if not rag:
            return "Knowledge RAG not available, Sir."
        
        results = rag.search(query, k=max_results)
        
        if not results:
            return f"No knowledge found for '{query}', Sir. Try indexing documents with index_documents or different query."
        
        output = [f"Found {len(results)} knowledge docs for '{query}', Sir:\n"]
        for i, r in enumerate(results, 1):
            fp = r.get("metadata", {}).get("file_path", "unknown")
            score = r.get("score", 0)
            text = r.get("text", "")[:600]
            output.append(f"\n--- {i}. {fp} (relevance: {score:.2f}) ---\n{text}...\n")
        
        return "\n".join(output)[:8000]
    except Exception as e:
        return f"Knowledge search failed: {e}"


def search_everything(query: str, max_results: int = 5) -> str:
    """
    Search everything - codebase + documents + learnings + memories + profile
    Unified second brain search
    """
    try:
        sb = _get_second_brain()
        if not sb:
            return "Second brain not available"
        
        results = sb.search_everything(query, k=max_results)
        
        output = [f"Searching everything for '{query}', Sir:\n"]
        
        if results.get("code"):
            output.append(f"\n📦 Codebase ({len(results['code'])} hits):")
            for r in results["code"][:2]:
                fp = r.get("metadata",{}).get("file_path","unknown")
                output.append(f"  - {fp} (score {r.get('score',0):.2f}): {r.get('text','')[:150]}...")
        
        if results.get("documents"):
            output.append(f"\n📚 Documents ({len(results['documents'])} hits):")
            for r in results["documents"][:2]:
                fp = r.get("metadata",{}).get("file_path","unknown")
                output.append(f"  - {fp} (score {r.get('score',0):.2f}): {r.get('text','')[:150]}...")
        
        if results.get("learnings"):
            output.append(f"\n🧠 Learnings ({len(results['learnings'])} hits):")
            for r in results["learnings"][:2]:
                output.append(f"  - {r.get('text','')[:150]}... (score {r.get('score',0):.2f})")
        
        if results.get("memories"):
            output.append(f"\n💾 Memories ({len(results['memories'])} hits):")
            for m in results["memories"][:2]:
                output.append(f"  - {m.get('key')}: {m.get('value','')[:100]}")
        
        if results.get("profile"):
            prof = results["profile"]
            output.append(f"\n👤 Profile: {prof.get('preferred_name') or prof.get('name')} - {len(prof.get('facts',[]))} facts")
        
        if len(output) == 1:
            return f"Nothing found for '{query}' across codebase, docs, memory, Sir. Try different query."
        
        return "\n".join(output)[:8000]
    except Exception as e:
        return f"Search everything failed: {e}"


def index_documents(path: str = None, force: bool = False) -> str:
    """
    Index documents for second brain
    PDFs, markdown, Notion export, Obsidian vault, etc
    """
    try:
        rag = _get_doc_rag()
        if not rag:
            return "Document RAG not available"
        
        if path:
            p = Path(path)
            if not p.exists():
                # Try relative to workspace
                p = config.WORKSPACE_DIR / path
            if not p.exists():
                return f"Path not found: {path}"
            
            if p.is_file():
                chunks = rag.index_file(p)
                rag._save_meta()
                rag.vector_store._save()
                return f"Indexed file {path}, Sir: {chunks} chunks, total vectors {len(rag.vector_store.vectors)}"
            else:
                result = rag.index_documents(root_path=p, force=force)
                return f"Indexed documents from {path}, Sir: {result['files_indexed']} files, {result['chunks']} chunks, total {result['total_vectors']} vectors"
        else:
            result = rag.index_documents(force=force)
            return f"Indexed all knowledge dirs, Sir: {result['files_indexed']} files, {result['chunks']} chunks, total {result['total_vectors']} vectors"
    
    except Exception as e:
        return f"Index documents failed: {e}"


def read_document(file_path: str) -> str:
    """
    Read document content - PDF, markdown, etc
    """
    try:
        rag = _get_doc_rag()
        if not rag:
            return "Document RAG not available"
        
        content = rag.get_document(file_path)
        return f"Document: {file_path}\n---\n{content[:8000]}"
    except Exception as e:
        return f"Read document failed: {e}"


def get_knowledge_overview() -> str:
    """Get overview of knowledge base - second brain stats"""
    try:
        from ..knowledge import SecondBrain
        sb = SecondBrain()
        overview = sb.get_overview()
        
        output = f"""Second Brain Overview, Sir:

Codebase: {overview.get('codebase',{}).get('total_files',0)} files, {overview.get('codebase',{}).get('total_vectors',0)} vectors
Documents: {overview.get('documents',{}).get('total_files',0)} files, {overview.get('documents',{}).get('total_vectors',0)} vectors
Learnings: {overview.get('learnings',0)} vectors
Memories: {overview.get('memories',0)} explicit remembers

Document types: {overview.get('documents',{}).get('types',{})}
Recent docs: {', '.join(overview.get('documents',{}).get('recent_files',[])[:3])}

Use search_everything to search across all, Sir.
"""
        return output
    except Exception as e:
        return f"Knowledge overview failed: {e}"
