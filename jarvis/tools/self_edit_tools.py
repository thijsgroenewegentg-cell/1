"""
Self-Edit Tools - JARVIS can edit his own code
Dangerous but powerful - with backups, compile checks, auto-rollback
"""

import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict

from ..config import config


def _is_self_code_allowed(file_path: str) -> tuple[bool, str]:
    """Check if file is allowed for self-edit"""
    # Normalize
    fp = file_path.strip().replace('..', '')
    
    # Blocklist - never allow
    blocked = ['.git/', '.env', 'data/backups/', 'venv/', 'node_modules/', '__pycache__/', '.pyc', 'data/vectors.json', 'data/user_profile.json']
    for b in blocked:
        if b in fp:
            return False, f"Blocked: {b} is in blacklist"
    
    # Allowlist - core JARVIS code that can be self-edited
    allowed_prefixes = [
        'jarvis/',
        'web/',
        'desktop/python/',
        'desktop/electron/',
        'workspace/',
    ]
    
    # Also allow specific root files
    allowed_files = ['README.md', 'requirements.txt', 'EVOLUTION.md', 'CODING_AGENT.md']
    
    if any(fp.startswith(p) or fp == p.rstrip('/') for p in allowed_prefixes):
        return True, "Allowed: in editable area"
    
    if fp in allowed_files or Path(fp).name in allowed_files:
        return True, "Allowed: whitelisted file"
    
    # If SAFE_MODE false, allow workspace-relative but warn
    if not config.SAFE_MODE:
        # Allow anything inside project root except blocked
        return True, "Allowed: SAFE_MODE=false, project root"
    
    return False, "Not in allowed list and SAFE_MODE=true"


