#!/usr/bin/env python3
"""
Super AI Assistant Web Interface
Runs with Flask. Provides chat, autonomous mode, file browser, and reflection view.
"""
import sys
import os
sys.path.insert(0, "/home/user/1")

from flask import Flask, render_template_string, request, jsonify
from super_ai.full_agent import SuperAgentFull
from super_ai.ollama_client import OllamaLLM

app = Flask(__name__)
agent = None

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Super AI Assistant</title>
<style>
body { font-family: system-ui, sans-serif; background: #0b0c15; color: #e0e6ed; margin: 0; padding: 2rem; }
h1 { color: #00d4aa; }
.card { background: #13152a; border-radius: 12px; padding: 1.5rem; margin: 1rem 0; box-shadow: 0 4px 30px rgba(0,0,0,.4); }
input, textarea, button { font-size: 1rem; padding: .6rem .8rem; border-radius: 8px; border: none; margin: .3rem .2rem; }
input, textarea { background: #1a1d2e; color: #e0e6ed; width: 60%; }
button { background: #00d4aa; color: #0b0c15; cursor: pointer; font-weight: bold; }
button:hover { background: #00b894; }
pre { background: #0d0e14; padding: 1rem; border-radius: 8px; overflow-x: auto; }
.status { font-size: .9rem; color: #aaa; }
</style>
</head>
<body>
<h1>🤖 Super AI Assistant</h1>
<p class="status">Model: {{ model }} | LLM Available: {{ llm_available }} | Memory Entries: {{ memory_count }}</p>

<div class="card">
<h2>Autonomous Loop</h2>
<form method="post" action="/loop">
<input type="text" name="goal" placeholder="Enter autonomous goal (e.g. 'Analyze workspace and summarize')" value="Analyze workspace and summarize" style="width: 70%">
<button type="submit">Run Autonomous Loop</button>
</form>
</div>

<div class="card">
<h2>Chat / Reasoning</h2>
<form method="post" action="/chat">
<textarea name="message" rows="3" placeholder="Ask the super AI anything..." style="width: 70%">Analyze this workspace and suggest improvements.</textarea><br>
<button type="submit">Send to Smartest Ollama Model</button>
</form>
</div>

<div class="card">
<h2>Memory</h2>
<pre>{{ memory }}</pre>
</div>

<div class="card">
<h2>Reflection</h2>
<pre>{{ reflection }}</pre>
</div>

<div class="card">
<h2>Autonomous Results</h2>
<pre>{{ loop_result }}</pre>
</div>
</body>
</html>
'''

@app.route("/")
def index():
    global agent
    if agent is None:
        agent = SuperAgentFull()
    memory = agent.memory.recall(n=10)
    reflection = agent.reflection.reflect("Web interface session", ["load"])
    return render_template_string(
        HTML_TEMPLATE,
        model=agent.llm.model,
        llm_available=str(agent.llm.is_available()),
        memory_count=len(agent.memory.episodic),
        memory=str(memory)[:3000],
        reflection=str(reflection),
        loop_result="",
    )

@app.route("/loop", methods=["POST"])
def loop():
    global agent
    if agent is None:
        agent = SuperAgentFull()
    goal = request.form.get("goal", "Analyze workspace")
    result = agent.loop(goal)
    return render_template_string(
        HTML_TEMPLATE,
        model=agent.llm.model,
        llm_available=str(agent.llm.is_available()),
        memory_count=len(agent.memory.episodic),
        memory=str(agent.memory.recall(n=10))[:3000],
        reflection=str(result.get("reflection", {})),
        loop_result=str(result)[:4000],
    )

@app.route("/chat", methods=["POST"])
def chat():
    global agent
    if agent is None:
        agent = SuperAgentFull()
    message = request.form.get("message", "Hello")
    system = agent.system_prompt
    response_text = agent.llm.generate(message, system=system)
    # Save interaction
    agent.memory.add("chat", {"user": message, "agent": response_text}, outcome="info")
    reflection = agent.reflection.reflect("Chat interaction", ["chat"])
    return render_template_string(
        HTML_TEMPLATE,
        model=agent.llm.model,
        llm_available=str(agent.llm.is_available()),
        memory_count=len(agent.memory.episodic),
        memory=str(agent.memory.recall(n=10))[:3000],
        reflection=str(reflection),
        loop_result=f"Response: {response_text}\n\nAgent Reflection: {str(reflection)}",
    )

@app.route("/api/status")
def api_status():
    if agent is None:
        return jsonify({"status": "agent not initialized"})
    return jsonify({
        "name": agent.name,
        "model": agent.llm.model,
        "llm_available": agent.llm.is_available(),
        "memory_entries": len(agent.memory.episodic),
        "preferences": agent.memory.preferences,
    })

if __name__ == "__main__":
    print("Starting Super AI Web Assistant on http://localhost:5000")
    print("NOTE: Ensure ollama server is running with the smartest model pulled.")
    app.run(host="0.0.0.0", port=5000, debug=True)
