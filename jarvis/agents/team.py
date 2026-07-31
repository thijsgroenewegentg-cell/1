"""
Agent Team - Multi-agent collaboration
JARVIS is a team: Planner, Researcher, Coder, Reviewer, Supervisor
They collaborate to solve complex tasks
"""

import time
from typing import List, Dict, Generator
from datetime import datetime

from ..config import config
from .supervisor import SupervisorAgent
from .planner import PlannerAgent
from .researcher import ResearcherAgent
from .coder import CoderAgent
from .reviewer import ReviewerAgent


class AgentTeam:
    def __init__(self, brain=None):
        # Share brain? Or separate brains with different prompts?
        # For simplicity, share brain but override personality per agent via set_personality
        # Better: each agent has own brain instance with its own personality
        from ..brain import JarvisBrain
        
        base_brain = brain or JarvisBrain()
        
        # Create agents - each with own brain copy to keep personalities separate
        # We create new brain instances to avoid prompt overriding
        self.supervisor = SupervisorAgent(brain=JarvisBrain(model=base_brain.model))
        self.planner = PlannerAgent(brain=JarvisBrain(model=base_brain.model))
        self.researcher = ResearcherAgent(brain=JarvisBrain(model=base_brain.model))
        self.coder = CoderAgent(brain=JarvisBrain(model=base_brain.model))
        self.reviewer = ReviewerAgent(brain=JarvisBrain(model=base_brain.model))
        
        self.agents = {
            "supervisor": self.supervisor,
            "planner": self.planner,
            "researcher": self.researcher,
            "coder": self.coder,
            "reviewer": self.reviewer
        }
        
        self.history = []
        print("👥 Multi-Agent Team initialized: Planner, Researcher, Coder, Reviewer, Supervisor - At your service, Sir.")
    
    def _emit(self, event_type: str, agent: str, data: Dict) -> Dict:
        event = {
            "type": event_type,
            "agent": agent,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        self.history.append(event)
        return event
    
    def execute(self, task: str) -> Generator[Dict, None, Dict]:
        """
        Execute task with multi-agent team
        Yields events: {type, agent, data}
        Types: team_start, supervisor_decision, plan, agent_start, agent_thinking, agent_result, agent_done, team_done
        """
        start_time = time.time()
        
        yield self._emit("team_start", "supervisor", {"task": task, "message": f"Team assembling for: {task}, Sir."})
        
        # 1. Supervisor decides routing
        yield self._emit("agent_start", "supervisor", {"message": "Supervisor analyzing task, Sir..."})
        routing = self.supervisor.route(task)
        yield self._emit("supervisor_decision", "supervisor", {"routing": routing, "message": f"Routing: {routing['strategy']} - {routing['reason']}"})
        
        if routing["complexity"] == "simple" and routing["first_agent"] == "none":
            # Simple task, handle directly via supervisor's brain (which is JARVIS himself)
            yield self._emit("agent_thinking", "supervisor", {"message": "Handling directly, Sir. No team needed."})
            try:
                response = self.supervisor.think(task)
                yield self._emit("agent_result", "supervisor", {"response": response})
                yield self._emit("team_done", "supervisor", {
                    "task": task,
                    "result": response,
                    "elapsed": int(time.time() - start_time),
                    "agents_used": ["supervisor"],
                    "message": "Simple task handled directly, Sir."
                })
                return {"task": task, "result": response, "agents": ["supervisor"]}
            except Exception as e:
                yield self._emit("agent_error", "supervisor", {"error": str(e)})
                yield self._emit("team_done", "supervisor", {"task": task, "error": str(e)})
                return {"error": str(e)}
        
        # Complex task - need team
        context = f"Original task: {task}\nRouting: {routing['strategy']}\n"
        agents_used = []
        
        # 2. Planner
        if "planner" in routing["strategy"]:
            yield self._emit("agent_start", "planner", {"message": "Planner breaking down task, Sir..."})
            try:
                todos = self.planner.plan(task, context)
                context += f"\nPlan by Planner: {len(todos)} todos:\n"
                for t in todos:
                    context += f"- {t['id']}. {t['title']} ({t['agent']}) - {t['description']}\n"
                
                yield self._emit("plan", "planner", {"todos": todos, "message": f"Planner created {len(todos)} todos, Sir."})
                agents_used.append("planner")
                
                # Now execute todos with assigned agents
                for todo in todos:
                    agent_name = todo.get("agent", "coder")
                    agent = self.agents.get(agent_name)
                    if not agent:
                        agent = self.coder
                        agent_name = "coder"
                    
                    yield self._emit("agent_start", agent_name, {"todo": todo, "message": f"{agent_name.capitalize()} starting: {todo['title']}, Sir."})
                    
                    try:
                        if agent_name == "researcher":
                            result = self.researcher.research(f"{todo['title']} - {todo['description']}", context)
                        elif agent_name == "coder":
                            result = self.coder.code(todo, task, context)
                        elif agent_name == "reviewer":
                            result = self.reviewer.review(f"{todo['title']} - {todo['description']}", context)
                        else:
                            result = agent.think(f"{todo['title']} - {todo['description']}", context)
                        
                        context += f"\n{agent_name.capitalize()} result for todo {todo['id']} ({todo['title']}): {result[:1500]}\n"
                        
                        yield self._emit("agent_result", agent_name, {"todo": todo, "result": result[:3000], "message": f"{agent_name.capitalize()} done: {todo['title']}"})
                        yield self._emit("agent_done", agent_name, {"todo": todo, "message": f"{todo['title']} completed by {agent_name}"})
                        
                        if agent_name not in agents_used:
                            agents_used.append(agent_name)
                    
                    except Exception as e:
                        yield self._emit("agent_error", agent_name, {"todo": todo, "error": str(e), "message": f"{agent_name} failed on {todo['title']}: {e}"})
                
                # Final review by reviewer if not already done
                if "reviewer" not in agents_used and len(todos) > 2:
                    yield self._emit("agent_start", "reviewer", {"message": "Reviewer doing final review, Sir..."})
                    try:
                        review_result = self.reviewer.review(task, context)
                        context += f"\nFinal Review by Reviewer: {review_result[:1500]}\n"
                        yield self._emit("agent_result", "reviewer", {"result": review_result[:3000], "message": "Final review done"})
                        agents_used.append("reviewer")
                    except Exception as e:
                        yield self._emit("agent_error", "reviewer", {"error": str(e)})
            
            except Exception as e:
                yield self._emit("agent_error", "planner", {"error": str(e), "message": f"Planner failed: {e}, Sir. Falling back to single coder."})
                # Fallback to coder directly
                try:
                    yield self._emit("agent_start", "coder", {"message": "Fallback to Coder, Sir..."})
                    result = self.coder.code({"id": 1, "title": task, "description": task, "files": [], "type": "coding"}, task, context)
                    context += f"\nCoder fallback result: {result[:1500]}\n"
                    yield self._emit("agent_result", "coder", {"result": result[:3000]})
                    agents_used.append("coder")
                except Exception as e2:
                    yield self._emit("agent_error", "coder", {"error": str(e2)})
        
        else:
            # No planner in strategy, directly start with first_agent
            first = routing.get("first_agent", "coder")
            agent = self.agents.get(first, self.coder)
            yield self._emit("agent_start", first, {"message": f"Starting with {first}, Sir..."})
            try:
                result = agent.think(task, context)
                context += f"\n{first} result: {result[:1500]}\n"
                yield self._emit("agent_result", first, {"result": result[:3000]})
                agents_used.append(first)
            except Exception as e:
                yield self._emit("agent_error", first, {"error": str(e)})
        
        elapsed = int(time.time() - start_time)
        
        # Team done
        final_summary = {
            "task": task,
            "agents_used": agents_used,
            "elapsed_seconds": elapsed,
            "context_length": len(context),
            "message": f"Team finished, Sir. {len(agents_used)} agents collaborated for {elapsed}s. Task: {task[:100]}",
            "final_context": context[-3000:]  # last 3k chars
        }
        
        yield self._emit("team_done", "supervisor", final_summary)
        return final_summary
    
    def get_status(self) -> Dict:
        return {
            "agents": {name: agent.get_status() for name, agent in self.agents.items()},
            "history_length": len(self.history),
            "last_events": self.history[-5:] if self.history else []
        }
