"""
Test Runner - JARVIS runs tests and self-fixes
"""

import subprocess
import os
from pathlib import Path
from typing import Dict

from ..config import config


class TestRunner:
    def __init__(self, workspace: Path = None):
        self.workspace = workspace or config.MEMORY_FILE.parent.parent
    
    def _run(self, cmd: str, timeout: int = 30) -> Dict:
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return {
                "success": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": result.stdout[:5000],
                "stderr": result.stderr[:5000],
                "combined": (result.stdout + "\n" + result.stderr)[:8000]
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "exit_code": -1, "stdout": "", "stderr": f"Timed out after {timeout}s", "combined": f"Timeout {timeout}s"}
        except Exception as e:
            return {"success": False, "exit_code": -1, "stdout": "", "stderr": str(e), "combined": str(e)}
    
    def detect_test_command(self) -> str:
        """Auto-detect test command from project"""
        root = self.workspace
        
        if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
            # Check pyproject for pytest
            try:
                content = (root / "pyproject.toml").read_text() if (root / "pyproject.toml").exists() else ""
                if "pytest" in content or (root / "tests").exists() or list(root.glob("test_*.py")) or list(root.glob("*_test.py")):
                    return "python -m pytest -v"
            except:
                pass
        
        if (root / "package.json").exists():
            try:
                import json
                pkg = json.loads((root / "package.json").read_text())
                if "test" in pkg.get("scripts", {}):
                    return "npm test"
                if "jest" in str(pkg):
                    return "npx jest"
            except:
                pass
        
        # Fallback: python -m py_compile
        return "python -m py_compile $(find . -name '*.py' | head -n 20)"
    
    def run_tests(self, command: str = None) -> Dict:
        cmd = command or self.detect_test_command()
        print(f"🧪 Running tests: {cmd}")
        result = self._run(cmd, timeout=60)
        
        # Quick analysis
        output = result["combined"].lower()
        if "passed" in output and "failed" not in output:
            result["summary"] = "All tests passed, Sir."
        elif "failed" in output:
            # Extract failure count
            import re
            match = re.search(r'(\d+) failed', output)
            if match:
                result["summary"] = f"{match.group(1)} tests failed, Sir. Needs fixing."
            else:
                result["summary"] = "Some tests failed, Sir."
        elif result["success"]:
            result["summary"] = "Command succeeded, Sir."
        else:
            result["summary"] = "Tests failed or command error, Sir."
        
        return result
    
    def run_file(self, file_path: str) -> Dict:
        """Run single file (for quick test)"""
        if file_path.endswith('.py'):
            return self._run(f"python {file_path}", timeout=15)
        elif file_path.endswith('.js'):
            return self._run(f"node {file_path}", timeout=15)
        else:
            return self._run(f"python -m py_compile {file_path}", timeout=10)
