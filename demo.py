#!/usr/bin/env python3
"""Run a quick demo of the agent framework."""
import sys
sys.path.insert(0, "/home/user/1")

from super_ai.agent import SuperAgent

agent = SuperAgent()
print("Agent created.")
print("Memory loaded:", len(agent.memory.episodic))
print("Tools available:", agent.tools.list_available())
print("Reflection engine ready.")
agent.loop()
