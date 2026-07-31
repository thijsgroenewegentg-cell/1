"""
Git Watcher - JARVIS watches your repo and notifies proactively
Like real JARVIS watching Stark's lab
"""

import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional

from ..config import config


class GitWatcher:
    def __init__(self, repo_path: Path = None, on_change: Callable = None, poll_interval: int = 30):
        self.repo_path = repo_path or config.MEMORY_FILE.parent.parent
        self.on_change = on_change
        self.poll_interval = poll_interval
        
        self.is_watching = False
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        
        self.last_status = ""
        self.last_commit_hash = ""
        
        print(f"👀 GitWatcher init: {self.repo_path}, poll {poll_interval}s")
    
    def _get_git_status(self) -> str:
        try:
            import subprocess
            result = subprocess.run(
                "git status --porcelain",
                shell=True,
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.stdout.strip()
        except:
            return ""
    
    def _get_last_commit(self) -> str:
        try:
            import subprocess
            result = subprocess.run(
                "git rev-parse HEAD",
                shell=True,
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.stdout.strip()
        except:
            return ""
    
    def _get_failed_tests(self) -> Optional[str]:
        # Check if there's a recent test failure file or CI status
        # For now, simple: check if pytest last run failed? We can't know, so skip
        # Future: integrate with GitHub Actions API via gh cli
        return None
    
    def _watch_loop(self):
        print(f"👀 Git watcher started, Sir. Watching {self.repo_path}")
        
        # Initial state
        self.last_status = self._get_git_status()
        self.last_commit_hash = self._get_last_commit()
        
        while not self.stop_event.is_set():
            try:
                time.sleep(self.poll_interval)
                
                if self.stop_event.is_set():
                    break
                
                # Check for changes
                current_status = self._get_git_status()
                current_commit = self._get_last_commit()
                
                # Detect new commit
                if current_commit and current_commit != self.last_commit_hash:
                    print(f"👀 New commit detected: {current_commit[:8]}")
                    if self.on_change:
                        try:
                            self.on_change("new_commit", {
                                "old": self.last_commit_hash[:8],
                                "new": current_commit[:8],
                                "message": f"New commit {current_commit[:8]} detected, Sir."
                            })
                        except Exception as e:
                            print(f"Git watcher on_change failed: {e}")
                    self.last_commit_hash = current_commit
                    self.last_status = current_status
                    continue
                
                # Detect new unstaged changes after being clean
                if current_status != self.last_status:
                    # Only notify if significant change and previous was clean or different
                    if self.last_status == "" and current_status != "":
                        # New dirty state
                        changed_files = len(current_status.split("\n"))
                        if self.on_change and changed_files > 0:
                            try:
                                self.on_change("dirty", {
                                    "files": changed_files,
                                    "status": current_status[:500],
                                    "message": f"{changed_files} files changed, Sir. Working tree is dirty."
                                })
                            except Exception as e:
                                print(f"Git watcher on_change dirty failed: {e}")
                    elif self.last_status != "" and current_status == "":
                        # Became clean (maybe committed)
                        pass
                    
                    self.last_status = current_status
                
                # Check for CI failure via gh (optional)
                # This is expensive, so only every 5 minutes
                # Skipped for now
            
            except Exception as e:
                print(f"Git watcher loop error: {e}")
                time.sleep(5)
    
    def start(self):
        if self.is_watching:
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._watch_loop, daemon=True)
        self.thread.start()
        self.is_watching = True
        print("✓ Git watcher started, Sir. I'll watch your repo like a hawk.")
    
    def stop(self):
        if not self.is_watching:
            return
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.is_watching = False
        print("✓ Git watcher stopped")
    
    def check_now(self) -> dict:
        """Manual check now"""
        status = self._get_git_status()
        commit = self._get_last_commit()
        return {
            "status": status,
            "commit": commit,
            "is_dirty": len(status) > 0,
            "changed_files": len(status.split("\n")) if status else 0
        }
