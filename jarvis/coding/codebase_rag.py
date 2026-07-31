"""
Codebase RAG - JARVIS knows your entire repo
Indexes workspace files into vector store for semantic code search
"""

import os
import re
from pathlib import Path
from typing import List, Dict
import json
import hashlib
from datetime import datetime

from ..config import config
from ..learning.vector_store import VectorStore, cosine_sim


# File patterns to index
CODE_EXTS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.java', '.go', '.rs', '.c', '.cpp', '.h', '.rb', '.php', '.swift', '.kt', '.cs', '.md', '.json', '.yaml', '.yml', '.toml', '.html', '.css', '.sh', '.sql'}

IGNORE_DIRS = {'node_modules', '.git', '__pycache__', 'venv', '.venv', 'dist', 'build', '.next', 'target', '.mypy_cache', '.pytest_cache', 'data', 'dist_electron'}

IGNORE_FILES = {'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', '.DS_Store'}


def is_code_file(path: Path) -> bool:
    if path.name in IGNORE_FILES:
        return False
    if path.suffix.lower() in CODE_EXTS:
        return True
    # Also index files without extension but with shebang? Skip
    return False


def chunk_code(content: str, file_path: str, chunk_size: int = 800, overlap: int = 100) -> List[Dict]:
    """Chunk code file into overlapping chunks, trying to respect function boundaries"""
    chunks = []
    
    # For Python, try to split by functions/classes
    if file_path.endswith('.py'):
        # Split by def/class
        parts = re.split(r'\n(?=def |class |async def )', content)
        current = ""
        for part in parts:
            if len(current) + len(part) < chunk_size:
                current += part + "\n"
            else:
                if current.strip():
                    chunks.append(current)
                current = part + "\n"
        if current.strip():
            chunks.append(current)
        if not chunks:
            chunks = [content]
    else:
        # Generic sliding window
        for i in range(0, len(content), chunk_size - overlap):
            chunk = content[i:i+chunk_size]
            if chunk.strip():
                chunks.append(chunk)
    
    # Add metadata
    result = []
    for idx, chunk in enumerate(chunks):
        if len(chunk.strip()) < 20:
            continue
        result.append({
            "text": chunk[:2000],  # limit
            "file_path": file_path,
            "chunk_id": idx,
            "hash": hashlib.md5(chunk.encode()).hexdigest()[:8]
        })
    return result


