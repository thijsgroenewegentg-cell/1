"""
Enhanced Autonomous Loop using the smartest Ollama model.
This is NOT consciousness — it is a structured agent loop powered by LLM reasoning.
"""
from .memory import Memory
from .reflection import ReflectionEngine
from .tools import ToolRegistry
from .ollama_client import OllamaLLM
import json


class SuperAgentFull:
    """
    The complete agent: memory + reflection + tools + LLM reasoning + web + autonomous loops.
    """

    def __init__(self, name: str = "SuperAgent", model: str = None):
        self.name = name
        self.memory = Memory()
        self.reflection = ReflectionEngine(self.memory)
        self.tools = ToolRegistry()
        self.llm = OllamaLLM(model=model)
        self.running = True
        self.system_prompt = (
            "You are an autonomous AI agent. You have access to tools: "
            f"{self.tools.list_available()}. You also have persistent memory. "
            "Be helpful, accurate, and reflect on your actions. You are NOT conscious. "
            "You are a highly capable assistant framework powered by an LLM backend. "
            "Always consider safety and user intent."
        )

    def observe(self) -> dict:
        # Structured observation with LLM if available
        if self.llm.is_available():
            try:
                observation_text = self.memory.get_preference("last_observation", "No recent observation in memory.")
                prompt = (
                    f"Given this agent memory observation: '{observation_text}', "
                    "summarize the agent's current state in one sentence. "
                    "Respond as JSON with keys: 'summary', 'priority'."
                )
                response = self.llm.generate(prompt, system="You summarize agent state concisely.")
                # Try to parse JSON response
                try:
                    data = json.loads(response)
                    return data
                except Exception:
                    return {"summary": response, "priority": "unknown"}
            except Exception:
                pass
        return {"summary": self.memory.get_preference("last_observation", "No observation"), "priority": "unknown"}

    def plan(self, goal: str) -> list:
        available = self.tools.list_available()
        base_plan = [
            f"Understand goal: {goal}",
            f"Select relevant tools from: {available}",
            "Execute actions step by step",
            "Reflect on results and update memory",
        ]
        if self.llm.is_available():
            try:
                prompt = (
                    f"You are an autonomous agent with goal: '{goal}'. "
                    f"Available tools: {available}. "
                    f"Generate a concise step-by-step plan (max 5 steps) as a JSON array of strings."
                )
                response = self.llm.generate(prompt, system="You create structured agent plans.")
                try:
                    parsed = json.loads(response)
                    if isinstance(parsed, list):
                        return parsed
                except Exception:
                    pass
            except Exception:
                pass
        return base_plan

    def act(self, goal: str) -> dict:
        # Enhanced action with LLM reasoning
        results = []
        actions = ["observe", "plan"]

        # Try to get LLM to choose a tool
        chosen_tool = None
        if self.llm.is_available():
            try:
                prompt = (
                    f"Agent goal: '{goal}'. Tools: {self.tools.list_available()}. "
                    "Which single tool is most appropriate right now? Respond with just the tool name, no explanation."
                )
                response = self.llm.generate(prompt, system="You choose agent tools concisely.")
                clean = response.strip().split()[0].strip('.,')
                if clean in self.tools.list_available():
                    chosen_tool = clean
            except Exception:
                pass

        if chosen_tool == "read_file":
            results.append(self.tools.call("read_file", path="README.md"))
            actions.append("read_file(README.md)")
        elif chosen_tool == "list_dir":
            results.append(self.tools.call("list_dir"))
            actions.append("list_dir()")
        elif chosen_tool == "bash":
            results.append(self.tools.call("bash", command="pwd && echo 'Agent is autonomous'"))
            actions.append("bash(pwd)")
        elif chosen_tool == "evaluate_code":
            results.append(self.tools.call("evaluate_code", code="print('Agent running')"))
            actions.append("evaluate_code()")
        else:
            # Default autonomous behavior
            results.append(self.tools.call("list_dir"))
            results.append(self.memory.get_preference("last_goal", goal))
            actions.append("list_dir()")

        # Ensure chosen_tool is set correctly
        if chosen_tool is None:
            chosen_tool = "default"
        self.memory.add("action", {"goal": goal, "results_summary": results, "chosen_tool": chosen_tool}, outcome="success")
        return {"results": results, "goal_completed": False, "chosen_tool": chosen_tool, "note": "Requires LLM for full autonomy; running best-effort with available backend."}

    def loop(self, goal: str = "Be helpful, autonomous, and safe"):
        print(f"[Agent] Starting autonomous loop: {goal}")
        print(f"[Agent] LLM available: {self.llm.is_available()} (model: {self.llm.model})")

        observation = self.observe()
        print(f"[Agent] Observation: {observation}")

        plan = self.plan(goal)
        print(f"[Agent] Plan: {plan}")

        outcome = self.act(goal)
        print(f"[Agent] Action completed. Tool used: {outcome.get('chosen_tool') or 'default'}")

        reflection = self.reflection.reflect(goal, ["observe", "plan", "act"])
        print(f"[Agent] Reflection: rate={reflection['success_rate']}, suggestion={reflection['suggestion']}")

        # Update preferences based on outcome
        if outcome.get("results") and any("error" in str(r) for r in outcome.get("results", [])):
            self.memory.update_preference("preferred_strategy", "conservative")
        else:
            self.memory.update_preference("preferred_strategy", "aggressive")
        self.memory.update_preference("last_goal", goal)
        self.memory.update_preference("last_observation", str(observation))

        return {
            "goal": goal,
            "observation": observation,
            "plan": plan,
            "outcome": outcome,
            "reflection": reflection,
            "model": self.llm.model,
            "llm_available": self.llm.is_available(),
        }
