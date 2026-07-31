"""
Git Tools - JARVIS has full git superpowers
Uses subprocess git + gh CLI if available
"""

import subprocess
import os
from pathlib import Path
from typing import Dict, List, Optional

from ..config import config


class GitTools:
    def __init__(self, repo_path: Path = None):
        self.repo_path = repo_path or config.MEMORY_FILE.parent.parent
        # Ensure it's a git repo
        self.is_git_repo = (self.repo_path / ".git").exists()
    
    def _run(self, cmd: str, timeout: int = 15) -> str:
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=timeout
            )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            if result.returncode != 0 and not output.strip():
                output = f"Command failed with code {result.returncode}"
            return output[:10000]  # limit
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout}s: {cmd}"
        except Exception as e:
            return f"Git error: {e}"
    
    def status(self) -> str:
        if not self.is_git_repo:
            return "Not a git repo, Sir."
        return self._run("git status --short --branch")
    
    def diff(self, file_path: str = None, staged: bool = False) -> str:
        if not self.is_git_repo:
            return "Not a git repo"
        if staged:
            cmd = "git diff --cached"
        elif file_path:
            cmd = f"git diff -- {file_path}"
        else:
            cmd = "git diff"
        return self._run(cmd)
    
    def diff_last_commit(self) -> str:
        return self._run("git diff HEAD~1 HEAD")
    
    def log(self, limit: int = 10, oneline: bool = True) -> str:
        if not self.is_git_repo:
            return "Not a git repo"
        if oneline:
            return self._run(f"git log --oneline -{limit}")
        else:
            return self._run(f"git log -{limit} --stat")
    
    def branch(self) -> str:
        if not self.is_git_repo:
            return "Not a git repo"
        return self._run("git branch -a")
    
    def add(self, files: str = ".") -> str:
        if not self.is_git_repo:
            return "Not a git repo"
        return self._run(f"git add {files}")
    
    def commit(self, message: str, files: str = None) -> str:
        if not self.is_git_repo:
            return "Not a git repo"
        if files:
            self._run(f"git add {files}")
        # Escape message
        safe_msg = message.replace('"', '\\"').replace('`', '\\`')
        return self._run(f'git commit -m "{safe_msg}"')
    
    def push(self, branch: str = None) -> str:
        if not self.is_git_repo:
            return "Not a git repo"
        if branch:
            return self._run(f"git push origin {branch}")
        else:
            return self._run("git push")
    
    def create_branch(self, branch_name: str) -> str:
        if not self.is_git_repo:
            return "Not a git repo"
        return self._run(f"git checkout -b {branch_name}")
    
    def checkout(self, branch: str) -> str:
        if not self.is_git_repo:
            return "Not a git repo"
        return self._run(f"git checkout {branch}")
    
    def blame(self, file_path: str) -> str:
        if not self.is_git_repo:
            return "Not a git repo"
        return self._run(f"git blame {file_path} | head -n 50")
    
    def show(self, commit: str = "HEAD") -> str:
        if not self.is_git_repo:
            return "Not a git repo"
        return self._run(f"git show {commit} --stat")
    
    def create_pr(self, title: str, body: str = "", base: str = "main") -> str:
        """Create PR using gh CLI if available"""
        try:
            # Check gh exists
            check = subprocess.run("gh --version", shell=True, capture_output=True, text=True, timeout=5)
            if check.returncode != 0:
                return "gh CLI not installed. Install with: https://cli.github.com/ - Can't create PR, Sir. But you can push and create manually."
            
            # Create PR
            safe_title = title.replace('"', '\\"').replace('`', '\\`')
            safe_body = body.replace('"', '\\"').replace('`', '\\`')[:1000]
            cmd = f'gh pr create --title "{safe_title}" --body "{safe_body}" --base {base}'
            return self._run(cmd, timeout=20)
        except Exception as e:
            return f"PR creation failed: {e}"
    
    def list_prs(self) -> str:
        try:
            return self._run("gh pr list --limit 10", timeout=10)
        except:
            return "gh not available"
    
    def get_current_branch(self) -> str:
        return self._run("git rev-parse --abbrev-ref HEAD").strip()
    
    def get_changed_files(self) -> List[str]:
        output = self._run("git diff --name-only HEAD")
        return [f.strip() for f in output.split("\n") if f.strip()]
    
    def stash(self, message: str = "") -> str:
        if message:
            return self._run(f'git stash push -m "{message}"')
        else:
            return self._run("git stash push")
    
    def reset_hard(self, commit: str = "HEAD") -> str:
        return self._run(f"git reset --hard {commit}")
