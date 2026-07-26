#!/usr/bin/env python3
"""
Full Demo of Super AI Assistant
Runs the full agent, shows LLM integration, reflection, memory, and web readiness.
"""
import sys
sys.path.insert(0, "/home/user/1")

from super_ai.full_agent import SuperAgentFull

def main():
    print("=== FULL SUPER AI DEMO ===")
    agent = SuperAgentFull()
    print(f"Agent: {agent.name}")
    print(f"Smartest Ollama Model Configured: {agent.llm.model}")
    print(f"LLM Server Reachable: {agent.llm.is_available()}")
    print(f"Available Tools: {agent.tools.list_available()}")

    # Demonstrate memory persistence
    agent.memory.add("startup", "Agent initialized with full framework", outcome="success")
    agent.memory.update_preference("mode", "autonomous")

    # Demonstrate reflection
    reflection = agent.reflection.reflect("Startup", ["init", "observe"])
    print(f"Startup Reflection: {reflection['suggestion']}")

    # Demonstrate autonomous loop
    print("\n--- Running Autonomous Loop ---")
    result = agent.loop("Read README.md and summarize workspace purpose")
    print(f"Plan used: {result['plan']}")
    print(f"Reflection rate: {result['reflection']['success_rate']}")

    # Show memory after loop
    print("\n--- Memory After Loop ---")
    for r in agent.memory.recall(n=5):
        print(f"  {r['type']} | outcome={r['outcome']} | time={r['timestamp']}")

    # Try LLM chat (will show whether server is available)
    print("\n--- LLM Chat Test ---")
    response = agent.llm.generate("What is this agent framework? Answer in one sentence.")
    print(f"LLM Response: {response[:300]}...")

    # Show web interface info
    print("\n--- Web Interface ---")
    print("Run: python -m super_ai.web_app")
    print("Visit: http://localhost:5000")

if __name__ == "__main__":
    main()
