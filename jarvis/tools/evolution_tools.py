"""
Evolution Tools - JARVIS can improve himself via tools
"""

from typing import Dict

_evolution_engine = None

def _get_evolution_engine():
    global _evolution_engine
    if _evolution_engine is None:
        try:
            from ..evolution import EvolutionEngine
            _evolution_engine = EvolutionEngine()
        except Exception as e:
            print(f"Evolution engine not available: {e}")
            _evolution_engine = None
    return _evolution_engine

def improve_self(instruction: str = "") -> str:
    """
    Trigger self-improvement / evolution cycle
    JARVIS analyzes his own performance and makes himself better
    """
    try:
        engine = _get_evolution_engine()
        if not engine:
            return "Evolution engine not available, Sir."
        
        result = engine.manual_evolution(instruction)
        status = engine.get_status()
        
        return f"""Self-improvement triggered, Sir. Evolution #{status.get('evolution_count', 0)+1}

Instruction: {instruction or 'General self-improvement'}
Stats: {status.get('stats', {})}
Reasons: {status.get('should_evolve')}? 

Status: {result.get('message', 'Evolution started in background')}
I will evolve my prompt, forge tools if needed, and optimize memory, Sir.

Check evolution history for results."""
    except Exception as e:
        return f"Self-improvement failed, Sir: {e}"

def create_new_tool(tool_name: str, description: str, purpose: str) -> str:
    """
    JARVIS forges a new tool for himself when he lacks capability
    """
    try:
        engine = _get_evolution_engine()
        if not engine:
            return "Evolution not available"
        
        # Forge the tool
        result = engine.forger.forge_tool(tool_name, purpose, reason=description)
        
        if result.get("success"):
            return f"Tool forged successfully, Sir! Created {tool_name} at {result.get('path')}. {result.get('message', '')} Restart may be needed to use it."
        else:
            return f"Tool forging failed, Sir: {result.get('error', 'unknown')}"
    except Exception as e:
        return f"Tool creation error: {e}"

def analyze_performance() -> str:
    """
    Analyze own performance and suggest improvements
    """
    try:
        engine = _get_evolution_engine()
        if not engine:
            return "Evolution engine not available"
        
        status = engine.get_status()
        stats = status.get("stats", {})
        should = status.get("should_evolve", False)
        reasons = status.get("reasons", [])
        
        critic_avg = status.get("avg_critic_score", 7.0)
        
        report = f"""Self-analysis report, Sir:

Performance (last 50):
- Total interactions: {stats.get('total_interactions', 0)}
- Avg latency: {stats.get('avg_latency', 0)}ms
- Success rate: {stats.get('success_rate', 1.0)*100:.1f}%
- Avg satisfaction: {stats.get('avg_satisfaction', 0.5)*100:.1f}%
- Avg self-critique: {critic_avg}/10
- Trend: {stats.get('trend', 'unknown')}
- Tool usage: {stats.get('tool_usage', {})}

Should evolve: {should}
Reasons: {', '.join(reasons) if reasons else 'None - performing well'}

Evolution count: {status.get('evolution_count', 0)}
Last evolution: {status.get('last_evolution', {}).get('timestamp', 'never')}

Capabilities:
{chr(10).join('- ' + c for c in status.get('capabilities', []))}

Sir, {'I should improve myself' if should else 'I am performing optimally, Sir.'}
"""
        return report
    except Exception as e:
        return f"Performance analysis failed: {e}"

def get_evolution_history(limit: int = 5) -> str:
    """Get history of self-improvements"""
    try:
        from ..evolution import SelfEditor
        editor = SelfEditor()
        history = editor.get_evolution_history()
        
        prompts = history.get("prompt_evolutions", [])[-limit:]
        tools = history.get("tool_forges", [])[-limit:]
        
        out = f"Evolution history (last {limit}), Sir:\n\n"
        
        out += "Prompt evolutions:\n"
        if not prompts:
            out += "- None yet\n"
        else:
            for p in prompts:
                out += f"- [{p.get('timestamp','')[:16]}] {p.get('prompt','')[:80]}... (reason: {p.get('reason','')[:60]})\n"
        
        out += "\nTool forges:\n"
        if not tools:
            out += "- None yet\n"
        else:
            for t in tools:
                out += f"- [{t.get('timestamp','')[:16]}] {t.get('tool_name','')}: {t.get('reason','')[:60]}\n"
        
        out += f"\nTotal evolutions: {history.get('total_evolutions', 0)}, Backups: {history.get('backup_count', 0)}"
        
        return out
    except Exception as e:
        return f"Failed to get evolution history: {e}"

def self_reflect() -> str:
    """Trigger self-reflection"""
    try:
        from ..learning import ReflectionEngine
        from ..learning import UserProfile
        from ..brain import JarvisBrain
        
        # Quick reflection via learning engine if available
        engine = _get_evolution_engine()
        if engine:
            # Also trigger learning reflection
            try:
                from ..learning import LearningEngine
                le = LearningEngine()
                insights = le.reflection_engine.reflect([], None)
                return f"Reflection complete, Sir: {insights}"
            except:
                pass
        
        # Fallback
        return "Reflecting on my performance, Sir... I am analyzing my recent interactions to learn and improve. Check /api/insights for detailed reflections."
    except Exception as e:
        return f"Reflection failed: {e}"