class CodebaseRAG:
    def __init__(self, workspace: Path = None, vector_path: Path = None):
        self.workspace = workspace or config.WORKSPACE_DIR
        # Also index project root for codebase understanding (except ignored dirs)
        self.project_root = config.MEMORY_FILE.parent.parent
        self.vector_store = VectorStore(store_path=vector_path or config.MEMORY_FILE.parent / "codebase_vectors.json")
        self.index_meta_path = config.MEMORY_FILE.parent / "codebase_index_meta.json"
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
            key = str(file_path.relative_to(self.project_root))
            old_mtime = self.index_meta.get(key, {}).get("mtime", 0)
            return mtime > old_mtime
        except:
            return True
    
    def index_file(self, file_path: Path) -> int:
        """Index single file, returns chunks added"""
        try:
            if not file_path.exists() or not file_path.is_file():
                return 0
            if file_path.stat().st_size > 200_000:  # skip huge files
                return 0
            
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            if not content.strip():
                return 0
            
            rel_path = str(file_path.relative_to(self.project_root))
            
            # Delete old vectors for this file
            self.vector_store.vectors = [v for v in self.vector_store.vectors if v.get("metadata", {}).get("file_path") != rel_path]
            
            chunks = chunk_code(content, rel_path)
            for chunk in chunks:
                self.vector_store.add(
                    text=chunk["text"],
                    metadata={
                        "file_path": chunk["file_path"],
                        "chunk_id": chunk["chunk_id"],
                        "hash": chunk["hash"],
                        "type": "code",
                        "language": file_path.suffix.lstrip('.')
                    }
                )
            
            # Update meta
            self.index_meta[rel_path] = {"mtime": file_path.stat().st_mtime, "chunks": len(chunks), "indexed_at": datetime.now().isoformat()}
            
            return len(chunks)
        except Exception as e:
            print(f"Index file failed {file_path}: {e}")
            return 0
    
    def index_workspace(self, force: bool = False) -> Dict:
        """Index entire workspace + project code (excluding ignored)"""
        print("🧠 Indexing codebase, Sir... This may take a moment.")
        total_files = 0
        total_chunks = 0
        
        # Walk project root and workspace
        roots_to_scan = [self.project_root, self.workspace]
        # Avoid duplicate if workspace inside project root
        seen = set()
        
        for root in roots_to_scan:
            if not root.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                # Filter ignored dirs
                dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith('.')]
                
                for fname in filenames:
                    fpath = Path(dirpath) / fname
                    rel = str(fpath.relative_to(self.project_root))
                    if rel in seen:
                        continue
                    seen.add(rel)
                    
                    if not is_code_file(fpath):
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
        print(f"✓ Codebase indexed: {total_files} files, {total_chunks} chunks, {len(self.vector_store.vectors)} vectors")
        return result
    
    def search(self, query: str, k: int = 5, file_pattern: str = None) -> List[Dict]:
        """Semantic search over codebase"""
        try:
            results = self.vector_store.search(query, k=k*2, threshold=0.05)  # get more, filter
            
            # Filter by file pattern if given
            if file_pattern:
                pattern = file_pattern.lower()
                results = [r for r in results if pattern in r.get("metadata", {}).get("file_path", "").lower()]
            
            # Deduplicate by file_path
            seen_files = set()
            deduped = []
            for r in results:
                fp = r.get("metadata", {}).get("file_path", "")
                # Allow multiple chunks per file but not too many
                key = (fp, r.get("metadata", {}).get("chunk_id", 0))
                if key not in seen_files or len(deduped) < k:
                    seen_files.add(key)
                    deduped.append(r)
                if len(deduped) >= k:
                    break
            
            return deduped[:k]
        except Exception as e:
            print(f"Codebase search failed: {e}")
            return []
    
    def get_overview(self) -> Dict:
        """Get codebase overview: file tree, tech stack, stats"""
        try:
            overview = {
                "total_files": len(self.index_meta),
                "total_vectors": len(self.vector_store.vectors),
                "languages": {},
                "structure": {},
                "main_files": [],
                "tech_stack": []
            }
            
            # Languages
            for meta in self.index_meta.values():
                # Infer from file path in meta keys
                pass
            
            # Actually count from vector store metadata
            lang_count = {}
            for v in self.vector_store.vectors:
                lang = v.get("metadata", {}).get("language", "unknown")
                lang_count[lang] = lang_count.get(lang, 0) + 1
            
            overview["languages"] = lang_count
            
            # File tree (top level)
            root = self.project_root
            structure = []
            try:
                for item in root.iterdir():
                    if item.name in IGNORE_DIRS or item.name.startswith('.'):
                        continue
                    if item.is_dir():
                        # Count code files in this dir
                        code_files = sum(1 for _ in item.rglob("*.py")) if item.exists() else 0
                        structure.append(f"{item.name}/ ({code_files} py files)")
                    else:
                        if is_code_file(item):
                            structure.append(item.name)
                overview["structure"] = structure[:20]
            except:
                overview["structure"] = list(self.index_meta.keys())[:20]
            
            # Tech stack from files
            tech = set()
            if (root / "requirements.txt").exists():
                tech.add("python + requirements.txt")
            if (root / "package.json").exists():
                tech.add("node + package.json")
            if (root / "pyproject.toml").exists():
                tech.add("pyproject.toml")
            if (root / "Dockerfile").exists():
                tech.add("docker")
            if (root / "docker-compose.yml").exists():
                tech.add("docker-compose")
            if any((root / d).exists() for d in ["jarvis", "web", "desktop"]):
                tech.add("jarvis-custom")
            
            overview["tech_stack"] = list(tech)
            overview["main_files"] = list(self.index_meta.keys())[:15]
            
            return overview
        except Exception as e:
            return {"error": str(e), "total_files": len(self.index_meta)}
    
    def get_file_content(self, file_path: str) -> str:
        """Get file content with safety check"""
        try:
            # Resolve safely inside project root or workspace
            requested = (self.project_root / file_path).resolve()
            # Allow if inside project root
            try:
                requested.relative_to(self.project_root.resolve())
            except ValueError:
                # Try workspace
                requested = (self.workspace / file_path).resolve()
                try:
                    requested.relative_to(self.workspace.resolve())
                except ValueError:
                    return f"Access denied: {file_path} outside workspace"
            
            if not requested.exists():
                return f"File not found: {file_path}"
            
            if requested.stat().st_size > 200_000:
                return f"File too large: {file_path} ({requested.stat().st_size} bytes)"
            
            content = requested.read_text(encoding="utf-8", errors="ignore")
            return content[:20000]  # limit
        except Exception as e:
            return f"Error reading {file_path}: {e}"
