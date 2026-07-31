"""
Document RAG - Second Brain that indexes everything
PDFs, markdown, Notion export, Obsidian vault, text files, docs, etc
100% free, local, no API keys
"""

import os
import re
from pathlib import Path
from typing import List, Dict
import json
import hashlib
from datetime import datetime

from ..config import config
from ..learning.vector_store import VectorStore


# Supported extensions
DOC_EXTS = {
    '.pdf', '.md', '.txt', '.rst', '.json', '.yaml', '.yml', '.toml',
    '.docx', '.csv', '.html', '.htm', '.tex', '.org', '.log'
}

# Also index code as docs? No, codebase RAG does that, but we can include
# For second brain, we focus on knowledge docs

IGNORE_DIRS = {'node_modules', '.git', '__pycache__', 'venv', '.venv', 'dist', 'build', '.next', 'target', '.mypy_cache', '.pytest_cache', 'data'}

IGNORE_FILES = {'package-lock.json', 'yarn.lock'}


def is_document_file(path: Path) -> bool:
    if path.name in IGNORE_FILES:
        return False
    if path.suffix.lower() in DOC_EXTS:
        return True
    # Also markdown without extension? No
    return False


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from PDF - free via pypdf"""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        text = ""
        for page in reader.pages[:20]:  # limit 20 pages per PDF to avoid huge
            try:
                text += page.extract_text() + "\n"
            except:
                continue
        return text[:20000]  # limit
    except ImportError:
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(str(pdf_path))
            text = ""
            for page in reader.pages[:20]:
                text += page.extract_text() + "\n" if page.extract_text() else ""
            return text[:20000]
        except ImportError:
            return f"[PDF extraction requires pypdf - pip install pypdf] File: {pdf_path.name}"
    except Exception as e:
        return f"[PDF extract failed: {e}]"


def extract_text_from_docx(docx_path: Path) -> str:
    try:
        import docx
        doc = docx.Document(str(docx_path))
        text = "\n".join([p.text for p in doc.paragraphs])
        return text[:20000]
    except ImportError:
        return f"[DOCX extraction requires python-docx - pip install python-docx] File: {docx_path.name}"
    except Exception as e:
        return f"[DOCX extract failed: {e}]"


def chunk_text(content: str, file_path: str, chunk_size: int = 800, overlap: int = 150) -> List[Dict]:
    """Chunk text into overlapping pieces"""
    chunks = []
    # Clean
    content = content.strip()
    if not content:
        return []
    
    # Split by paragraphs first
    paragraphs = re.split(r'\n\s*\n', content)
    current = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) < chunk_size:
            current += "\n\n" + para if current else para
        else:
            if current:
                chunks.append(current)
            # If para itself is huge, split it
            if len(para) > chunk_size:
                for i in range(0, len(para), chunk_size - overlap):
                    chunks.append(para[i:i+chunk_size])
                current = ""
            else:
                current = para
    
    if current:
        chunks.append(current)
    
    # Add metadata
    result = []
    for idx, chunk in enumerate(chunks):
        if len(chunk.strip()) < 30:
            continue
        result.append({
            "text": chunk[:2000],
            "file_path": file_path,
            "chunk_id": idx,
            "hash": hashlib.md5(chunk.encode()).hexdigest()[:8]
        })
    return result


class DocumentRAG:
    def __init__(self, 
                 knowledge_dirs: List[Path] = None,
                 vector_path: Path = None):
        # Where to look for knowledge docs
        # Default: workspace/docs/, workspace/knowledge/, ~/Documents/Obsidian, ~/Notion export, etc
        self.knowledge_dirs = knowledge_dirs or [
            config.WORKSPACE_DIR / "docs",
            config.WORKSPACE_DIR / "knowledge",
            Path.home() / "Documents",
            Path.home() / "Obsidian",
            Path.home() / "Notion",
        ]
        
        self.vector_store = VectorStore(store_path=vector_path or config.MEMORY_FILE.parent / "knowledge_vectors.json")
        self.index_meta_path = config.MEMORY_FILE.parent / "knowledge_index_meta.json"
        self.index_meta = self._load_meta()
    
    def _load_meta(self) -> Dict:
        if self.index_meta_path.exists():
            try:
                return json.loads(self.index_meta_path.read_text())
            except:
                return {}
        return {}
    
    def _save_meta(self):
        try:
            self.index_meta_path.write_text(json.dumps(self.index_meta, indent=2))
        except:
            pass
    
    def should_reindex(self, file_path: Path) -> bool:
        try:
            mtime = file_path.stat().st_mtime
            key = str(file_path)
            old_mtime = self.index_meta.get(key, {}).get("mtime", 0)
            return mtime > old_mtime
        except:
            return True
    
    def _extract_text(self, file_path: Path) -> str:
        """Extract text from various document types"""
        ext = file_path.suffix.lower()
        try:
            if ext == '.pdf':
                return extract_text_from_pdf(file_path)
            elif ext == '.docx':
                return extract_text_from_docx(file_path)
            else:
                # For md, txt, etc, read directly
                if file_path.stat().st_size > 500_000:
                    return f"[File too large: {file_path.stat().st_size} bytes]"
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                return content[:20000]
        except Exception as e:
            return f"[Extract failed {file_path}: {e}]"
    
    def index_file(self, file_path: Path) -> int:
        """Index single document file"""
        try:
            if not file_path.exists() or not file_path.is_file():
                return 0
            if file_path.stat().st_size > 2_000_000:  # skip >2MB docs
                return 0
            
            content = self._extract_text(file_path)
            if not content or content.startswith("[") and "requires" in content:
                # If extraction requires library, still index the error message? Skip
                if "requires" in content and len(content) < 200:
                    return 0
            
            if not content.strip() or len(content.strip()) < 20:
                return 0
            
            rel_path = str(file_path)
            try:
                # Make relative to home or workspace if possible
                if file_path.is_relative_to(Path.home()):
                    rel_path = str(file_path.relative_to(Path.home()))
                elif file_path.is_relative_to(config.WORKSPACE_DIR):
                    rel_path = str(file_path.relative_to(config.WORKSPACE_DIR))
            except:
                pass
            
            # Delete old vectors for this file
            self.vector_store.vectors = [v for v in self.vector_store.vectors if v.get("metadata", {}).get("file_path") != rel_path]
            
            chunks = chunk_text(content, rel_path)
            for chunk in chunks:
                self.vector_store.add(
                    text=chunk["text"],
                    metadata={
                        "file_path": chunk["file_path"],
                        "chunk_id": chunk["chunk_id"],
                        "hash": chunk["hash"],
                        "type": "document",
                        "source": "knowledge",
                        "language": file_path.suffix.lstrip('.')
                    }
                )
            
            self.index_meta[str(file_path)] = {
                "mtime": file_path.stat().st_mtime,
                "chunks": len(chunks),
                "indexed_at": datetime.now().isoformat(),
                "rel_path": rel_path
            }
            
            return len(chunks)
        except Exception as e:
            print(f"Index doc file failed {file_path}: {e}")
            return 0
    
    def index_documents(self, root_path: Path = None, force: bool = False) -> Dict:
        """Index documents from root_path or default knowledge dirs"""
        print("📚 Indexing knowledge documents, Sir... (PDFs, markdown, Notion, Obsidian)")
        
        total_files = 0
        total_chunks = 0
        
        roots_to_scan = [Path(root_path)] if root_path else self.knowledge_dirs
        seen = set()
        
        for root in roots_to_scan:
            if not root or not root.exists():
                continue
            
            # Don't scan entire home Documents if it's huge? Limit depth?
            max_depth = 3 if str(root).startswith(str(Path.home())) else 10
            
            for dirpath, dirnames, filenames in os.walk(root):
                # Calculate depth
                try:
                    depth = len(Path(dirpath).relative_to(root).parts)
                    if depth > max_depth:
                        dirnames[:] = []
                        continue
                except:
                    pass
                
                # Filter ignored dirs
                dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith('.') and not d.startswith('_')]
                
                for fname in filenames:
                    fpath = Path(dirpath) / fname
                    fpath_str = str(fpath)
                    if fpath_str in seen:
                        continue
                    seen.add(fpath_str)
                    
                    if not is_document_file(fpath):
                        continue
                    
                    if not force and not self.should_reindex(fpath):
                        continue
                    
                    chunks = self.index_file(fpath)
                    if chunks > 0:
                        total_files += 1
                        total_chunks += chunks
        
        self._save_meta()
        self.vector_store._save()
        
        result = {"files_indexed": total_files, "chunks": total_chunks, "total_vectors": len(self.vector_store.vectors)}
        print(f"✓ Knowledge indexed: {total_files} files, {total_chunks} chunks, {len(self.vector_store.vectors)} vectors")
        return result
    
    def search(self, query: str, k: int = 5, file_pattern: str = None) -> List[Dict]:
        """Semantic search over knowledge docs"""
        try:
            results = self.vector_store.search(query, k=k*2, threshold=0.05)
            
            if file_pattern:
                pattern = file_pattern.lower()
                results = [r for r in results if pattern in r.get("metadata", {}).get("file_path", "").lower()]
            
            seen = set()
            deduped = []
            for r in results:
                fp = r.get("metadata", {}).get("file_path", "")
                cid = r.get("metadata", {}).get("chunk_id", 0)
                key = (fp, cid)
                if key not in seen:
                    seen.add(key)
                    deduped.append(r)
                if len(deduped) >= k:
                    break
            
            return deduped[:k]
        except Exception as e:
            print(f"Knowledge search failed: {e}")
            return []
    
    def get_document(self, file_path: str) -> str:
        """Get document content"""
        try:
            p = Path(file_path)
            if not p.is_absolute():
                # Try relative to knowledge dirs
                for kd in self.knowledge_dirs:
                    candidate = kd / file_path
                    if candidate.exists():
                        p = candidate
                        break
                else:
                    # Try workspace
                    candidate = config.WORKSPACE_DIR / file_path
                    if candidate.exists():
                        p = candidate
            
            if not p.exists():
                # Try direct
                p = Path(file_path)
                if not p.exists():
                    return f"Document not found: {file_path}"
            
            content = self._extract_text(p)
            return content[:15000]
        except Exception as e:
            return f"Error reading {file_path}: {e}"
    
    def get_overview(self) -> Dict:
        """Overview of knowledge base"""
        try:
            total = len(self.vector_store.vectors)
            files = len(self.index_meta)
            
            # File types
            type_count = {}
            for v in self.vector_store.vectors:
                lang = v.get("metadata", {}).get("language", "unknown")
                type_count[lang] = type_count.get(lang, 0) + 1
            
            # Recent files
            recent = sorted(self.index_meta.items(), key=lambda x: x[1].get("indexed_at",""), reverse=True)[:10]
            recent_files = [f"{Path(k).name} ({v.get('chunks',0)} chunks)" for k,v in recent]
            
            return {
                "total_files": files,
                "total_vectors": total,
                "types": type_count,
                "recent_files": recent_files,
                "knowledge_dirs": [str(d) for d in self.knowledge_dirs if d.exists()]
            }
        except Exception as e:
            return {"error": str(e), "total_files": len(self.index_meta)}
