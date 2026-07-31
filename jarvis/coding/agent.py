"""
Coding Agent - Autonomous 10x Engineer
JARVIS plans, codes, tests, fixes, commits for hours

This is the Devin-like loop:
  Task → Plan → Todos → For each todo: Context (RAG) → Code → Format → Test → Self-Fix → Done → Git commit

Uses JarvisBrain for reasoning, CodebaseRAG for context, GitTools for git superpowers
"""

import time
import json
from pathlib import Path
from typing import List, Dict, Generator, Optional
from datetime import datetime

from ..config import config
from ..brain import JarvisBrain
from .codebase_rag import CodebaseRAG
from .git_tools import GitTools
from .task_planner import TaskPlanner
from .test_runner import TestRunner
from .formatter import CodeFormatter


class CodingAgent:
    def __init__(self, workspace: Path = None, brain: JarvisBrain = None):
        self.workspace = workspace or config.WORKSPACE_DIR
        self.project_root = config.MEMORY_FILE.parent.parent
        self.brain = brain or JarvisBrain(enable_learning=True, enable_evolution=True)
        
        self.rag = CodebaseRAG(workspace=self.workspace)
        self.git = GitTools(repo_path=self.project_root)
        self.planner = TaskPlanner()
        self.tester = TestRunner(workspace=self.project_root)
        self.formatter = CodeFormatter(workspace=self.project_root)
        
        self.current_task = None
        self.todos = []
        self.events = []  # history of events for UI
        
        # Ensure workspace indexed
        try:
            # Quick index if not indexed recently
            self.rag.index_workspace(force=False)
        except Exception as e:
            print(f"Initial indexing failed: {e}")
    
    def _emit(self, event_type: str, data: Dict) -> Dict:
        event = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        self.events.append(event)
        return event
    
    def plan(self, task: str) -> List[Dict]:
        """Plan task into todos"""
        overview = self.rag.get_overview()
        todos = self.planner.plan(task, overview)
        self.todos = todos
        self.current_task = task
        return todos
    
    def execute(self, task: str) -> Generator[Dict, None, Dict]:
        """
        Main autonomous execution - generator yielding events
        Yields: {type, data} where type in [plan, todo_start, todo_progress, file_edit, test_result, todo_done, error, done]
        Returns final summary dict
        """
        start_time = time.time()
        
        yield self._emit("start", {"task": task, "message": f"Starting task: {task}, Sir."})
        
        # 1. Plan
        yield self._emit("status", {"message": "Planning task, Sir..."})
        todos = self.plan(task)
        yield self._emit("plan", {"todos": todos, "message": f"Planned {len(todos)} steps, Sir."})
        
        # 2. For each todo
        completed = 0
        failed = 0
        
        for todo in todos:
            todo_id = todo["id"]
            todo["status"] = "in_progress"
            yield self._emit("todo_start", {"todo": todo, "message": f"Starting {todo['title']}, Sir."})
            
            try:
                result = self._execute_todo(todo, task, todos)
                
                if result.get("success"):
                    todo["status"] = "done"
                    completed += 1
                    yield self._emit("todo_done", {"todo": todo, "result": result, "message": f"✓ {todo['title']} done, Sir."})
                else:
                    todo["status"] = "failed"
                    failed += 1
                    yield self._emit("todo_failed", {"todo": todo, "result": result, "message": f"✗ {todo['title']} failed, Sir: {result.get('error','')[:200]}"})
                    
                    # If analysis todo fails, continue, else ask? For now continue
                    if todo["type"] == "analysis":
                        continue
                    # For coding todo failure, try self-fix loop once
                    if todo["type"] == "coding" and result.get("can_retry"):
                        yield self._emit("status", {"message": f"Attempting self-fix for {todo['title']}, Sir..."})
                        fix_result = self._self_fix_todo(todo, result, task)
                        if fix_result.get("success"):
                            todo["status"] = "done"
                            completed += 1
                            failed -= 1
                            yield self._emit("todo_done", {"todo": todo, "result": fix_result, "message": f"✓ {todo['title']} fixed and done, Sir."})
            
            except Exception as e:
                todo["status"] = "failed"
                failed += 1
                yield self._emit("error", {"todo": todo, "error": str(e), "message": f"Error in {todo['title']}: {e}"})
        
        # 3. Final tests
        yield self._emit("status", {"message": "Running final verification, Sir..."})
        test_result = self.tester.run_tests()
        yield self._emit("test_result", {"result": test_result, "message": test_result.get("summary", "Tests completed")})
        
        # 4. Git commit if changes
        git_status = self.git.status()
        has_changes = "modified:" in git_status or "new file:" in git_status or "deleted:" in git_status or "Untracked files" in git_status
        
        if has_changes and completed > 0:
            yield self._emit("status", {"message": "Committing changes, Sir..."})
            # Add all? For safety, only add workspace and relevant files
            # Check if we should commit
            commit_msg = f"feat: {task[:80]} - JARVIS Agent\n\nTodos: {completed} done, {failed} failed\nTask: {task}\nCo-authored-by: JARVIS <jarvis@local>"
            commit_result = self.git.commit(commit_msg)
            yield self._emit("git_commit", {"result": commit_result, "message": f"Committed, Sir."})
            
            # Optional push? Ask first? For now don't auto-push, just show status
            yield self._emit("status", {"message": "Ready to push. Use git push or create PR, Sir."})
        
        elapsed = int(time.time() - start_time)
        summary = {
            "task": task,
            "todos_total": len(todos),
            "completed": completed,
            "failed": failed,
            "elapsed_seconds": elapsed,
            "has_changes": has_changes,
            "test_success": test_result.get("success", False),
            "message": f"Agent finished, Sir. {completed}/{len(todos)} todos done in {elapsed}s. {'All tests passed' if test_result.get('success') else 'Some tests need attention'}."
        }
        
        yield self._emit("done", summary)
        return summary
    
    def _execute_todo(self, todo: Dict, main_task: str, all_todos: List[Dict]) -> Dict:
        """Execute single todo"""
        ttype = todo.get("type", "coding")
        title = todo.get("title", "")
        desc = todo.get("description", "")
        files_hint = todo.get("files", [])
        
        try:
            if ttype == "analysis":
                return self._do_analysis_todo(todo, main_task)
            elif ttype == "coding":
                return self._do_coding_todo(todo, main_task, files_hint)
            elif ttype == "testing":
                return self._do_testing_todo(todo, main_task)
            elif ttype == "git":
                return self._do_git_todo(todo, main_task)
            elif ttype == "docs":
                return self._do_docs_todo(todo, main_task)
            else:
                return self._do_coding_todo(todo, main_task, files_hint)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e), "can_retry": True}
    
    def _do_analysis_todo(self, todo: Dict, main_task: str) -> Dict:
        """Analyze codebase relevant to task"""
        try:
            # Search codebase for relevant files
            queries = [
                main_task,
                todo.get("description", ""),
                " ".join(todo.get("files", []))
            ]
            results = []
            for q in queries:
                if q and len(q) > 3:
                    search_res = self.rag.search(q, k=3)
                    results.extend(search_res)
            
            # Deduplicate
            seen = set()
            unique = []
            for r in results:
                fp = r.get("metadata", {}).get("file_path", "")
                if fp not in seen:
                    seen.add(fp)
                    unique.append(r)
            
            # Get overview
            overview = self.rag.get_overview()
            
            analysis = {
                "overview": overview,
                "relevant_files": [{"file": r.get("metadata", {}).get("file_path"), "score": r.get("score"), "preview": r.get("text", "")[:500]} for r in unique[:5]],
                "git_status": self.git.status()[:1000],
                "git_branch": self.git.get_current_branch()
            }
            
            return {"success": True, "analysis": analysis, "message": f"Analyzed codebase, found {len(unique)} relevant files, Sir."}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _do_coding_todo(self, todo: Dict, main_task: str, files_hint: List[str]) -> Dict:
        """Implement coding todo - uses brain to generate code"""
        try:
            # Gather context via RAG
            context_files = []
            search_query = f"{main_task} {todo.get('description','')} {' '.join(files_hint)}"
            rag_results = self.rag.search(search_query, k=5)
            
            context_str = ""
            for r in rag_results[:3]:
                fp = r.get("metadata", {}).get("file_path", "")
                text = r.get("text", "")[:800]
                context_str += f"\n--- File: {fp} ---\n{text}\n"
            
            # If files_hint specified, read those files
            if files_hint:
                for fp in files_hint[:3]:
                    try:
                        content = self.rag.get_file_content(fp)
                        if content and not content.startswith("File not found") and not content.startswith("Access denied"):
                            context_str += f"\n--- Current content of {fp} ---\n{content[:2000]}\n"
                    except:
                        pass
            
            # Ask brain to generate code changes
            prompt = f"""You are JARVIS, an expert senior engineer. Implement this todo.

Main task: {main_task}

Current todo: {todo.get('title')} - {todo.get('description')}
Todo type: {todo.get('type')}
Files hint: {files_hint}

Codebase context (relevant files):
{context_str[:6000]}

Your job:
1. Decide which files to create or edit
2. Generate the full file content or edits needed
3. Use tools: file_write to create/edit files, file_read to check, file_list

Rules:
- Write clean, production-ready code
- Keep existing style
- Don't break existing code
- Use absolute paths relative to project root like workspace/file.py or jarvis/file.py
- If creating new file, provide full content
- If editing, provide full new content (not diff)
- Focus only on this todo, not entire main task

Implement the todo now using your tools. After done, summarize what you did.
"""
            
            # Use brain.think with tools - this will use file_write etc
            response = self.brain.think(prompt)
            
            # After think, check if files were modified via git status
            git_status = self.git.status()
            
            return {
                "success": True,
                "response": response[:2000],
                "git_status": git_status[:1000],
                "message": f"Coding todo executed via brain, Sir. Response: {response[:300]}",
                "can_retry": False
            }
        
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e), "can_retry": True}
    
    def _do_testing_todo(self, todo: Dict, main_task: str) -> Dict:
        """Run tests"""
        try:
            test_result = self.tester.run_tests()
            return {
                "success": test_result.get("success", False),
                "result": test_result,
                "message": test_result.get("summary", "Tests run"),
                "can_retry": not test_result.get("success", False)
            }
        except Exception as e:
            return {"success": False, "error": str(e), "can_retry": True}
    
    def _do_git_todo(self, todo: Dict, main_task: str) -> Dict:
        """Git commit todo"""
        try:
            status = self.git.status()
            if "nothing to commit" in status or "working tree clean" in status:
                return {"success": True, "message": "No changes to commit, Sir.", "git_status": status}
            
            # Brain already did commit in final step, but we can do here too
            commit_msg = f"feat: {todo.get('title')} - {main_task[:60]}"
            result = self.git.commit(commit_msg)
            return {"success": True, "result": result, "message": f"Committed, Sir: {commit_msg}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _do_docs_todo(self, todo: Dict, main_task: str) -> Dict:
        """Docs todo - similar to coding but for docs"""
        return self._do_coding_todo(todo, main_task, todo.get("files", []))
    
    def _self_fix_todo(self, todo: Dict, previous_result: Dict, main_task: str) -> Dict:
        """Try to fix failed todo"""
        try:
            error = previous_result.get("error") or str(previous_result.get("result", {}).get("combined", ""))[:1000]
            
            prompt = f"""You are JARVIS fixing a failed todo.

Main task: {main_task}
Todo: {todo.get('title')} - {todo.get('description')}
Previous error: {error[:2000]}

Analyze error and fix it. Use tools to read files, edit, run tests.

Fix now, Sir.
"""
            response = self.brain.think(prompt)
            
            # Run tests again if testing related
            if todo.get("type") in ["coding", "testing"]:
                test_result = self.tester.run_tests()
                if test_result.get("success"):
                    return {"success": True, "response": response, "test_result": test_result, "message": "Fixed after retry, Sir."}
                else:
                    return {"success": False, "error": f"Still failing after fix: {test_result.get('combined','')[:500]}", "response": response, "can_retry": False}
            
            return {"success": True, "response": response, "message": "Fix attempted, Sir."}
        
        except Exception as e:
            return {"success": False, "error": str(e)}
