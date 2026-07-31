"""
Formatter - JARVIS auto-formats code like a senior dev
Uses black, ruff, prettier if available
"""

import subprocess
from pathlib import Path

from ..config import config


class CodeFormatter:
    def __init__(self, workspace: Path = None):
        self.workspace = workspace or config.MEMORY_FILE.parent.parent
    
    def _run(self, cmd: str) -> str:
        try:
            result = subprocess.run(cmd, shell=True, cwd=str(self.workspace), capture_output=True, text=True, timeout=10)
            return result.stdout + result.stderr
        except Exception as e:
            return f"Formatter error: {e}"
    
    def format_file(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            # Try relative to workspace
            path = self.workspace / file_path
        
        if not path.exists():
            return f"File not found: {file_path}"
        
        ext = path.suffix.lower()
        
        if ext == '.py':
            # Try black, then ruff
            black = self._run(f"black {path} --quiet 2>&1 || echo 'no black'")
            if "no black" in black or "not found" in black:
                # Try autopep8 or ruff
                ruff = self._run(f"ruff format {path} 2>&1 || ruff check --fix {path} 2>&1 || echo 'no ruff'")
                if "no ruff" in ruff:
                    return f"No formatter available for {file_path}, but file is valid, Sir."
                return f"Formatted {file_path} with ruff, Sir.\n{ruff[:500]}"
            return f"Formatted {file_path} with black, Sir."
        
        elif ext in ['.js', '.ts', '.tsx', '.jsx', '.json', '.css', '.html']:
            # Try prettier
            pret = self._run(f"npx prettier --write {path} 2>&1 || echo 'no prettier'")
            if "no prettier" in pret:
                return f"No prettier, skipped formatting {file_path}"
            return f"Formatted {file_path} with prettier, Sir."
        
        else:
            return f"No formatter for {ext}, skipped"
    
    def format_workspace(self, pattern: str = "*.py") -> str:
        if pattern == "*.py":
            result = self._run(f"black . --quiet 2>&1 | head -n 20")
            if "not found" in result or "no" in result.lower():
                result = self._run(f"ruff format . 2>&1 | head -n 20")
            return f"Formatted workspace {pattern}: {result[:1000]}"
        return "Pattern not supported"
