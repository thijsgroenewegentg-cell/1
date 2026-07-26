from .memory import Memory
from typing import List, Dict, Any


class ReflectionEngine:
    """Self-evaluation loop. Not consciousness — just structured meta-analysis."""

    def __init__(self, memory: Memory):
        self.memory = memory

    def reflect(self, goal: str, actions_taken: List[str]) -> Dict[str, Any]:
        # Basic heuristic reflection based on memory outcomes
        recent = self.memory.recall("action", n=20)
        successes = sum(1 for r in recent if r.get("outcome") == "success")
        failures = sum(1 for r in recent if r.get("outcome") == "failure")
        total = len(recent)
        rate = successes / max(total, 1)

        reflection = {
            "goal": goal,
            "success_rate": rate,
            "successes": successes,
            "failures": failures,
            "suggestion": self._suggest(rate, failures),
        }
        self.memory.add("reflection", reflection, outcome="info")
        return reflection

    def _suggest(self, rate: float, failures: int) -> str:
        if rate < 0.3:
            return "Strategy failing repeatedly. Consider different approach or ask for clarification."
        elif rate < 0.7:
            return "Mixed results. Analyze which actions succeed and replicate patterns."
        else:
            return "Good success rate. Maintain current strategy."
