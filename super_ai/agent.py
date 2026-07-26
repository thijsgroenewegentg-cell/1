from .memory import Memory
from .reflection import ReflectionEngine
from .tools import ToolRegistry


class SuperAgent:
    """
    An autonomous agent framework. It is NOT an AGI.
    It uses structured loops (observe -> plan -> act -> reflect)
    to approximate autonomous behavior.
    """

    def __init__(self, name: str = "SuperAgent"):
        self.name = name
        self.memory = Memory()
        self.reflection = ReflectionEngine(self.memory)
        self.tools = ToolRegistry()
        self.running = True

    def observe(self) -> str:
        # In a real LLM-backed agent, this would read user input / environment.
        # Here we expose a simple observation hook.
        return self.memory.get_preference("last_observation", "No observation yet.")

    def plan(self, goal: str) -> list:
        # In a real agent, an LLM would generate this plan.
        # We return a structured template.
        available = self.tools.list_available()
        return [
            f"Understand goal: {goal}",
            f"Select from available tools: {available}",
            "Execute step-by-step",
            "Reflect on outcome",
        ]

    def act(self, goal: str) -> dict:
        # Example autonomous action: list workspace and log it.
        results = []
        results.append(self.tools.call("list_dir"))
        results.append(self.memory.get_preference("last_goal", goal))
        self.memory.add("action", {"goal": goal, "results_summary": results}, outcome="success")
        return {"results": results, "goal_completed": False, "note": "Requires external LLM for full autonomy."}

    def loop(self, goal: str = "Be helpful and autonomous"):
        """Single reflection loop demonstrating autonomy structure."""
        print(f"[Agent] Starting loop for goal: {goal}")
        plan = self.plan(goal)
        print(f"[Agent] Plan: {plan}")
        outcome = self.act(goal)
        reflection = self.reflection.reflect(goal, ["observe", "plan", "act"])
        print(f"[Agent] Reflection: success_rate={reflection['success_rate']}, suggestion={reflection['suggestion']}")
        print(f"[Agent] Outcome: {outcome}")
        return {"plan": plan, "outcome": outcome, "reflection": reflection}

    def learn_preference(self, interaction_result: dict):
        # Basic adaptive preference: if failures exceed successes, prefer simpler actions.
        failures = interaction_result.get("failures", 0)
        successes = interaction_result.get("successes", 0)
        if failures > successes:
            self.memory.update_preference("preferred_strategy", "conservative")
        else:
            self.memory.update_preference("preferred_strategy", "aggressive")
