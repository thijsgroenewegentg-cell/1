import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional


class ToolRegistry:
    """Tools the agent can call. These use sandbox capabilities."""

    def __init__(self):
        self.tools = {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "bash": self.bash,
            "list_dir": self.list_dir,
            "search_web": self.search_web,
            "evaluate_code": self.evaluate_code,
        }

    def list_available(self) -> list:
        return list(self.tools.keys())

    def call(self, name: str, **kwargs) -> Any:
        if name not in self.tools:
            return {"error": f"Unknown tool: {name}"}
        try:
            return self.tools[name](**kwargs)
        except Exception as e:
            return {"error": str(e)}

    def read_file(self, path: str) -> Dict:
        p = Path(path)
        if p.exists():
            return {"content": p.read_text(), "exists": True}
        return {"exists": False, "error": "File not found"}

    def write_file(self, path: str, content: str) -> Dict:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return {"written": True, "path": str(p.resolve())}

    def bash(self, command: str) -> Dict:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    def list_dir(self, path: str = ".") -> Dict:
        p = Path(path)
        if p.exists():
            return {"files": [str(f.name) for f in p.iterdir() if f.is_file()]}
        return {"error": "Path not found"}

    def search_web(self, query: str) -> Dict:
        # Note: Actual search requires an API key or external service.
        # This provides a template/search mechanism placeholder.
        return {
            "query": query,
            "note": "Web search requires external search API (Serper, SerpAPI, or similar). This is a placeholder response.",
            "suggestion": "Consider using bash 'curl' for direct HTTP requests, or integrate with a search API.",
        }

    def evaluate_code(self, code: str) -> Dict:
        # Simple syntax check only; execution is risky.
        try:
            compile(code, "<agent>", "exec")
            return {"valid_syntax": True, "message": "Syntax valid. Execution blocked for safety."}
        except SyntaxError as e:
            return {"valid_syntax": False, "message": str(e)}
