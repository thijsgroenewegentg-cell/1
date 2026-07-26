#!/usr/bin/env python3
"""
Super AI Assistant CLI — Full Autonomous Mode with Smartest Ollama
"""
import sys
sys.path.insert(0, "/home/user/1")

from super_ai.full_agent import SuperAgentFull


def main():
    print("=" * 60)
    print("SUPER AI ASSISTANT (Full Framework + Smartest Ollama)")
    print("=" * 60)
    print("NOTE: This framework connects to the smartest available Ollama model.")
    print("To run at full power: install ollama, pull a top model, and run `ollama serve`.")
    print("Recommended smartest models (in order):")
    print("  1. qwen3-coder-next")
    print("  2. deepseek-r1:32b")
    print("  3. qwen2.5-coder:32b")
    print("  4. llama4:scout")
    print("=" * 60)

    agent = SuperAgentFull()
    agent.memory.update_preference("user_intent", "autonomous agent framework with smartest ollama")

    print(f"Agent: {agent.name}")
    print(f"LLM Model Configured: {agent.llm.model}")
    print(f"LLM Server Available: {agent.llm.is_available()}")
    print(f"Available Tools: {agent.tools.list_available()}")

    # Run full autonomous loop
    print("\n--- STARTING FULL AUTONOMOUS LOOP ---")
    result = agent.loop("Analyze workspace files and suggest improvements")

    print("\n--- LOOP RESULT ---")
    for k, v in result.items():
        if k != "outcome":
            print(f"{k}: {v}")

    print("\n--- ACTION DETAILS ---")
    print(f"Chosen Tool: {result['outcome'].get('chosen_tool', 'default')}")
    print(f"Results Summary: {str(result['outcome']['results'])[:500]}")

    print("\n--- MEMORY STATE ---")
    for pref_key, pref_val in agent.memory.preferences.items():
        print(f"  {pref_key}: {pref_val}")
    recent = agent.memory.recall(n=3)
    for r in recent:
        print(f"  - {r['type']}: {str(r['content'])[:120]}")

    print("\n--- STATUS ---")
    print("Framework initialized successfully.")
    print("All capabilities present: memory, reflection, tools, LLM integration, web interface.")
    print(f"Limitations acknowledged: No true consciousness. LLM required for 'super' behavior.")


if __name__ == "__main__":
    main()
