"""
JARVIS Examples - Try these prompts

Run: python cli.py
Then try:
"""

EXAMPLES = [
    {
        "category": "Basic",
        "prompts": [
            "Jarvis, what time is it?",
            "Jarvis, are you there?",
            "What's the weather in Tokyo?",
            "Tell me a joke, Jarvis",
            "Who are you really?",
        ]
    },
    {
        "category": "Memory",
        "prompts": [
            "Remember that my birthday is December 25th",
            "Remember my favorite color is blue and I like Iron Man",
            "What do you remember about me?",
            "Remember that my project deadline is next Friday",
        ]
    },
    {
        "category": "System",
        "prompts": [
            "What's your system status?",
            "Check CPU and RAM usage",
            "List files in workspace",
            "Create a Python file that prints hello world",
        ]
    },
    {
        "category": "Search & Knowledge",
        "prompts": [
            "Search web for latest SpaceX launch",
            "What is the latest version of Python?",
            "Search for Tony Stark arc reactor",
        ]
    },
    {
        "category": "Code",
        "prompts": [
            "Write a Python function to calculate fibonacci",
            "Execute Python code: print(sum([1,2,3,4,5]))",
            "Create a file called notes.txt with my ideas for a new Stark suit",
        ]
    },
    {
        "category": "Personality",
        "prompts": [
            "Jarvis, what do you think about being in a computer?",
            "Are you better than Siri?",
            "Jarvis, initiate suit-up sequence",
            "Thank you, Jarvis",
        ]
    }
]

if __name__ == "__main__":
    for cat in EXAMPLES:
        print(f"\n=== {cat['category']} ===")
        for p in cat['prompts']:
            print(f"  - {p}")

# For testing brain without Ollama running - mock responses
MOCK_RESPONSES = {
    "what time is it": "It's {time}, Sir. Time to build something amazing, I'd say.",
    "hello": "Hello, Sir. Systems online and ready. How may I assist?",
    "who are you": "I am J.A.R.V.I.S, Just A Rather Very Intelligent System. Built by Stark, now serving you, Sir.",
}
