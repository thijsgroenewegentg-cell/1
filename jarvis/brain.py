"""
JARVIS Brain - Ollama client with tool calling + self-learning + self-evolution
"""

import json
import time
import requests
from typing import List, Dict, Any, Generator, Optional
from .config import config
from .personality import JARVIS_SYSTEM_PROMPT
from .tools import TOOLS_SCHEMA, TOOL_MAP
from .memory import MemoryManager, ConversationManager

# Self-learning
try:
    from .learning import LearningEngine
    LEARNING_AVAILABLE = True
except Exception as e:
    print(f"Learning engine not available: {e}")
    LEARNING_AVAILABLE = False
    LearningEngine = None

# Self-evolution
try:
    from .evolution import EvolutionEngine
    EVOLUTION_AVAILABLE = True
except Exception as e:
    print(f"Evolution engine not available: {e}")
    EVOLUTION_AVAILABLE = False
    EvolutionEngine = None

try:
    import ollama
    OLLAMA_LIB = True
except ImportError:
    OLLAMA_LIB = False


class JarvisBrain:
    def __init__(self, model: str = None, system_prompt: str = None, enable_learning: bool = True, enable_evolution: bool = True):
        self.model = model or config.OLLAMA_MODEL
        self.fallback_models = config.FALLBACK_MODELS
        self.base_system_prompt = system_prompt or JARVIS_SYSTEM_PROMPT
        self.system_prompt = self.base_system_prompt
        self.host = config.OLLAMA_HOST
        self.memory = MemoryManager()
        self.conversation = ConversationManager()
        self.messages: List[Dict] = []
        
        # Self-learning
        self.learning_enabled = enable_learning and LEARNING_AVAILABLE
        self.learning_engine = None
        if self.learning_enabled:
            try:
                self.learning_engine = LearningEngine(use_llm_extraction=True)
                print("🧠 Self-learning enabled, Sir.")
            except Exception as e:
                print(f"Learning init failed: {e}")
                self.learning_enabled = False
        
        # Self-evolution
        self.evolution_enabled = enable_evolution and EVOLUTION_AVAILABLE and config.LEARNING_ENABLED
        self.evolution_engine = None
        if self.evolution_enabled:
            try:
                self.evolution_engine = EvolutionEngine()
                print("🧬 Self-evolution enabled, Sir. I can make myself better.")
            except Exception as e:
                print(f"Evolution init failed: {e}")
                self.evolution_enabled = False
        
        self._init_messages()
        self._check_ollama()
    
    def _load_evolution_prompt_additions(self) -> str:
        """Load evolved prompt additions"""
        try:
            from pathlib import Path
            prompt_file = config.MEMORY_FILE.parent / "evolution" / "prompt_additions.json"
            if prompt_file.exists():
                data = json.loads(prompt_file.read_text())
                active = [e["prompt"] for e in data if e.get("active", True)]
                if active:
                    # Return last 3 active evolutions
                    return "\n".join([f"- {p}" for p in active[-3:]])
        except:
            pass
        return ""
    
    def _init_messages(self):
        full_prompt = self.base_system_prompt
        
        if self.learning_enabled and self.learning_engine:
            try:
                profile_ctx = self.learning_engine.user_profile.get_summary_for_prompt()
                adaptive = self.learning_engine.user_profile.get_adaptive_prompt_addition()
                if profile_ctx:
                    full_prompt += f"\n\n{profile_ctx}"
                if adaptive:
                    full_prompt += f"\n\n{adaptive}"
            except:
                pass
        
        # Add evolution additions
        try:
            evo_additions = self._load_evolution_prompt_additions()
            if evo_additions:
                full_prompt += f"\n\nSelf-evolved improvements (learned from experience):\n{evo_additions}"
        except:
            pass
        
        self.system_prompt = full_prompt
        self.messages = [{"role": "system", "content": self.system_prompt}]
        history = self.conversation.load_history(limit=10)
        for msg in history:
            if msg["role"] in ["user", "assistant"]:
                self.messages.append({"role": msg["role"], "content": msg["content"]})
    
    def _build_messages_with_context(self, user_input: str) -> List[Dict]:
        if not self.learning_enabled or not self.learning_engine:
            return self.messages
        
        try:
            context = self.learning_engine.get_context(user_input, k=5)
            if not context:
                return self.messages
            
            enhanced = self.messages.copy()
            adaptive_system = self.base_system_prompt
            profile_summary = self.learning_engine.user_profile.get_summary_for_prompt()
            adaptive_add = self.learning_engine.user_profile.get_adaptive_prompt_addition()
            evo_additions = self._load_evolution_prompt_additions()
            
            if profile_summary:
                adaptive_system += f"\n\n{profile_summary}"
            if adaptive_add:
                adaptive_system += f"\n\n{adaptive_add}"
            if evo_additions:
                adaptive_system += f"\n\nSelf-evolved improvements:\n{evo_additions}"
            if context:
                if "Relevant memories" in context:
                    adaptive_system += f"\n\nContext from memory (use if relevant):\n{context}"
            
            if enhanced and enhanced[0]["role"] == "system":
                enhanced[0] = {"role": "system", "content": adaptive_system}
            
            return enhanced
        except Exception as e:
            print(f"Context injection failed: {e}")
            return self.messages
    
    def _check_ollama(self):
        try:
            if OLLAMA_LIB:
                client = ollama.Client(host=self.host)
                models = client.list()
                available = [m['name'] if isinstance(m, dict) else m.model for m in models.get('models', [])]
            else:
                resp = requests.get(f"{self.host}/api/tags", timeout=5)
                resp.raise_for_status()
                available = [m["name"] for m in resp.json().get("models", [])]
            
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
        if OLLAMA_LIB:
            try:
                client = ollama.Client(host=self.host)
                kwargs = {"model": self.model, "messages": messages, "stream": stream}
                if tools:
                    kwargs["tools"] = tools
                if stream:
                    return client.chat(**kwargs)
                else:
                    response = client.chat(**kwargs)
                    if hasattr(response, 'model_dump'):
                        response = response.model_dump()
                    elif not isinstance(response, dict):
                        msg = response.get('message', {}) if isinstance(response, dict) else getattr(response, 'message', {})
                        if not isinstance(msg, dict):
                            msg = {"role": getattr(msg, 'role', 'assistant'), "content": getattr(msg, 'content', ''), "tool_calls": getattr(msg, 'tool_calls', None)}
                        response = {"message": msg}
                    return response
            except Exception as e:
                print(f"Ollama library call failed: {e}, falling back to requests")
        
        payload = {"model": self.model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
        
        resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()
    
    def _call_ollama_chat_stream(self, messages: List[Dict], tools: List[Dict] = None) -> Generator[str, None, None]:
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
        
        payload = {"model": self.model, "messages": messages, "stream": True}
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
        start_time = time.time()
        messages_with_context = self._build_messages_with_context(user_input)
        self.messages.append({"role": "user", "content": user_input})
        messages_with_context.append({"role": "user", "content": user_input})
        self.conversation.add_message("user", user_input)
        
        max_tool_iterations = 5
        iteration = 0
        final_response = ""
        tool_calls_made = []
        working_messages = messages_with_context
        
        while iteration < max_tool_iterations:
            iteration += 1
            try:
                response = self._call_ollama_chat(messages=working_messages, tools=TOOLS_SCHEMA if use_tools else None, stream=False)
                message = response.get("message", {})
                content = message.get("content", "")
                tool_calls = message.get("tool_calls", [])
                
                if not tool_calls:
                    final_response = content
                    self.messages.append({"role": "assistant", "content": content})
                    self.conversation.add_message("assistant", content)
                    break
                
                print(f"🔧 JARVIS uses tools: {[tc.get('function', {}).get('name') for tc in tool_calls]}")
                tool_calls_made.extend(tool_calls)
                
                self.messages.append(message)
                working_messages.append(message)
                
                for tool_call in tool_calls:
                    func_info = tool_call.get("function", {})
                    func_name = func_info.get("name")
                    func_args = func_info.get("arguments", {})
                    
                    if isinstance(func_args, str):
                        try:
                            func_args = json.loads(func_args)
                        except:
                            func_args = {}
                    
                    tool_func = TOOL_MAP.get(func_name)
                    if tool_func:
                        try:
                            result = tool_func(**func_args)
                        except Exception as e:
                            result = f"Tool {func_name} error: {e}"
                    else:
                        result = f"Tool {func_name} not found, Sir."
                    
                    tool_result_msg = {"role": "tool", "content": str(result)}
                    self.messages.append(tool_result_msg)
                    working_messages.append(tool_result_msg)
                
                if iteration == max_tool_iterations:
                    response = self._call_ollama_chat(messages=working_messages, tools=None, stream=False)
                    final_response = response.get("message", {}).get("content", "I've completed the tasks, Sir.")
                    self.messages.append({"role": "assistant", "content": final_response})
                    self.conversation.add_message("assistant", final_response)
                    break
                
            except Exception as e:
                error_msg = f"I encountered an issue with my neural pathways, Sir: {e}"
                print(error_msg)
                final_response = error_msg
                self.messages.append({"role": "assistant", "content": final_response})
                break
        
        latency = int((time.time() - start_time)*1000)
        
        # Learning
        if self.learning_enabled and self.learning_engine:
            try:
                self.learning_engine.learn_from_interaction(user_message=user_input, assistant_response=final_response, conversation=self.messages[-10:])
            except Exception as e:
                print(f"Learning trigger failed: {e}")
        
        # Evolution - self-critique and improve
        if self.evolution_enabled and self.evolution_engine:
            try:
                self.evolution_engine.evaluate_interaction(
                    user_input=user_input,
                    assistant_response=final_response,
                    tool_calls=tool_calls_made,
                    latency_ms=latency
                )
            except Exception as e:
                print(f"Evolution trigger failed: {e}")
        
        return final_response
    
    def think_stream(self, user_input: str) -> Generator[str, None, None]:
        start_time = time.time()
        messages_with_context = self._build_messages_with_context(user_input)
        self.messages.append({"role": "user", "content": user_input})
        messages_with_context.append({"role": "user", "content": user_input})
        self.conversation.add_message("user", user_input)
        
        full_response = ""
        tool_calls_made = []
        try:
            check_resp = self._call_ollama_chat(messages=messages_with_context, tools=TOOLS_SCHEMA, stream=False)
            msg = check_resp.get("message", {})
            tool_calls = msg.get("tool_calls", [])
            
            if tool_calls:
                working = messages_with_context
                working.append(msg)
                self.messages.append(msg)
                tool_calls_made.extend(tool_calls)
                
                for tc in tool_calls:
                    func_info = tc.get("function", {})
                    func_name = func_info.get("name")
                    func_args = func_info.get("arguments", {})
                    if isinstance(func_args, str):
                        try:
                            func_args = json.loads(func_args)
                        except:
                            func_args = {}
                    
                    tool_func = TOOL_MAP.get(func_name)
                    if tool_func:
                        try:
                            result = tool_func(**func_args)
                            yield f"\n[Using tool: {func_name}]\n"
                        except Exception as e:
                            result = f"Error: {e}"
                            yield f"\n[Tool error: {e}]\n"
                    else:
                        result = f"Tool {func_name} not found"
                    
                    tool_msg = {"role": "tool", "content": str(result)}
                    working.append(tool_msg)
                    self.messages.append(tool_msg)
                    
                    for chunk in self._call_ollama_chat_stream(working, tools=None):
                        full_response += chunk
                        yield chunk
                    
                    self.messages.append({"role": "assistant", "content": full_response})
                    self.conversation.add_message("assistant", full_response)
                    
                    if self.learning_enabled and self.learning_engine:
                        self.learning_engine.learn_from_interaction(user_message=user_input, assistant_response=full_response, conversation=self.messages[-10:])
                    if self.evolution_enabled and self.evolution_engine:
                        latency = int((time.time()-start_time)*1000)
                        self.evolution_engine.evaluate_interaction(user_input, full_response, tool_calls_made, latency)
                    return
            
            for chunk in self._call_ollama_chat_stream(messages_with_context, tools=None):
                full_response += chunk
                yield chunk
            
            self.messages.append({"role": "assistant", "content": full_response})
            self.conversation.add_message("assistant", full_response)
            
            if self.learning_enabled and self.learning_engine:
                self.learning_engine.learn_from_interaction(user_message=user_input, assistant_response=full_response, conversation=self.messages[-10:])
            if self.evolution_enabled and self.evolution_engine:
                latency = int((time.time()-start_time)*1000)
                self.evolution_engine.evaluate_interaction(user_input, full_response, tool_calls_made, latency)
            
        except Exception as e:
            err = f"Neural link disrupted, Sir: {e}"
            yield err
    
    def add_feedback(self, feedback: str, message_text: str = None):
        if self.learning_enabled and self.learning_engine:
            self.learning_engine.add_feedback(feedback=feedback, message_text=message_text)
        if self.evolution_enabled and self.evolution_engine:
            try:
                # Map feedback to satisfaction
                satis = 0.8 if feedback == "positive" else 0.2 if feedback == "negative" else 0.5
                self.evolution_engine.tracker.record(
                    user_input=f"feedback: {feedback}",
                    response=message_text or "",
                    latency_ms=0,
                    tool_calls=[],
                    tool_success=1.0,
                    satisfaction=satis
                )
            except:
                pass
    
    def improve_self(self, instruction: str = "") -> Dict:
        if self.evolution_enabled and self.evolution_engine:
            return self.evolution_engine.manual_evolution(instruction)
        return {"error": "Evolution not enabled"}
    
    def get_evolution_status(self) -> Dict:
        if self.evolution_enabled and self.evolution_engine:
            return self.evolution_engine.get_status()
        return {"error": "Evolution not enabled"}
    
    def set_personality(self, prompt: str):
        self.base_system_prompt = prompt
        self.system_prompt = prompt
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = prompt
        else:
            self.messages.insert(0, {"role": "system", "content": prompt})
    
    def clear_memory(self):
        self._init_messages()
        self.conversation.clear()
    
    def clear_all(self):
        self.clear_memory()
        if self.learning_enabled and self.learning_engine:
            self.learning_engine.clear_all_learnings()
    
    def get_status(self) -> Dict:
        status = {
            "model": self.model,
            "host": self.host,
            "ollama_connected": self._is_ollama_up(),
            "conversation_length": len(self.messages),
            "memory_count": len(self.memory.get_all_memories()),
            "learning_enabled": self.learning_enabled,
            "evolution_enabled": self.evolution_enabled
        }
        if self.learning_enabled and self.learning_engine:
            try:
                status["vector_count"] = len(self.learning_engine.vector_store.vectors)
                status["profile"] = self.learning_engine.user_profile.get()
                status["learnings_count"] = len(self.learning_engine.vector_store.vectors)
                status["satisfaction"] = self.learning_engine.user_profile.profile["interaction_stats"].get("satisfaction_score", 0.5)
            except:
                pass
        if self.evolution_enabled and self.evolution_engine:
            try:
                evo_status = self.evolution_engine.get_status()
                status["evolution_count"] = evo_status["evolution_count"]
                status["avg_critic_score"] = evo_status.get("avg_critic_score")
                status["should_evolve"] = evo_status.get("should_evolve")
                status["trend"] = evo_status.get("stats", {}).get("trend")
            except:
                pass
        return status
    
    def _is_ollama_up(self) -> bool:
        try:
            requests.get(f"{self.host}/api/tags", timeout=2)
            return True
        except:
            return False
