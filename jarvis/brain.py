"""
JARVIS Brain - Ollama client with tool calling support
"""
import json
import time
import requests
from typing import List, Dict, Any, Generator, Optional
from .config import config
from .personality import JARVIS_SYSTEM_PROMPT
from .tools import TOOLS_SCHEMA, TOOL_MAP
from .memory import MemoryManager, ConversationManager

try:
    import ollama
    OLLAMA_LIB = True
except ImportError:
    OLLAMA_LIB = False

class JarvisBrain:
    def __init__(self, model: str = None, system_prompt: str = None):
        self.model = model or config.OLLAMA_MODEL
        self.fallback_models = config.FALLBACK_MODELS
        self.system_prompt = system_prompt or JARVIS_SYSTEM_PROMPT
        self.host = config.OLLAMA_HOST
        self.memory = MemoryManager()
        self.conversation = ConversationManager()
        self.messages: List[Dict] = []
        self._init_messages()
        self._check_ollama()
    
    def _init_messages(self):
        self.messages = [{"role": "system", "content": self.system_prompt}]
        # Load recent history
        history = self.conversation.load_history(limit=10)
        for msg in history:
            if msg["role"] in ["user", "assistant"]:
                self.messages.append({"role": msg["role"], "content": msg["content"]})
    
    def _check_ollama(self):
        """Check Ollama connection and model availability"""
        try:
            if OLLAMA_LIB:
                client = ollama.Client(host=self.host)
                models = client.list()
                available = [m['name'] if isinstance(m, dict) else m.model for m in models.get('models', [])]
            else:
                resp = requests.get(f"{self.host}/api/tags", timeout=5)
                resp.raise_for_status()
                available = [m["name"] for m in resp.json().get("models", [])]
            
            # If primary model not available, try fallbacks
            all_models_str = " ".join(available).lower()
            if self.model not in all_models_str and not any(self.model in a for a in available):
                print(f"⚠️ Model {self.model} not found. Available: {available}")
                for fb in self.fallback_models:
                    if any(fb in a or a in fb for a in available):
                        print(f"✓ Using fallback model: {fb}")
                        self.model = fb
                        break
                else:
                    if available:
                        print(f"✓ Using first available: {available[0]}")
                        self.model = available[0]
                    else:
                        print(f"❌ No models available. Pull one: ollama pull {self.fallback_models[0]}")
        except Exception as e:
            print(f"⚠️ Could not connect to Ollama at {self.host}: {e}")
            print(f"   Make sure 'ollama serve' is running, Sir.")
    
    def _call_ollama_chat(self, messages: List[Dict], tools: List[Dict] = None, stream: bool = False) -> Dict:
        """Call Ollama API, with or without library"""
        if OLLAMA_LIB:
            try:
                client = ollama.Client(host=self.host)
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "stream": stream,
                }
                if tools:
                    kwargs["tools"] = tools
                
                if stream:
                    return client.chat(**kwargs)
                else:
                    response = client.chat(**kwargs)
                    # Normalize response to dict like API
                    if hasattr(response, 'model_dump'):
                        response = response.model_dump()
                    elif not isinstance(response, dict):
                        # Convert ollama response object
                        msg = response.get('message', {}) if isinstance(response, dict) else getattr(response, 'message', {})
                        if not isinstance(msg, dict):
                            msg = {"role": getattr(msg, 'role', 'assistant'), "content": getattr(msg, 'content', ''), "tool_calls": getattr(msg, 'tool_calls', None)}
                        response = {"message": msg}
                    return response
            except Exception as e:
                print(f"Ollama library call failed: {e}, falling back to requests")
        
        # Fallback to requests
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False
        }
        if tools:
            payload["tools"] = tools
        
        resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()
    
    def _call_ollama_chat_stream(self, messages: List[Dict], tools: List[Dict] = None) -> Generator[str, None, None]:
        """Streaming call"""
        if OLLAMA_LIB:
            try:
                client = ollama.Client(host=self.host)
                stream = client.chat(model=self.model, messages=messages, tools=tools, stream=True)
                for chunk in stream:
                    if isinstance(chunk, dict):
                        content = chunk.get("message", {}).get("content", "")
                    else:
                        content = getattr(chunk.message, 'content', '') if hasattr(chunk, 'message') else ""
                    if content:
                        yield content
                return
            except Exception as e:
                print(f"Stream failed via lib: {e}")
        
        # Requests streaming
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True
        }
        if tools:
            payload["tools"] = tools
        
        resp = requests.post(f"{self.host}/api/chat", json=payload, stream=True, timeout=120)
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line:
                try:
                    data = json.loads(line)
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                except:
                    continue
    
    def think(self, user_input: str, use_tools: bool = True) -> str:
        """
        Main thinking loop: chat + tool execution loop (up to 5 iterations)
        """
        self.messages.append({"role": "user", "content": user_input})
        self.conversation.add_message("user", user_input)
        
        max_tool_iterations = 5
        iteration = 0
        final_response = ""
        
        while iteration < max_tool_iterations:
            iteration += 1
            
            try:
                # Call Ollama
                response = self._call_ollama_chat(
                    messages=self.messages,
                    tools=TOOLS_SCHEMA if use_tools else None,
                    stream=False
                )
                
                message = response.get("message", {})
                content = message.get("content", "")
                tool_calls = message.get("tool_calls", [])
                
                # If no tool calls, we're done
                if not tool_calls:
                    final_response = content
                    self.messages.append({"role": "assistant", "content": content})
                    self.conversation.add_message("assistant", content)
                    break
                
                # Handle tool calls
                print(f"🔧 JARVIS uses tools: {[tc.get('function', {}).get('name') for tc in tool_calls]}")
                
                # Add assistant message with tool calls
                self.messages.append(message)
                
                # Execute each tool
                for tool_call in tool_calls:
                    func_info = tool_call.get("function", {})
                    func_name = func_info.get("name")
                    func_args = func_info.get("arguments", {})
                    
                    if isinstance(func_args, str):
                        try:
                            func_args = json.loads(func_args)
                        except:
                            func_args = {}
                    
                    # Execute
                    tool_func = TOOL_MAP.get(func_name)
                    if tool_func:
                        try:
                            result = tool_func(**func_args)
                        except Exception as e:
                            result = f"Tool {func_name} error: {e}"
                    else:
                        result = f"Tool {func_name} not found, Sir."
                    
                    # Add tool result
                    tool_result_msg = {
                        "role": "tool",
                        "content": str(result)
                    }
                    self.messages.append(tool_result_msg)
                
                # If after tool calls, we want to loop again to get final answer
                # If this was last iteration, create final response from tool results
                if iteration == max_tool_iterations:
                    # One final call to synthesize
                    response = self._call_ollama_chat(messages=self.messages, tools=None, stream=False)
                    final_response = response.get("message", {}).get("content", "I've completed the tasks, Sir.")
                    self.messages.append({"role": "assistant", "content": final_response})
                    self.conversation.add_message("assistant", final_response)
                    break
                
                # Continue loop - next iteration will get final response
                
            except Exception as e:
                error_msg = f"I encountered an issue with my neural pathways, Sir: {e}"
                print(error_msg)
                final_response = error_msg
                self.messages.append({"role": "assistant", "content": final_response})
                break
        
        return final_response
    
    def think_stream(self, user_input: str) -> Generator[str, None, None]:
        """Streaming version without tool loop for UI"""
        self.messages.append({"role": "user", "content": user_input})
        self.conversation.add_message("user", user_input)
        
        full_response = ""
        try:
            # First check if tools needed (non-streaming check)
            check_resp = self._call_ollama_chat(messages=self.messages, tools=TOOLS_SCHEMA, stream=False)
            msg = check_resp.get("message", {})
            tool_calls = msg.get("tool_calls", [])
            
            if tool_calls:
                # Tool path - non-streaming but execute tools then stream final
                for tc in tool_calls:
                    func_info = tc.get("function", {})
                    func_name = func_info.get("name")
                    func_args = func_info.get("arguments", {})
                    if isinstance(func_args, str):
                        try:
                            func_args = json.loads(func_args)
                        except:
                            func_args = {}
                    
                    self.messages.append(msg)
                    
                    tool_func = TOOL_MAP.get(func_name)
                    if tool_func:
                        try:
                            result = tool_func(**func_args)
                            yield f"\n[Using tool: {func_name} -> {result[:100]}...]\n"
                        except Exception as e:
                            result = f"Error: {e}"
                            yield f"\n[Tool error: {e}]\n"
                    else:
                        result = f"Tool {func_name} not found"
                    
                    self.messages.append({"role": "tool", "content": str(result)})
                    
                    # Now stream final answer
                    for chunk in self._call_ollama_chat_stream(self.messages, tools=None):
                        full_response += chunk
                        yield chunk
                    
                    self.messages.append({"role": "assistant", "content": full_response})
                    self.conversation.add_message("assistant", full_response)
                    return
            
            # No tools, just stream
            for chunk in self._call_ollama_chat_stream(self.messages, tools=None):
                full_response += chunk
                yield chunk
            
            self.messages.append({"role": "assistant", "content": full_response})
            self.conversation.add_message("assistant", full_response)
            
        except Exception as e:
            err = f"Neural link disrupted, Sir: {e}"
            yield err
    
    def set_personality(self, prompt: str):
        self.system_prompt = prompt
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = prompt
        else:
            self.messages.insert(0, {"role": "system", "content": prompt})
    
    def clear_memory(self):
        self._init_messages()
        self.conversation.clear()
    
    def get_status(self) -> Dict:
        return {
            "model": self.model,
            "host": self.host,
            "ollama_connected": self._is_ollama_up(),
            "conversation_length": len(self.messages),
            "memory_count": len(self.memory.get_all_memories())
        }
    
    def _is_ollama_up(self) -> bool:
        try:
            requests.get(f"{self.host}/api/tags", timeout=2)
            return True
        except:
            return False
