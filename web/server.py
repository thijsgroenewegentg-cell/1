"""
JARVIS Web Server - Minimal + Self-Learning + Self-Evolution
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

app = FastAPI(title="J.A.R.V.I.S", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

brain = None
memory_manager = MemoryManager()

def get_brain():
    global brain
    if brain is None:
        brain = JarvisBrain(enable_learning=True, enable_evolution=True)
    return brain

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

@app.get("/")
async def serve_ui():
    ui_path = Path(__file__).parent / "index.html"
    if ui_path.exists():
        return FileResponse(str(ui_path))
    return HTMLResponse("<h1>JARVIS UI not found</h1>")

@app.get("/api/status")
async def get_status():
    b = get_brain()
    return b.get_status()

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
    # Fallback via editor
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
        await websocket.send_json({"type": "message", "data": "Online, Sir. Evolution enabled."})
        
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
                evolved = False
                if b.learning_enabled:
                    try:
                        recent_learnings = b.learning_engine.vector_store.search(user_msg, k=1)
                        if recent_learnings:
                            learned = [r["text"] for r in recent_learnings[:1]]
                    except:
                        pass
                
                # Check if evolution happened
                if b.evolution_enabled and b.evolution_engine:
                    status = b.evolution_engine.get_status()
                    if status.get("should_evolve") and status.get("reasons"):
                        evolved = True
                
                # Stream
                words = full.split(" ")
                for i, word in enumerate(words):
                    chunk = word + (" " if i < len(words)-1 else "")
                    await websocket.send_json({"type": "stream", "data": chunk})
                    await asyncio.sleep(0.02)
                
                if learned:
                    await websocket.send_json({"type": "learned", "data": learned})
                
                if evolved:
                    await websocket.send_json({"type": "evolved", "data": {"message": "I evolved myself, Sir. Check evolution history."}})
                
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
    ║  J.A.R.V.I.S 3.0 - Self-Evolving
    ║  http://{config.WEB_HOST}:{config.WEB_PORT}
    ║  Brain: {config.OLLAMA_MODEL}
    ║  Learning: Enabled | Evolution: Enabled
    ╚════════════════════════════════════╝
    """)
    uvicorn.run("server:app", host=config.WEB_HOST, port=config.WEB_PORT, reload=True, reload_dirs=[str(web_dir.parent)])
