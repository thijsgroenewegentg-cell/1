"""
JARVIS Web Server - Minimal + Self-Learning + Self-Evolution + Coding Agent
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import json
import asyncio
import threading
from typing import Optional

from jarvis.brain import JarvisBrain
from jarvis.config import config
from jarvis.memory import MemoryManager

app = FastAPI(title="J.A.R.V.I.S", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

brain = None
memory_manager = MemoryManager()
coding_agent = None
proactive_engine = None
agent_team = None

def get_brain():
    global brain
    if brain is None:
        brain = JarvisBrain(enable_learning=True, enable_evolution=True)
    return brain

def get_coding_agent():
    global coding_agent
    if coding_agent is None:
        try:
            from jarvis.coding import CodingAgent
            coding_agent = CodingAgent(brain=get_brain())
        except Exception as e:
            print(f"Coding agent init failed: {e}")
            coding_agent = None
    return coding_agent

def get_proactive():
    global proactive_engine
    if proactive_engine is None:
        try:
            from jarvis.proactive import get_proactive_engine
            proactive_engine = get_proactive_engine(brain=get_brain())
            # Auto-start if enabled
            if config.PROACTIVE_ENABLED and not proactive_engine.is_active:
                proactive_engine.start()
        except Exception as e:
            print(f"Proactive init failed: {e}")
    return proactive_engine

def get_team():
    global agent_team
    if agent_team is None:
        try:
            from jarvis.agents import AgentTeam
            agent_team = AgentTeam(brain=get_brain())
        except Exception as e:
            print(f"Team init failed: {e}")
            agent_team = None
    return agent_team

class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = None
    stream: bool = True

class ChatResponse(BaseModel):
    response: str
    model: str
    status: dict
    learnings: Optional[list] = None

class FeedbackRequest(BaseModel):
    message_id: Optional[str] = None
    feedback: str
    message_text: Optional[str] = None

class EvolutionRequest(BaseModel):
    instruction: str = ""

class AgentRequest(BaseModel):
    task: str
    model: Optional[str] = None

@app.get("/")
async def serve_ui():
    ui_path = Path(__file__).parent / "index.html"
    if ui_path.exists():
        return FileResponse(str(ui_path))
    return HTMLResponse("<h1>JARVIS UI not found</h1>")

@app.get("/api/status")
async def get_status():
    b = get_brain()
    status = b.get_status()
    # Add coding agent status
    agent = get_coding_agent()
    if agent:
        try:
            overview = agent.rag.get_overview()
            status["codebase"] = overview
        except:
            pass
    return status

@app.get("/api/memories")
async def get_memories():
    return {"memories": memory_manager.get_all_memories()}

@app.get("/api/profile")
async def get_profile():
    b = get_brain()
    if b.learning_enabled and b.learning_engine:
        return b.learning_engine.get_profile()
    return {"error": "Learning not enabled"}

@app.get("/api/learnings")
async def get_learnings(limit: int = 20):
    b = get_brain()
    if b.learning_enabled and b.learning_engine:
        return {
            "learnings": b.learning_engine.get_learnings(limit=limit),
            "insights": b.learning_engine.get_insights()
        }
    return {"learnings": []}

@app.get("/api/insights")
async def get_insights():
    b = get_brain()
    if b.learning_enabled and b.learning_engine:
        return b.learning_engine.get_insights()
    return {"error": "Learning disabled"}

@app.get("/api/evolution/status")
async def get_evolution_status():
    b = get_brain()
    if b.evolution_enabled and b.evolution_engine:
        return b.evolution_engine.get_status()
    return {"error": "Evolution disabled"}

@app.get("/api/evolution/history")
async def get_evolution_history(limit: int = 20):
    b = get_brain()
    if b.evolution_enabled and b.evolution_engine:
        return {"history": b.evolution_engine.get_history(limit=limit)}
    try:
        from jarvis.evolution import SelfEditor
        editor = SelfEditor()
        return editor.get_evolution_history()
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/evolution/improve")
async def trigger_evolution(req: EvolutionRequest):
    b = get_brain()
    if b.evolution_enabled and b.evolution_engine:
        result = b.improve_self(req.instruction)
        return result
    return {"error": "Evolution not enabled"}

# Coding Agent Endpoints
@app.get("/api/codebase/overview")
async def codebase_overview():
    agent = get_coding_agent()
    if not agent:
        return {"error": "Coding agent not available"}
    return agent.rag.get_overview()

@app.get("/api/codebase/search")
async def codebase_search(query: str, k: int = 5):
    agent = get_coding_agent()
    if not agent:
        return {"error": "Coding agent not available"}
    results = agent.rag.search(query, k=k)
    return {"query": query, "results": results}

@app.post("/api/codebase/index")
async def codebase_index(force: bool = False):
    agent = get_coding_agent()
    if not agent:
        return {"error": "Coding agent not available"}
    result = agent.rag.index_workspace(force=force)
    return result

@app.get("/api/git/status")
async def git_status():
    agent = get_coding_agent()
    if not agent:
        return {"error": "Git not available"}
    return {"status": agent.git.status()}

@app.get("/api/git/diff")
async def git_diff(file: str = None, staged: bool = False):
    agent = get_coding_agent()
    if not agent:
        return {"error": "Git not available"}
    return {"diff": agent.git.diff(file_path=file, staged=staged)}

@app.get("/api/git/log")
async def git_log(limit: int = 10):
    agent = get_coding_agent()
    if not agent:
        return {"error": "Git not available"}
    return {"log": agent.git.log(limit=limit)}

@app.get("/api/self-edit/history")
async def self_edit_history(limit: int = 10):
    try:
        from jarvis.tools.self_edit_tools import list_self_edits
        return {"history": list_self_edits(limit=limit)}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/self-edit/list-backups")
async def list_backups(file_path: str = None):
    try:
        from pathlib import Path
        from jarvis.config import config
        backup_dir = config.MEMORY_FILE.parent / "backups" / "self_edit"
        if not backup_dir.exists():
            return {"backups": []}
        if file_path:
            backups = sorted(backup_dir.rglob(f"{Path(file_path).name}.*.bak"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]
        else:
            backups = sorted(backup_dir.rglob("*.bak"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]
        return {"backups": [{"path": str(b), "file": b.name, "mtime": b.stat().st_mtime, "size": b.stat().st_size} for b in backups]}
    except Exception as e:
        return {"error": str(e)}

# Proactive Endpoints
@app.get("/api/proactive/status")
async def proactive_status():
    engine = get_proactive()
    if not engine:
        return {"error": "Proactive not available"}
    return engine.get_status()

@app.post("/api/proactive/briefing")
async def proactive_briefing(type: str = "morning"):
    engine = get_proactive()
    if not engine:
        return {"error": "Proactive not available"}
    try:
        if type == "morning":
            text = engine.briefing.generate_morning_briefing()
        else:
            text = engine.briefing.generate_evening_summary()
        return {"type": type, "text": text}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/proactive/trigger")
async def proactive_trigger(type: str = "morning"):
    engine = get_proactive()
    if not engine:
        return {"error": "Proactive not available"}
    msg = engine.trigger_briefing_now(type=type)
    return {"status": msg, "full_status": engine.get_status()}

# Team Endpoints
@app.get("/api/team/status")
async def team_status():
    team = get_team()
    if not team:
        return {"error": "Team not available"}
    return team.get_status()

@app.post("/api/team/execute")
async def team_execute(req: AgentRequest):
    team = get_team()
    if not team:
        return {"error": "Team not available"}
    # Non-streaming, final result
    final = None
    for event in team.execute(req.task):
        if event["type"] == "team_done":
            final = event["data"]
    return final or {"error": "No result"}

# Always-On Wake Word
@app.get("/api/wakeword/status")
async def wakeword_status():
    try:
        from jarvis.voice.wakeword import get_wake_listener
        listener = get_wake_listener()
        return {
            "engine": listener.engine,
            "wake_words": listener.wake_words,
            "is_running": listener.is_running(),
            "sensitivity": listener.sensitivity
        }
    except Exception as e:
        return {"error": str(e), "is_running": False}

@app.post("/api/agent/plan")
async def agent_plan(req: AgentRequest):
    agent = get_coding_agent()
    if not agent:
        return {"error": "Coding agent not available"}
    todos = agent.plan(req.task)
    return {"task": req.task, "todos": todos}

@app.post("/api/agent/execute")
async def agent_execute(req: AgentRequest):
    """Non-streaming execute - returns final summary"""
    agent = get_coding_agent()
    if not agent:
        return {"error": "Coding agent not available"}
    
    # Run in thread to avoid blocking, but for simplicity run sync here
    # For streaming, use websocket
    summary = None
    for event in agent.execute(req.task):
        if event["type"] == "done":
            summary = event["data"]
    return summary or {"error": "No summary"}

@app.post("/api/feedback")
async def post_feedback(req: FeedbackRequest):
    b = get_brain()
    try:
        b.add_feedback(feedback=req.feedback, message_text=req.message_text)
        return {"status": "ok", "feedback": req.feedback}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/reflect")
async def trigger_reflect():
    b = get_brain()
    if b.learning_enabled and b.learning_engine:
        insights = b.learning_engine.reflect()
        return {"insights": insights}
    return {"error": "Learning not enabled"}

@app.post("/api/clear")
async def clear_all(clear_learnings: bool = False):
    b = get_brain()
    if clear_learnings:
        b.clear_all()
        return {"status": "cleared all including learnings"}
    else:
        b.clear_memory()
        return {"status": "cleared conversation"}

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    b = get_brain()
    if req.model:
        b.model = req.model
    try:
        response = b.think(req.message)
        learnings = []
        if b.learning_enabled and b.learning_engine:
            recent = b.learning_engine.vector_store.get_all(limit=3)
            learnings = [r["text"] for r in recent]
        return ChatResponse(response=response, model=b.model, status=b.get_status(), learnings=learnings[:2])
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e), "model": b.model}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    b = get_brain()
    
    try:
        await websocket.send_json({"type": "status", "data": b.get_status()})
        await websocket.send_json({"type": "message", "data": "Online, Sir. Agent + Evolution enabled."})
        
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                if isinstance(payload, dict):
                    user_msg = payload.get("message", data)
                    msg_type = payload.get("type", "chat")
                    
                    if msg_type == "feedback":
                        b.add_feedback(feedback=payload.get("feedback", "positive"), message_text=payload.get("text"))
                        await websocket.send_json({"type": "feedback_ok", "data": payload.get("feedback")})
                        continue
                    
                    if msg_type == "evolve":
                        instruction = payload.get("instruction", "")
                        await websocket.send_json({"type": "thinking", "data": True})
                        result = b.improve_self(instruction)
                        await websocket.send_json({"type": "evolution", "data": result})
                        await websocket.send_json({"type": "done", "data": ""})
                        continue
                    
                    if msg_type == "agent":
                        # Coding agent streaming
                        task = payload.get("task", user_msg)
                        agent = get_coding_agent()
                        if not agent:
                            await websocket.send_json({"type": "error", "data": "Coding agent not available"})
                            continue
                        
                        await websocket.send_json({"type": "agent_start", "data": {"task": task}})
                        try:
                            for event in agent.execute(task):
                                await websocket.send_json({"type": f"agent_{event['type']}", "data": event["data"]})
                                await asyncio.sleep(0.01)
                        except Exception as e:
                            await websocket.send_json({"type": "error", "data": f"Agent error: {e}"})
                        continue
                    
                    if msg_type == "team":
                        task = payload.get("task", user_msg)
                        team = get_team()
                        if not team:
                            await websocket.send_json({"type": "error", "data": "Team not available"})
                            continue
                        await websocket.send_json({"type": "team_start", "data": {"task": task}})
                        try:
                            for event in team.execute(task):
                                await websocket.send_json({"type": f"team_{event['type']}", "data": event["data"]})
                                await asyncio.sleep(0.01)
                        except Exception as e:
                            await websocket.send_json({"type": "error", "data": f"Team error: {e}"})
                        continue
                    
                    if msg_type == "proactive_briefing":
                        btype = payload.get("briefing_type", "morning")
                        engine = get_proactive()
                        if not engine:
                            await websocket.send_json({"type": "error", "data": "Proactive not available"})
                            continue
                        try:
                            if btype == "morning":
                                text = engine.briefing.generate_morning_briefing()
                            else:
                                text = engine.briefing.generate_evening_summary()
                            await websocket.send_json({"type": "briefing", "data": {"type": btype, "text": text}})
                        except Exception as e:
                            await websocket.send_json({"type": "error", "data": f"Briefing error: {e}"})
                        continue
                    
                    model = payload.get("model")
                    if model:
                        b.model = model
                else:
                    user_msg = data
            except:
                user_msg = data
            
            if not user_msg or not user_msg.strip():
                continue
            
            if user_msg.lower() in ["/clear", "clear"]:
                b.clear_memory()
                await websocket.send_json({"type": "clear"})
                await websocket.send_json({"type": "message", "data": "Cleared, Sir."})
                continue
            
            if user_msg.lower() in ["/evolve", "improve yourself", "make yourself better"]:
                await websocket.send_json({"type": "thinking", "data": True})
                result = b.improve_self("General self-improvement as requested by Sir")
                await websocket.send_json({"type": "evolution", "data": result})
                await websocket.send_json({"type": "message", "data": f"Evolution started, Sir. {result.get('message','')}"})
                await websocket.send_json({"type": "done", "data": ""})
                await websocket.send_json({"type": "status", "data": b.get_status()})
                continue
            
            if user_msg.lower().startswith("/agent "):
                task = user_msg[7:].strip()
                agent = get_coding_agent()
                if not agent:
                    await websocket.send_json({"type": "error", "data": "Coding agent not available"})
                    continue
                await websocket.send_json({"type": "agent_start", "data": {"task": task}})
                try:
                    for event in agent.execute(task):
                        await websocket.send_json({"type": f"agent_{event['type']}", "data": event["data"]})
                        await asyncio.sleep(0.01)
                except Exception as e:
                    await websocket.send_json({"type": "error", "data": f"Agent error: {e}"})
                continue
            
            if user_msg.lower() == "/reflect":
                await websocket.send_json({"type": "thinking", "data": True})
                insights = b.learning_engine.reflect() if b.learning_enabled else {}
                await websocket.send_json({"type": "reflection", "data": insights})
                await websocket.send_json({"type": "done", "data": ""})
                continue
            
            try:
                await websocket.send_json({"type": "thinking", "data": True})
                
                q = []
                def target():
                    try:
                        resp = b.think(user_msg)
                        q.append(resp)
                    except Exception as e:
                        q.append(f"Error, Sir: {e}")
                
                thread = threading.Thread(target=target)
                thread.start()
                while thread.is_alive():
                    await asyncio.sleep(0.1)
                thread.join()
                
                full = q[0] if q else "No response, Sir."
                
                learned = []
                if b.learning_enabled:
                    try:
                        recent_learnings = b.learning_engine.vector_store.search(user_msg, k=1)
                        if recent_learnings:
                            learned = [r["text"] for r in recent_learnings[:1]]
                    except:
                        pass
                
                words = full.split(" ")
                for i, word in enumerate(words):
                    chunk = word + (" " if i < len(words)-1 else "")
                    await websocket.send_json({"type": "stream", "data": chunk})
                    await asyncio.sleep(0.02)
                
                if learned:
                    await websocket.send_json({"type": "learned", "data": learned})
                
                await websocket.send_json({"type": "done", "data": full})
                await websocket.send_json({"type": "status", "data": b.get_status()})
                
            except Exception as e:
                await websocket.send_json({"type": "error", "data": str(e)})
    
    except WebSocketDisconnect:
        print("WS disconnected")
    except Exception as e:
        print(f"WS error: {e}")
        try:
            await websocket.send_json({"type": "error", "data": str(e)})
        except:
            pass

web_dir = Path(__file__).parent
if web_dir.exists():
    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

if __name__ == "__main__":
    print(f"""
    ╔════════════════════════════════════╗
    ║  J.A.R.V.I.S 4.0 - Agent + Evolution
    ║  http://{config.WEB_HOST}:{config.WEB_PORT}
    ║  Brain: {config.OLLAMA_MODEL}
    ║  Learning | Evolution | Coding Agent
    ╚════════════════════════════════════╝
    """)
    uvicorn.run("server:app", host=config.WEB_HOST, port=config.WEB_PORT, reload=True, reload_dirs=[str(web_dir.parent)])