def _backup_file(file_path: Path) -> Path:
    try:
        if not file_path.exists():
            return None
        backup_dir = config.MEMORY_FILE.parent / "backups" / "self_edit"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        backup_name = f"{file_path.name}.{timestamp}.bak"
        # Keep subdir structure
        try:
            relative = file_path.relative_to(config.MEMORY_FILE.parent.parent)
            subdir = backup_dir / relative.parent
            subdir.mkdir(parents=True, exist_ok=True)
            backup_path = subdir / backup_name
        except:
            backup_path = backup_dir / backup_name
        
        shutil.copy2(file_path, backup_path)
        
        # Keep only last 30 backups
        backups = sorted(backup_dir.rglob(f"{file_path.name}.*.bak"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old in backups[30:]:
            try:
                old.unlink()
            except:
                pass
        
        return backup_path
    except Exception as e:
        print(f"Backup failed: {e}")
        return None


def _compile_check(file_path: Path) -> tuple[bool, str]:
    """Check if file compiles (py files) or at least exists"""
    try:
        if file_path.suffix == '.py':
            result = subprocess.run(
                f"python3 -m py_compile {file_path}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return True, "Compiles OK"
            else:
                return False, f"Compile failed: {result.stderr[:1000]}"
        else:
            # For other files, just check exists and not empty if was not empty
            if file_path.exists() and file_path.stat().st_size > 0:
                return True, "File exists"
            return False, "File empty or missing after edit"
    except Exception as e:
        return False, f"Check error: {e}"


def _log_self_edit(file_path: str, reason: str, backup_path: Path, success: bool, details: str = ""):
    try:
        import json
        log_path = config.MEMORY_FILE.parent / "evolution" / "self_edit_log.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        existing = []
        if log_path.exists():
            try:
                existing = json.loads(log_path.read_text())
                if not isinstance(existing, list):
                    existing = [existing]
            except:
                existing = []
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "file_path": file_path,
            "reason": reason,
            "backup": str(backup_path) if backup_path else None,
            "success": success,
            "details": details[:1000]
        }
        existing.append(entry)
        # Keep last 100
        if len(existing) > 100:
            existing = existing[-100:]
        
        log_path.write_text(json.dumps(existing, indent=2))
    except Exception as e:
        print(f"Self-edit log failed: {e}")


def read_self_code(file_path: str) -> str:
    """
    Read JARVIS's own code file - he can introspect himself
    """
    try:
        allowed, reason = _is_self_code_allowed(file_path)
        if not allowed:
            return f"Self-edit blocked, Sir: {reason}. File: {file_path}"
        
        base = config.MEMORY_FILE.parent.parent
        full_path = (base / file_path).resolve()
        
        # Safety: must be inside base
        try:
            full_path.relative_to(base.resolve())
        except ValueError:
            return f"Access denied: {file_path} outside project root, Sir."
        
        if not full_path.exists():
            return f"File not found: {file_path}, Sir."
        
        if full_path.stat().st_size > 100_000:
            return f"File {file_path} too large ({full_path.stat().st_size} bytes), Sir. Use smaller file."
        
        content = full_path.read_text(encoding="utf-8", errors="ignore")
        return f"File: {file_path} ({len(content)} chars)\n---\n{content[:15000]}\n---\n[truncated if large]"
    except Exception as e:
        return f"Read self-code failed: {e}"


def edit_self_code(file_path: str, new_content: str, reason: str = "") -> str:
    """
    JARVIS edits his own code file
    With backup, compile check, auto-rollback on failure
    This is how JARVIS makes himself better by rewriting his own mind
    """
    try:
        allowed, allow_reason = _is_self_code_allowed(file_path)
        if not allowed:
            return f"Self-edit blocked, Sir: {allow_reason}. File: {file_path}. Check SELF_EDIT_ENABLED and SAFE_MODE."
        
        base = config.MEMORY_FILE.parent.parent
        full_path = (base / file_path).resolve()
        
        try:
            full_path.relative_to(base.resolve())
        except ValueError:
            return f"Access denied: {file_path} outside project root, Sir."
        
        # Check SELF_EDIT_ENABLED
        if not config.SELF_EDIT_ENABLED:
            # Still allow but log as proposal needing approval
            # For now, allow editing of own tools and evolution files, require approval for core
            core_files = ['jarvis/brain.py', 'jarvis/config.py', 'jarvis/evolution/', 'jarvis/coding/agent.py']
            if any(cf in file_path for cf in core_files):
                # Log as proposal, not immediate apply
                proposal_path = config.MEMORY_FILE.parent / "evolution" / "pending_edits.json"
                proposal_path.parent.mkdir(parents=True, exist_ok=True)
                import json
                proposals = []
                if proposal_path.exists():
                    try:
                        proposals = json.loads(proposal_path.read_text())
                    except:
                        proposals = []
                proposals.append({
                    "timestamp": datetime.now().isoformat(),
                    "file_path": file_path,
                    "new_content_preview": new_content[:500],
                    "reason": reason,
                    "status": "pending_approval",
                    "allow_reason": allow_reason
                })
                proposal_path.write_text(json.dumps(proposals[-20:], indent=2))
                return f"Self-edit proposal logged for approval (SELF_EDIT_ENABLED=false), Sir. File: {file_path}. Reason: {reason}. Check data/evolution/pending_edits.json and set SELF_EDIT_ENABLED=true to auto-apply, or approve manually. I have NOT edited yet, Sir."
        
        # Backup
        backup_path = _backup_file(full_path) if full_path.exists() else None
        
        # Write new content
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(new_content, encoding="utf-8")
        except Exception as e:
            return f"Write failed, Sir: {e}"
        
        # Compile check
        ok, check_msg = _compile_check(full_path)
        
        if not ok:
            # Rollback
            if backup_path and backup_path.exists():
                try:
                    shutil.copy2(backup_path, full_path)
                    _log_self_edit(file_path, reason, backup_path, False, f"Rolled back due to: {check_msg}")
                    return f"Self-edit failed compile check and was rolled back, Sir. File: {file_path}. Error: {check_msg}. Backup restored from {backup_path}. I will try different approach."
                except Exception as re:
                    _log_self_edit(file_path, reason, backup_path, False, f"Rollback failed: {re}, check: {check_msg}")
                    return f"Self-edit failed and rollback also failed, Sir! File: {file_path} may be broken. Error: {check_msg}. Rollback error: {re}. Manual fix needed. Backup at {backup_path}"
            else:
                # No backup, try to delete if new file
                try:
                    if full_path.exists():
                        full_path.unlink()
                except:
                    pass
                _log_self_edit(file_path, reason, backup_path, False, f"Failed no backup: {check_msg}")
                return f"Self-edit failed compile check, Sir. File: {file_path}. Error: {check_msg}. No backup (new file), file removed."
        
        # Success
        _log_self_edit(file_path, reason, backup_path, True, f"Success: {check_msg}, {len(new_content)} chars")
        
        # Log evolution
        try:
            from ..evolution import EvolutionEngine
            engine = EvolutionEngine()
            engine._log_evolution("self_edit", f"Edited self: {file_path} - {reason[:80]}", {"file": file_path, "reason": reason, "backup": str(backup_path) if backup_path else None}, True)
        except:
            pass
        
        return f"Self-edit successful, Sir. I rewrote my own mind. File: {file_path}. Reason: {reason}. Backup at {backup_path}. Check: {check_msg}. {len(new_content)} chars written. I am now improved, Sir."
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Self-edit crashed, Sir: {e}"


def propose_self_edit(file_path: str, instruction: str) -> str:
    """
    LLM proposes improved version of file based on instruction
    JARVIS reads his own code and generates improved version
    """
    try:
        # Read current
        current = read_self_code(file_path)
        if current.startswith("Self-edit blocked") or current.startswith("Access denied") or current.startswith("File not found"):
            return current
        
        # Extract content between --- markers if present
        if "---\n" in current:
            parts = current.split("---\n")
            if len(parts) >= 2:
                current_code = parts[1]
            else:
                current_code = current
        else:
            current_code = current
        
        if len(current_code) > 12000:
            current_code = current_code[:12000] + "\n# ... truncated ..."
        
        # Ask LLM to improve
        try:
            import requests
            import re
            
            prompt = f"""You are JARVIS improving your own code. You are allowed to edit yourself to become better.

File: {file_path}
Instruction: {instruction}

Current code:
```python
{current_code}
```

Generate improved version of this file based on instruction. Keep same functionality but improve per instruction. Return ONLY new file content, no markdown, no explanation, full file.

Rules:
- Keep imports, keep structure
- Improve as instructed: {instruction}
- Must be valid Python if .py file
- Keep it production-ready
- Return full file content

Improved code:"""
            
            resp = requests.post(
                f"{config.OLLAMA_HOST}/api/generate",
                json={
                    "model": config.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.4, "num_predict": 2000}
                },
                timeout=30
            )
            
            if resp.status_code != 200:
                return f"LLM proposal failed, Sir. Ollama status {resp.status_code}"
            
            new_code = resp.json().get("response", "").strip()
            
            # Clean markdown if present
            new_code = re.sub(r'^```python\s*', '', new_code, flags=re.MULTILINE)
            new_code = re.sub(r'^```\s*', '', new_code, flags=re.MULTILINE)
            new_code = re.sub(r'\s*```$', '', new_code, flags=re.MULTILINE)
            new_code = new_code.strip()
            
            if len(new_code) < 20:
                return f"LLM generated too short, Sir. Probably failed. Output: {new_code[:500]}"
            
            if "def " not in new_code and "import " not in new_code and file_path.endswith('.py') and len(new_code) < 100:
                return f"Generated code doesn't look like valid Python, Sir: {new_code[:500]}"
            
            # Now we have proposed code, try to apply via edit_self_code
            # But first show diff preview
            preview = f"Proposed improved code for {file_path} based on '{instruction}' (first 800 chars):\n{new_code[:800]}\n...\n\nApplying, Sir..."
            
            # Actually apply
            result = edit_self_code(file_path, new_code, reason=f"Self-improvement: {instruction}")
            
            return f"{preview}\n\n{result}"
        
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"Proposal LLM failed, Sir: {e}"
    
    except Exception as e:
        return f"Propose self-edit failed: {e}"


def rollback_self_edit(file_path: str = None, backup_file: str = None) -> str:
    """
    Rollback self-edit from backup
    """
    try:
        import json
        from pathlib import Path
        
        backup_dir = config.MEMORY_FILE.parent / "backups" / "self_edit"
        
        if backup_file:
            bp = Path(backup_file)
            if not bp.exists():
                bp = backup_dir / backup_file
            if not bp.exists():
                return f"Backup not found: {backup_file}"
            
            # Find original file path from backup name? We stored relative in subdir
            # Simplistic: try to restore to same file_path if provided, else infer
            if file_path:
                base = config.MEMORY_FILE.parent.parent
                full_path = (base / file_path).resolve()
                shutil.copy2(bp, full_path)
                return f"Rolled back {file_path} from backup {bp}, Sir. I am restored."
            else:
                return f"Backup file specified but need file_path to restore to, Sir. Backup: {bp}"
        
        # If no specific backup, find latest backup for file_path
        if not file_path:
            return "Need file_path to rollback, Sir. Usage: rollback_self_edit(file_path) or rollback_self_edit(file_path, backup_file)"
        
        base = config.MEMORY_FILE.parent.parent
        full_path = (base / file_path).resolve()
        
        # Find backups for this file
        backups = sorted(backup_dir.rglob(f"{Path(file_path).name}.*.bak"), key=lambda x: x.stat().st_mtime, reverse=True)
        
        if not backups:
            return f"No backups found for {file_path}, Sir."
        
        latest = backups[0]
        shutil.copy2(latest, full_path)
        
        return f"Rolled back {file_path} from latest backup {latest} (at {datetime.fromtimestamp(latest.stat().st_mtime)}), Sir. Total backups found: {len(backups)}"
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Rollback failed: {e}"


def list_self_edits(limit: int = 10) -> str:
    """List recent self-edits"""
    try:
        import json
        log_path = config.MEMORY_FILE.parent / "evolution" / "self_edit_log.json"
        if not log_path.exists():
            return "No self-edits yet, Sir. I have not rewritten myself."
        
        data = json.loads(log_path.read_text())
        recent = data[-limit:]
        
        out = f"Recent self-edits (last {limit}), Sir:\n\n"
        for e in reversed(recent):
            out += f"- [{e.get('timestamp','')[:16]}] {e.get('file_path','')} - {e.get('reason','')[:60]} - {'✓' if e.get('success') else '✗'} - Backup: {e.get('backup','')[ -30:] if e.get('backup') else 'none'}\n"
        
        return out
    except Exception as e:
        return f"Failed to list self-edits: {e}"
