"""
Code Tools - Enhanced tools for coding agent
"""

from pathlib import Path
from typing import List

from ..config import config

# Lazy singletons
_rag = None
_git = None
_tester = None
_formatter = None

def _get_rag():
    global _rag
    if _rag is None:
        try:
            from ..coding import CodebaseRAG
            _rag = CodebaseRAG()
        except Exception as e:
            print(f"CodebaseRAG not available: {e}")
    return _rag

def _get_git():
    global _git
    if _git is None:
        try:
            from ..coding import GitTools
            _git = GitTools()
        except Exception as e:
            print(f"GitTools not available: {e}")
    return _git

def _get_tester():
    global _tester
    if _tester is None:
        try:
            from ..coding import TestRunner
            _tester = TestRunner()
        except Exception as e:
            print(f"TestRunner not available: {e}")
    return _tester

def _get_formatter():
    global _formatter
    if _formatter is None:
        try:
            from ..coding import CodeFormatter
            _formatter = CodeFormatter()
        except Exception as e:
            print(f"Formatter not available: {e}")
    return _formatter


def search_codebase(query: str, file_pattern: str = None, max_results: int = 5) -> str:
    """
    Semantic search over entire codebase
    JARVIS knows your repo - searches via embeddings
    """
    try:
        rag = _get_rag()
        if not rag:
            return "Codebase RAG not available, Sir."
        
        results = rag.search(query, k=max_results, file_pattern=file_pattern)
        
        if not results:
            return f"No results for '{query}' in codebase, Sir. Try different query or index with analyze_codebase."
        
        output = [f"Found {len(results)} relevant code snippets for '{query}', Sir:\n"]
        for i, r in enumerate(results, 1):
            fp = r.get("metadata", {}).get("file_path", "unknown")
            score = r.get("score", 0)
            text = r.get("text", "")[:800]
            output.append(f"\n--- Result {i}: {fp} (relevance: {score:.2f}) ---\n{text}\n")
        
        return "\n".join(output)[:8000]
    except Exception as e:
        return f"Codebase search failed: {e}"


def analyze_codebase(path: str = ".") -> str:
    """
    Analyze codebase overview - tech stack, structure, main files
    Auto-indexes if needed
    """
    try:
        rag = _get_rag()
        if not rag:
            return "RAG not available"
        
        # Trigger indexing if needed
        if len(rag.vector_store.vectors) < 10:
            rag.index_workspace(force=False)
        
        overview = rag.get_overview()
        
        output = f"""Codebase analysis, Sir:

Total files indexed: {overview.get('total_files', 0)}
Total vectors: {overview.get('total_vectors', 0)}
Languages: {overview.get('languages', {})}
Tech stack: {', '.join(overview.get('tech_stack', []))}
Structure:
{chr(10).join('- ' + s for s in overview.get('structure', [])[:20])}

Main files:
{chr(10).join('- ' + f for f in overview.get('main_files', [])[:15])}

Use search_codebase to dive deeper, Sir.
"""
        return output
    except Exception as e:
        return f"Analyze failed: {e}"


def git_status() -> str:
    try:
        git = _get_git()
        return git.status() if git else "Git not available"
    except Exception as e:
        return f"Git status failed: {e}"


def git_diff(file_path: str = None, staged: bool = False) -> str:
    try:
        git = _get_git()
        if not git:
            return "Git not available"
        return git.diff(file_path=file_path, staged=staged)
    except Exception as e:
        return f"Git diff failed: {e}"


def git_log(limit: int = 10) -> str:
    try:
        git = _get_git()
        return git.log(limit=limit) if git else "Git not available"
    except Exception as e:
        return f"Git log failed: {e}"


def git_commit(message: str, files: str = None) -> str:
    try:
        git = _get_git()
        if not git:
            return "Git not available"
        # Safety: don't commit if message empty
        if not message or len(message.strip()) < 5:
            return "Commit message too short, Sir."
        return git.commit(message, files=files)
    except Exception as e:
        return f"Git commit failed: {e}"


def git_branch() -> str:
    try:
        git = _get_git()
        return git.branch() if git else "Git not available"
    except Exception as e:
        return f"Git branch failed: {e}"


def run_tests(test_command: str = None) -> str:
    try:
        tester = _get_tester()
        if not tester:
            return "Test runner not available"
        result = tester.run_tests(command=test_command)
        output = f"""Test results, Sir:

Success: {result.get('success')}
Exit code: {result.get('exit_code')}
Summary: {result.get('summary')}

STDOUT (last 2000 chars):
{result.get('stdout','')[-2000:]}

STDERR (last 2000 chars):
{result.get('stderr','')[-2000:]}
"""
        return output[:6000]
    except Exception as e:
        return f"Test run failed: {e}"


def format_code(file_path: str) -> str:
    try:
        formatter = _get_formatter()
        if not formatter:
            return "Formatter not available"
        return formatter.format_file(file_path)
    except Exception as e:
        return f"Format failed: {e}"


def index_codebase(force: bool = False) -> str:
    try:
        rag = _get_rag()
        if not rag:
            return "RAG not available"
        result = rag.index_workspace(force=force)
        return f"Indexed, Sir: {result['files_indexed']} files, {result['chunks']} chunks, total {result['total_vectors']} vectors"
    except Exception as e:
        return f"Index failed: {e}"


def read_code_file(file_path: str) -> str:
    try:
        rag = _get_rag()
        if not rag:
            return "RAG not available"
        return rag.get_file_content(file_path)[:8000]
    except Exception as e:
        return f"Read failed: {e}"
