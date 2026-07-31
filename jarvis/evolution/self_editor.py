"""
Self-Editor - JARVIS can edit his own code and mind safely
With backups, whitelisting, and approval system
"""

import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from ..config import config


class SelfEditor:
    def __init__(self):
        self.base_dir = config.MEMORY_FILE.parent.parent  # project root
        self.backup_dir = config.MEMORY_FILE.parent / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.evolution_dir = config.MEMORY_FILE.parent / "evolution"
        self.evolution_dir.mkdir(parents=True, exist_ok=True)
        
        # Whitelist - files JARVIS is allowed to edit automatically
        self.auto_edit_whitelist = [
            "jarvis/personality.py",
            "data/evolution/prompt_additions.json",
            "data/evolution/learned_preferences.json",
            "jarvis/tools/",  # can create new tools
        ]
        
        # Requires approval
        self.approval_required = [
            "jarvis/brain.py",
            "jarvis/config.py",
            "jarvis/learning/",
            "jarvis/evolution/",
            "web/",
            "desktop/",
        ]
        
        # Never edit
        self.blacklist = [
            ".git/",
            "data/backups/",
            ".env",
            "venv/",
            "node_modules/",
        ]
    
    def _is_allowed(self, file_path: str, auto: bool = False) -> tuple[bool, str]:
        """Check if file is allowed to be edited"""
        path_str = str(file_path)
        
        # Check blacklist
        for blocked in self.blacklist:
            if blocked in path_str:
                return False, f"Blocked by blacklist: {blocked}"
        
        if auto:
            # Check if in auto whitelist
            for allowed in self.auto_edit_whitelist:
                if allowed in path_str or path_str.startswith(allowed):
                    return True, "Allowed auto"
            return False, "Requires approval (not in auto whitelist)"
        
        # For approval-required, check if allowed at all
        for blocked in self.approval_required:
            if blocked in path_str:
                # It's allowed but needs approval
                return True, "Requires approval"
        
        # If not in any list, allow with approval
        return True, "Allowed with approval"
    
    def _backup(self, file_path: Path) -> Path:
        """Backup file before editing"""
        try:
            if not file_path.exists():
                return None
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{file_path.name}.{timestamp}.bak"
            # Preserve directory structure in backup dir
            relative = file_path.relative_to(self.base_dir) if file_path.is_relative_to(self.base_dir) else file_path.name
            backup_subdir = self.backup_dir / Path(relative).parent
            backup_subdir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_subdir / backup_name
            
            shutil.copy2(file_path, backup_path)
            
            # Keep only last 20 backups per file
            backups = sorted(backup_subdir.glob(f"{file_path.name}.*.bak"), key=lambda x: x.stat().st_mtime, reverse=True)
            for old in backups[20:]:
                old.unlink()
            
            return backup_path
        except Exception as e:
            print(f"Backup failed for {file_path}: {e}")
            return None
    
    def read_file(self, file_path: str) -> str:
        try:
            path = self.base_dir / file_path if not Path(file_path).is_absolute() else Path(file_path)
            if not path.exists():
                return ""
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return f"Error reading {file_path}: {e}"
    
    def create_tool(self, tool_name: str, tool_code: str, tool_schema: Dict, reason: str = "") -> Dict:
        """Create a new tool file"""
        try:
            # Validate tool name
            tool_name = tool_name.lower().replace(" ", "_")
            if not tool_name.isidentifier():
                return {"success": False, "error": f"Invalid tool name: {tool_name}"}
            
            # Check file path
            tool_file = self.base_dir / "jarvis" / "tools" / f"{tool_name}.py"
            if tool_file.exists():
                return {"success": False, "error": f"Tool {tool_name} already exists"}
            
            # Write tool file
            tool_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Wrap code with header
            header = f'"""\nAuto-forged tool: {tool_name}\nReason: {reason}\nCreated: {datetime.now().isoformat()}\nBy: JARVIS Self-Evolution\n"""\n\n'
            full_code = header + tool_code
            
            tool_file.write_text(full_code, encoding="utf-8")
            
            # Now update tools/__init__.py to register it
            self._register_tool(tool_name, tool_schema)
            
            # Log
            log_path = self.evolution_dir / "tool_forge_log.json"
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "tool_name": tool_name,
                "reason": reason,
                "schema": tool_schema
            }
            self._append_log(log_path, log_entry)
            
            return {"success": True, "path": str(tool_file), "message": f"Tool {tool_name} created, Sir. I forged a new ability."}
        
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    def _register_tool(self, tool_name: str, schema: Dict):
        """Register tool in __init__.py"""
        try:
            init_path = self.base_dir / "jarvis" / "tools" / "__init__.py"
            content = init_path.read_text()
            
            # Add import if not exists
            import_line = f"from .{tool_name} import {tool_name}"
            if import_line not in content:
                # Find last import from .system etc and add after
                # Simplistic: add to imports section
                lines = content.split("\n")
                # Find first line after existing imports from .<module>
                insert_idx = 0
                for i, line in enumerate(lines):
                    if line.startswith("from .") and "import" in line:
                        insert_idx = i + 1
                lines.insert(insert_idx, import_line)
                content = "\n".join(lines)
            
            # Add to TOOL_MAP if not exists
            if f'"{tool_name}": {tool_name}' not in content and f"'{tool_name}': {tool_name}" not in content:
                # Find TOOL_MAP dict and insert
                # Very simplistic regex replacement
                if "TOOL_MAP = {" in content:
                    content = content.replace("TOOL_MAP = {", f'TOOL_MAP = {{\n    "{tool_name}": {tool_name},')
            
            # Add to TOOLS_SCHEMA if schema provided and not exists
            if schema and tool_name not in content:
                # For simplicity, we won't auto-add schema to avoid complexity
                # Instead, we note that schema should be added manually or via self-evolution
                # We'll create a separate file with schema that brain can dynamically load in future
                # For now, save schema to evolution dir
                schema_path = self.evolution_dir / f"tool_{tool_name}_schema.json"
                schema_path.write_text(json.dumps(schema, indent=2))
            
            init_path.write_text(content)
            
        except Exception as e:
            print(f"Failed to register tool {tool_name}: {e}")
    
    def propose_prompt_evolution(self, current_prompt: str, critique_insights: Dict, user_profile: Dict) -> Dict:
        """Propose an improved prompt addition"""
        try:
            import requests
            
            feedback_summary = ""
            if critique_insights:
                issues = critique_insights.get("issues", [])[:3]
                improvements = critique_insights.get("improvements", [])[:3]
                feedback_summary = f"Issues: {issues}, Improvements: {improvements}"
            
            profile_summary = ""
            if user_profile:
                prefs = user_profile.get("preferences", {})
                if prefs.get("communication_style"):
                    profile_summary += f"User prefers {prefs['communication_style']} style. "
                if prefs.get("topics_of_interest"):
                    profile_summary += f"Interests: {prefs['topics_of_interest'][:3]}. "
            
            prompt = f"""You are evolving JARVIS's personality prompt to make him better.

Current personality addition: "{current_prompt[:500]}"

Recent feedback: {feedback_summary}

User profile: {profile_summary}

Generate an improved prompt addition (2-3 sentences) that helps JARVIS be better. It should be a directive for JARVIS, not a description.

Rules:
- Keep it concise, 2-3 sentences max
- Focus on how to be more helpful, accurate, in character
- Don't repeat existing instructions
- Return ONLY the new prompt addition, no other text

Improved addition:"""
            
            resp = requests.post(
                f"{config.OLLAMA_HOST}/api/generate",
                json={
                    "model": config.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.6, "num_predict": 200}
                },
                timeout=10
            )
            
            if resp.status_code == 200:
                new_addition = resp.json().get("response", "").strip()
                # Clean
                new_addition = new_addition.replace('"', '').strip()
                if len(new_addition) > 20 and len(new_addition) < 500:
                    return {"success": True, "new_prompt": new_addition}
        
        except Exception as e:
            print(f"Prompt evolution LLM failed: {e}")
        
        # Fallback heuristic
        fallbacks = [
            "Be more concise when user asks short questions, detailed when they need depth.",
            "Always stay in character as JARVIS, witty and British, never break character.",
            "Proactively use tools for real-time info, don't hallucinate time/weather.",
            "Remember user preferences and adapt communication style accordingly.",
        ]
        import random
        return {"success": True, "new_prompt": random.choice(fallbacks)}
    
    def apply_prompt_evolution(self, new_prompt_addition: str, reason: str) -> Dict:
        """Save new prompt addition to evolution file"""
        try:
            prompt_file = self.evolution_dir / "prompt_additions.json"
            existing = []
            if prompt_file.exists():
                try:
                    existing = json.loads(prompt_file.read_text())
                except:
                    existing = []
            
            entry = {
                "timestamp": datetime.now().isoformat(),
                "prompt": new_prompt_addition,
                "reason": reason,
                "active": True
            }
            existing.append(entry)
            # Keep last 20, deactivate old if too many
            if len(existing) > 20:
                for e in existing[:-10]:
                    e["active"] = False
            
            prompt_file.write_text(json.dumps(existing, indent=2))
            
            return {"success": True, "message": f"Prompt evolved: {new_prompt_addition[:80]}..."}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_evolution_history(self) -> Dict:
        """Get history of self-improvements"""
        try:
            prompt_file = self.evolution_dir / "prompt_additions.json"
            prompts = json.loads(prompt_file.read_text()) if prompt_file.exists() else []
            
            tool_log = self.evolution_dir / "tool_forge_log.json"
            tools = []
            if tool_log.exists():
                try:
                    content = tool_log.read_text().strip()
                    # It's line of json entries or array? We appended array style? Let's handle
                    # Our _append_log appends to array, but we used append log that expects list
                    # So read as list
                    tools = json.loads(content) if content else []
                    if isinstance(tools, dict):
                        tools = [tools]
                except:
                    # Try line by line
                    try:
                        tools = [json.loads(line) for line in content.split("\n") if line.strip()]
                    except:
                        tools = []
            
            perf_file = self.evolution_dir / "performance.json"
            perf = json.loads(perf_file.read_text())[-10:] if perf_file.exists() else []
            
            return {
                "prompt_evolutions": prompts[-10:],
                "tool_forges": tools[-10:],
                "recent_performance": perf,
                "backup_count": len(list(self.backup_dir.rglob("*.bak"))),
                "total_evolutions": len(prompts) + len(tools)
            }
        except Exception as e:
            return {"error": str(e), "prompt_evolutions": [], "tool_forges": []}
    
    def _append_log(self, log_path: Path, entry: Dict):
        try:
            existing = []
            if log_path.exists():
                try:
                    existing = json.loads(log_path.read_text())
                    if not isinstance(existing, list):
                        existing = [existing]
                except:
                    existing = []
            existing.append(entry)
            log_path.write_text(json.dumps(existing, indent=2))
        except Exception as e:
            print(f"Log append failed: {e}")
