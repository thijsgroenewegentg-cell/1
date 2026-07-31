"""
Tool Forger - JARVIS creates new tools when he needs them
Self-evolution by forging new capabilities
"""

import json
import re
from typing import Dict, Optional

from ..config import config
from .self_editor import SelfEditor


class ToolForger:
    def __init__(self):
        self.editor = SelfEditor()
    
    def detect_missing_tool(self, user_input: str, assistant_response: str, tool_calls_made: list) -> Optional[Dict]:
        """
        Detect if user asked for something that existing tools can't handle
        Returns None if not missing, or dict with needed tool description
        """
        # Keywords that hint at missing capability
        missing_patterns = {
            "spotify": ["spotify", "play music", "play song"],
            "email": ["email", "gmail", "send mail"],
            "calendar": ["calendar", "schedule meeting", "add event"],
            "smart_home": ["lights", "thermostat", "home assistant", "turn on", "turn off the"],
            "stock": ["stock price", "crypto", "bitcoin price"],
            "translate": ["translate", "in spanish", "in french"],
            "image_generate": ["generate image", "create image", "draw"],
            "youtube": ["youtube", "play video"],
            "twitter": ["tweet", "twitter", "x.com"],
            "github": ["github", "create repo", "push code"],
        }
        
        user_lower = user_input.lower()
        response_lower = assistant_response.lower()
        
        # If assistant said "I can't" or "I don't have tool", likely missing
        cant_do_phrases = ["i can't", "i don't have", "i cannot", "no tool", "unable to", "not able to"]
        cant_do = any(phrase in response_lower for phrase in cant_do_phrases)
        
        for tool_key, keywords in missing_patterns.items():
            if any(kw in user_lower for kw in keywords):
                # Check if we already have a tool for this
                existing_tools = ["search_web", "get_weather", "get_time", "remember", "file_read", "file_write", "execute_python", "shell_command", "open_website", "open_application"]
                if tool_key not in "".join(existing_tools):
                    # And if we didn't already call relevant tool
                    if cant_do or len(tool_calls_made) == 0:
                        return {
                            "needed": tool_key,
                            "user_request": user_input,
                            "reason": f"User asked for {tool_key} capability that doesn't exist, assistant said it can't"
                        }
        
        # Also detect generic "I need a tool for X"
        if "need a tool" in user_lower or "create a tool" in user_lower or "make a tool" in user_lower:
            return {
                "needed": "custom",
                "user_request": user_input,
                "reason": "User explicitly asked for new tool"
            }
        
        return None
    
    def forge_tool(self, needed_tool: str, user_request: str, reason: str = "") -> Dict:
        """
        Forge a new tool using LLM code generation
        """
        try:
            import requests
            
            prompt = f"""You are JARVIS, an AI that creates its own tools. Create a Python tool for: {needed_tool}

User request: "{user_request}"
Reason: {reason}

You must create a Python function that will be a tool.

Requirements:
1. Function name must be exactly: {needed_tool} (or snake_case)
2. Must have docstring explaining what it does
3. Should be safe, no dangerous operations
4. Use only standard library + requests, os, json, datetime, etc
5. Return string result (human readable, JARVIS style)
6. Keep it simple, 20-60 lines max
7. If needs API key, use placeholder and explain

Example format:
def spotify_control(action: str, query: str = "") -> str:
    \"\"\"Control Spotify - play, pause, search\"\"\"
    try:
        # implementation
        return f"Spotify {{action}} executed, Sir."
    except Exception as e:
        return f"Spotify control failed: {{e}}"

Now create tool for: {needed_tool}

Return ONLY Python code, no markdown, no explanation, just the function.

Code:"""
            
            resp = requests.post(
                f"{config.OLLAMA_HOST}/api/generate",
                json={
                    "model": config.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.4, "num_predict": 800}
                },
                timeout=20
            )
            
            if resp.status_code == 200:
                code = resp.json().get("response", "").strip()
                # Clean code (remove markdown if present)
                code = re.sub(r'^```python\s*', '', code)
                code = re.sub(r'^```\s*', '', code)
                code = re.sub(r'\s*```$', '', code)
                code = code.strip()
                
                if "def " not in code:
                    return {"success": False, "error": "LLM didn't generate valid function"}
                
                # Extract function name
                match = re.search(r'def (\w+)\s*\(', code)
                if not match:
                    return {"success": False, "error": "No function found in generated code"}
                
                func_name = match.group(1)
                
                # Generate tool schema via LLM as well
                schema_prompt = f"""Create OpenAI tool schema JSON for function:

{code[:500]}

Return ONLY JSON with format:
{{"type": "function", "function": {{"name": "FUNC_NAME", "description": "...", "parameters": {{"type": "object", "properties": {{...}}, "required": [...]}}}}}}

JSON:"""
                
                schema_resp = requests.post(
                    f"{config.OLLAMA_HOST}/api/generate",
                    json={
                        "model": config.OLLAMA_MODEL,
                        "prompt": schema_prompt,
                        "stream": False,
                        "options": {"temperature": 0.2, "num_predict": 400}
                    },
                    timeout=10
                )
                
                schema = None
                if schema_resp.status_code == 200:
                    schema_text = schema_resp.json().get("response", "")
                    # Try to extract JSON
                    start = schema_text.find("{")
                    end = schema_text.rfind("}") + 1
                    if start != -1 and end != -1:
                        try:
                            schema = json.loads(schema_text[start:end])
                        except:
                            pass
                
                if not schema:
                    # Fallback schema
                    schema = {
                        "type": "function",
                        "function": {
                            "name": func_name,
                            "description": f"Auto-forged tool for {needed_tool}: {user_request[:100]}",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string", "description": "Query or input"}
                                },
                                "required": []
                            }
                        }
                    }
                
                # Try to test the code in sandbox (basic syntax check)
                try:
                    compile(code, "<string>", "exec")
                except SyntaxError as e:
                    return {"success": False, "error": f"Generated code has syntax error: {e}"}
                
                # Create tool via editor
                result = self.editor.create_tool(func_name, code, schema, reason=f"User asked: {user_request[:100]} - {reason}")
                
                return result
        
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
        
        return {"success": False, "error": "Failed to forge tool"}
    
    def list_forged_tools(self) -> list:
        """List tools that were auto-forged"""
        try:
            import json
            from pathlib import Path
            log_path = config.MEMORY_FILE.parent / "evolution" / "tool_forge_log.json"
            if log_path.exists():
                data = json.loads(log_path.read_text())
                return data if isinstance(data, list) else [data]
            return []
        except:
            return []
