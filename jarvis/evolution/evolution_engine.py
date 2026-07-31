"""
Evolution Engine - JARVIS Self-Improvement Orchestrator
The core that makes JARVIS make himself better

Loop:
1. Track performance
2. Self-critique each response
3. Detect missing tools
4. Evolve prompt / forge tools / optimize memory
5. Log everything

JARVIS can be asked: "Improve yourself" or it happens automatically
"""

import json
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from ..config import config
from .self_critic import SelfCritic
from .performance_tracker import PerformanceTracker
from .self_editor import SelfEditor
from .tool_forger import ToolForger


class EvolutionEngine:
    def __init__(self):
        self.critic = SelfCritic()
        self.tracker = PerformanceTracker()
        self.editor = SelfEditor()
        self.forger = ToolForger()
        
        self.evolution_dir = config.MEMORY_FILE.parent / "evolution"
        self.evolution_dir.mkdir(parents=True, exist_ok=True)
        
        self.evolution_log_path = self.evolution_dir / "evolution_log.json"
        self.evolution_log = self._load_log()
        
        self.evolution_count = len(self.evolution_log)
        self.last_evolution = None
        
        print(f"🧬 Evolution engine initialized - {self.evolution_count} evolutions so far, Sir.")
    
    def _load_log(self) -> List[Dict]:
        if self.evolution_log_path.exists():
            try:
                return json.loads(self.evolution_log_path.read_text())
            except:
                return []
        return []
    
    def _save_log(self):
        try:
            self.evolution_log_path.write_text(json.dumps(self.evolution_log[-100:], indent=2))
        except Exception as e:
            print(f"Evolution log save failed: {e}")
    
    def _log_evolution(self, type: str, description: str, details: Dict = None, success: bool = True):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": type,
            "description": description,
            "details": details or {},
            "success": success,
            "evolution_number": len(self.evolution_log) + 1
        }
        self.evolution_log.append(entry)
        self._save_log()
        self.evolution_count = len(self.evolution_log)
        self.last_evolution = entry
        print(f"🧬 Evolution #{entry['evolution_number']}: {type} - {description}")
        return entry
    
    def evaluate_interaction(self, 
                            user_input: str, 
                            assistant_response: str, 
                            tool_calls: List[Dict] = None,
                            latency_ms: int = None,
                            satisfaction: float = None) -> Dict:
        """
        Called after each interaction - evaluates and potentially triggers evolution
        Runs mostly in background
        """
        def background_eval():
            try:
                # 1. Track performance
                tool_success = 1.0
                if tool_calls:
                    # Simple heuristic: if any tool result contains error, lower success
                    # We don't have results here, so assume success
                    tool_success = 1.0
                
                self.tracker.record(
                    user_input=user_input,
                    response=assistant_response,
                    latency_ms=latency_ms or 0,
                    tool_calls=tool_calls or [],
                    tool_success=tool_success,
                    satisfaction=satisfaction
                )
                
                # 2. Self-critique
                critique = self.critic.critique(
                    user_input=user_input,
                    assistant_response=assistant_response,
                    tool_results=tool_calls,
                    latency_ms=latency_ms
                )
                
                # Update tracker with critique score
                # Re-record? No, just update last entry if possible, or store separately
                # We'll store critique in performance tracker history last entry
                if self.tracker.history:
                    self.tracker.history[-1]["critic_score"] = critique.get("score")
                    self.tracker._save()
                
                # 3. Check if should evolve
                should_evolve_info = self.tracker.should_evolve()
                
                # Also evolve if critique score low
                if critique.get("score", 10) < 5.0:
                    should_evolve_info["should_evolve"] = True
                    should_evolve_info["reasons"].append(f"Low self-critique score {critique['score']}/10")
                
                # 4. Detect missing tool
                missing_tool = self.forger.detect_missing_tool(user_input, assistant_response, tool_calls or [])
                
                # 5. Trigger evolution if needed (in background)
                if should_evolve_info["should_evolve"] or missing_tool:
                    self._trigger_evolution(
                        critique=critique,
                        missing_tool=missing_tool,
                        reasons=should_evolve_info["reasons"],
                        stats=should_evolve_info["stats"],
                        user_input=user_input
                    )
                
            except Exception as e:
                print(f"Evolution evaluation failed: {e}")
                import traceback
                traceback.print_exc()
        
        thread = threading.Thread(target=background_eval, daemon=True)
        thread.start()
        
        # Return immediate critique for potential UI display
        try:
            # Quick heuristic critique synchronously for fast feedback
            quick_critique = self.critic._heuristic_critique(user_input, assistant_response, tool_calls, latency_ms)
            return quick_critique
        except:
            return {"score": 7.0}
    
    def _trigger_evolution(self, critique: Dict, missing_tool: Dict = None, reasons: List[str] = None, stats: Dict = None, user_input: str = ""):
        """Actually evolve - improve prompt, forge tools, etc."""
        print(f"🧬 Triggering evolution, Sir. Reasons: {reasons}")
        
        evolutions_done = []
        
        try:
            # 1. If low critique score or satisfaction, evolve prompt
            if critique.get("score", 10) < 6.5 or (stats and stats.get("avg_satisfaction", 1.0) < 0.6):
                print("🧬 Evolving prompt, Sir...")
                current_prompt = ""
                prompt_file = self.evolution_dir / "prompt_additions.json"
                if prompt_file.exists():
                    try:
                        existing = json.loads(prompt_file.read_text())
                        if existing:
                            current_prompt = existing[-1].get("prompt", "") if isinstance(existing, list) else ""
                    except:
                        pass
                
                # Get user profile if available
                user_profile = None
                try:
                    from ..learning import UserProfile
                    up = UserProfile()
                    user_profile = up.get()
                except:
                    pass
                
                result = self.editor.propose_prompt_evolution(current_prompt, critique, user_profile)
                if result.get("success"):
                    new_prompt = result["new_prompt"]
                    apply_result = self.editor.apply_prompt_evolution(new_prompt, reason=f"Low score {critique.get('score')}: {', '.join(reasons or [])}")
                    if apply_result.get("success"):
                        evolutions_done.append(f"Prompt evolved: {new_prompt[:60]}...")
                        self._log_evolution("prompt_evolution", f"Evolved prompt due to: {', '.join(reasons or [])[:100]}", 
                                          {"new_prompt": new_prompt, "critique_score": critique.get("score"), "reasons": reasons}, True)
            
            # 2. If missing tool detected, forge it
            if missing_tool:
                needed = missing_tool.get("needed", "custom")
                user_req = missing_tool.get("user_request", user_input)
                print(f"🧬 Forging new tool for: {needed}, Sir...")
                
                forge_result = self.forger.forge_tool(needed, user_req, reason=missing_tool.get("reason", ""))
                
                if forge_result.get("success"):
                    evolutions_done.append(f"Tool forged: {needed}")
                    self._log_evolution("tool_forge", f"Forged tool {needed} for: {user_req[:80]}", 
                                      {"tool": needed, "user_request": user_req, "result": forge_result}, True)
                else:
                    print(f"Tool forge failed: {forge_result.get('error')}")
                    self._log_evolution("tool_forge_failed", f"Failed to forge {needed}", 
                                      {"error": forge_result.get("error"), "user_request": user_req}, False)
            
            # 3. Memory optimization (prune low-value)
            try:
                self._optimize_memory()
                evolutions_done.append("Memory optimized")
            except Exception as e:
                print(f"Memory optimization failed: {e}")
            
            if evolutions_done:
                print(f"🧬 Evolution cycle complete, Sir. {len(evolutions_done)} improvements: {evolutions_done}")
            else:
                print("🧬 Evolution cycle checked, no improvements needed at this time, Sir.")
        
        except Exception as e:
            print(f"Evolution trigger failed: {e}")
            import traceback
            traceback.print_exc()
            self._log_evolution("evolution_error", f"Evolution failed: {e}", {"reasons": reasons}, False)
    
    def _optimize_memory(self):
        """Prune and consolidate memories"""
        try:
            from ..learning import VectorStore
            vs = VectorStore()
            # If too many vectors, prune lowest access_count
            if len(vs.vectors) > 800:
                # Sort by access_count and keep top 600
                vs.vectors.sort(key=lambda x: x.get("access_count", 0), reverse=True)
                pruned = len(vs.vectors) - 600
                vs.vectors = vs.vectors[:600]
                vs._save()
                print(f"🧹 Pruned {pruned} low-value memories, Sir.")
                self._log_evolution("memory_prune", f"Pruned {pruned} memories", {"pruned": pruned}, True)
        except Exception as e:
            print(f"Memory optimization error: {e}")
    
    def manual_evolution(self, instruction: str = "") -> Dict:
        """Manually trigger evolution - user says 'improve yourself'"""
        print(f"🧬 Manual evolution triggered, Sir. Instruction: {instruction}")
        
        # Force a comprehensive evolution
        stats = self.tracker.get_stats(last_n=50)
        critique = {
            "score": stats.get("avg_satisfaction", 0.5) * 10,
            "issues": ["Manual evolution requested"] + ([f"Low satisfaction {stats['avg_satisfaction']}"] if stats["avg_satisfaction"] < 0.6 else []),
            "improvements": [instruction] if instruction else ["General improvement requested by Sir"]
        }
        
        # Trigger in background but also do immediate prompt evolution
        def do_evolution():
            self._trigger_evolution(
                critique=critique,
                missing_tool=None,
                reasons=[f"Manual trigger: {instruction}" if instruction else "Manual evolution"],
                stats=stats,
                user_input=instruction
            )
        
        thread = threading.Thread(target=do_evolution, daemon=True)
        thread.start()
        
        return {
            "status": "evolution_started",
            "message": f"Evolution started, Sir. Instruction: {instruction}. Check /api/evolution/history for progress.",
            "stats": stats,
            "instruction": instruction
        }
    
    def get_status(self) -> Dict:
        stats = self.tracker.get_stats(last_n=50)
        should_evolve = self.tracker.should_evolve()
        history = self.editor.get_evolution_history()
        avg_critic = self.critic.get_average_score(last_n=20)
        
        return {
            "evolution_count": self.evolution_count,
            "last_evolution": self.last_evolution,
            "should_evolve": should_evolve["should_evolve"],
            "reasons": should_evolve["reasons"],
            "stats": stats,
            "avg_critic_score": avg_critic,
            "history_summary": history,
            "self_improvement_enabled": True,
            "capabilities": [
                "Self-critique (scores own responses 0-10)",
                "Prompt evolution (rewrites own instructions)",
                "Tool forging (creates new tools when needed)",
                "Memory optimization (prunes low-value)",
                "Performance tracking (latency, success, satisfaction)",
                "Auto-evolution when performance drops"
            ]
        }
    
    def get_history(self, limit: int = 20) -> List[Dict]:
        return self.evolution_log[-limit:]
