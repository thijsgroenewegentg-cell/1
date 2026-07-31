"""
Base Agent - Foundation for all specialized agents
Each agent has its own personality, tools, and expertise
"""

from typing import List, Dict, Optional
from ..config import config
from ..brain import JarvisBrain


class BaseAgent:
    def __init__(self, name: str, role: str, system_prompt: str, brain: JarvisBrain = None, tools: List[str] = None):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.brain = brain or JarvisBrain()
        self.tools = tools  # subset of tools allowed, None = all
        
        # Override brain's system prompt for this agent
        self.brain.set_personality(system_prompt)
        
        self.memory = []  # agent's own conversation memory
        self.stats = {"tasks_completed": 0, "avg_score": 0}
    
    def think(self, task: str, context: str = "") -> str:
        """
        Agent thinks about task with its specialized personality
        """
        full_prompt = task
        if context:
            full_prompt = f"Context:\n{context[:3000]}\n\nTask: {task}"
        
        # Use brain but with agent's personality already set
        try:
            response = self.brain.think(full_prompt)
            self.memory.append({"role": "user", "content": task})
            self.memory.append({"role": "assistant", "content": response})
            if len(self.memory) > 20:
                self.memory = self.memory[-20:]
            return response
        except Exception as e:
            return f"Agent {self.name} failed, Sir: {e}"
    
    def get_status(self) -> Dict:
        return {
            "name": self.name,
            "role": self.role,
            "tasks_completed": self.stats["tasks_completed"],
            "memory_length": len(self.memory)
        }
