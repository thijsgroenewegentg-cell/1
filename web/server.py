"""
JARVIS Web Server - FastAPI backend for holographic UI
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
from jarvis.brain import JarvisBrain
from jarvis.config import config
from jarvis.memory import MemoryManager

app = FastAPI(title="JARVIS - Just A Rather Very Intelligent System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single global brain instance (could be per-user in future)
brain = None
memory_manager = MemoryManager()

def get_brain():
    global brain
    if brain is None:
        brain = JarvisBrain()
    return brain

class ChatRequest(BaseModel):
    message: str
    model: str = None
    stream: bool = True

class ChatResponse(BaseModel):
    response: str
    model: str
    status: dict

@app.get("/")
async def serve_ui():
    ui_path = Path(__file__).parent / "index.html"
    if ui_path.exists():
        return FileResponse(str(ui_path))
    return HTMLResponse("<h1>JARVIS UI not found</h1><p>Check web/index.html</p>")

@app.get("/api/status")
async def get_status():
    b = get_brain()
    return b.get_status()

@app.get("/api/memories")
async def get_memories():
    return {"memories": memory_manager.get_all_memories()}

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    b = get_brain()
    if req.model:
        b.model = req.model
    
    # Non-streaming simple response
    try:
        response = b.think(req.message)
        return ChatResponse(response=response, model=b.model, status=b.get_status())
    except Exception as e:
        return {"error": str(e), "model": b.model}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    b = get_brain()
    
    try:
        await websocket.send_json({"type": "status", "data": b.get_status()})
        await websocket.send_json({"type": "message", "data": "Systems online, Sir. JARVIS at your service."})
        
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                user_msg = payload.get("message", data)
                model = payload.get("model")
                if model:
                    b.model = model
            except:
                user_msg = data
            
            if not user_msg or not user_msg.strip():
                continue
            
            # Handle commands
            if user_msg.lower() in ["/clear"]:
                b.clear_memory()
                await websocket.send_json({"type": "clear"})
                await websocket.send_json({"type": "message", "data": "Memory cleared, Sir."})
                continue
            
            # Stream response with tool handling
            try:
                # First, think with tools but stream chunks via think_stream
                full_response = ""
                await websocket.send_json({"type": "thinking", "data": True})
                
                # Check if we need tool handling - use brain.think_stream
                async for chunk in async_think_stream(b, user_msg):
                    if chunk.startswith("[TOOL]"):
                        await websocket.send_json({"type": "tool", "data": chunk[6:]})
                    else:
                        full_response += chunk
                        await websocket.send_json({"type": "stream", "data": chunk})
                
                await websocket.send_json({"type": "done", "data": full_response})
                await websocket.send_json({"type": "status", "data": b.get_status()})
                
            except Exception as e:
                await websocket.send_json({"type": "error", "data": str(e)})
    
    except WebSocketDisconnect:
        print("WebSocket disconnected, Sir.")
    except Exception as e:
        print(f"WS error: {e}")
        try:
            await websocket.send_json({"type": "error", "data": str(e)})
        except:
            pass

async def async_think_stream(brain_instance, user_input: str):
    """Wrap sync think_stream into async generator"""
    loop = asyncio.get_event_loop()
    
    # We'll do tool handling synchronously in thread to avoid blocking
    def run_think():
        results = []
        try:
            for chunk in brain_instance.think_stream(user_input):
                results.append(chunk)
        except Exception as e:
            results.append(f"Error: {e}")
        return results
    
    # For true streaming, we need incremental
    # Simplify: use non-streaming think but simulate streaming for final response
    # Actually better: run think (which includes tools) and then stream result
    
    # First, let's do a full think to get tool execution
    import threading
    queue = []
    
    def target():
        try:
            # This will handle tools
            response = brain_instance.think(user_input)
            queue.append(response)
        except Exception as e:
            queue.append(f"Error, Sir: {e}")
    
    thread = threading.Thread(target=target)
    thread.start()
    
    # Wait with async
    while thread.is_alive():
        await asyncio.sleep(0.1)
        # Send thinking heartbeat? No, just wait
    
    thread.join()
    
    full = queue[0] if queue else "No response, Sir."
    
    # Simulate streaming words
    words = full.split(" ")
    for i, word in enumerate(words):
        yield word + (" " if i < len(words)-1 else "")
        await asyncio.sleep(0.03)  # Stark typing effect

# Mount static files (css, js)
web_dir = Path(__file__).parent
if web_dir.exists():
    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

if __name__ == "__main__":
    print(f"""
    ╔════════════════════════════════════╗
    ║  J.A.R.V.I.S Web Interface         ║
    ║  http://{config.WEB_HOST}:{config.WEB_PORT}              ║
    ║  Brain: {config.OLLAMA_MODEL:<20} ║
    ╚════════════════════════════════════╝
    """)
    uvicorn.run("server:app", host=config.WEB_HOST, port=config.WEB_PORT, reload=True, reload_dirs=[str(web_dir.parent)])
