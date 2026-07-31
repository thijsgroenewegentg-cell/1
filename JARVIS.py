#!/usr/bin/env python3
"""
J.A.R.V.I.S Singular App - Everything in One - INSTANT LOAD
100% FREE, No API Keys, Optimized for RX 9070 XT 16GB

INSTANT: UI loads in <1s, everything else background
"""

import os
import sys
import time
import threading
import argparse
import webbrowser
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

BANNER = """
╔══════════════════════════════════════════════════════════════╗
║   J.A.R.V.I.S 4.0 — Singular App — RX 9070 XT 16GB           ║
║   100% FREE • No API Keys • Fully Local • Self-Evolving      ║
║   Instant Load — UI first, brain background                  ║
╚══════════════════════════════════════════════════════════════╝
"""

def print_banner():
    print(BANNER)
    print(f"{datetime.now().strftime('%A %B %d, %Y %I:%M %p')} | Python {sys.version.split()[0]} | {sys.platform}")
    print()

def start_web_server_instant():
    """Start web server INSTANTLY - no brain, no checks, just serve UI"""
    def run():
        try:
            import uvicorn
            from web.server import app
            # Fast, no reload, minimal logging for instant
            uvicorn.run(app, host="0.0.0.0", port=8000, log_level="critical")
        except Exception as e:
            # Fallback: try import without jarvis brain
            try:
                import uvicorn
                from fastapi import FastAPI
                from fastapi.responses import HTMLResponse, FileResponse
                from fastapi.staticfiles import StaticFiles
                
                fallback_app = FastAPI()
                web_dir = Path(__file__).parent / "web"
                if web_dir.exists():
                    fallback_app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")
                
                @fallback_app.get("/")
                async def root():
                    # Try serve index.html instantly
                    for p in [web_dir / "index.html", Path("web/index.html"), Path("web/holo.html")]:
                        if p.exists():
                            return FileResponse(str(p))
                    return HTMLResponse("<h1>JARVIS Loading... Sir. Brain starting in background. Refresh in 2 sec. <a href='/holo'>Holo UI</a> | <a href='/api/health/'>Health</a></h1>")
                
                @fallback_app.get("/holo")
                async def holo():
                    for p in [web_dir / "holo.html", Path("web/holo.html")]:
                        if p.exists():
                            return FileResponse(str(p))
                    return HTMLResponse("<h1>Holo Loading... <a href='/'>Minimal</a></h1>")
                
                @fallback_app.get("/api/health/")
                async def health():
                    return {"status": "starting", "message": "UI instant, brain loading background, Sir."}
                
                uvicorn.run(fallback_app, host="0.0.0.0", port=8000, log_level="critical")
            except Exception as e2:
                print(f"Web server failed: {e} / {e2}")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    # No sleep - instant
    print("✓ Web server starting instantly at http://localhost:8000 and /holo")
    return thread

def open_browser_instant():
    """Open browser instantly, don't wait"""
    def do_open():
        time.sleep(0.5)  # tiny delay to let server bind
        try:
            webbrowser.open("http://localhost:8000/holo")
            time.sleep(0.5)
            webbrowser.open("http://localhost:8000/")
        except:
            pass
    threading.Thread(target=do_open, daemon=True).start()
    print("🌐 Opening browser instantly to /holo movable UI...")

def background_heavy_init():
    """Heavy stuff in background AFTER UI shown - for instant load"""
    time.sleep(1)  # let UI show first
    
    # GPU check fast
    try:
        print("\n--- Background init (non-blocking) ---")
        # Quick GPU check with short timeouts
        gpu_name = "Unknown"
        try:
            import subprocess
            # Fast check, 1s timeout
            result = subprocess.run(["rocm-smi", "--showproductname"], capture_output=True, text=True, timeout=1)
            if result.returncode == 0 and "9070" in result.stdout.lower():
                gpu_name = "RX 9070 XT 16GB - Perfect"
                print(f"✓ AMD GPU: {gpu_name}")
        except:
            pass
        
        # Ollama check fast
        try:
            import requests
            resp = requests.get("http://localhost:11434/api/tags", timeout=1)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])[:5]]
                print(f"✓ Ollama: {', '.join(models) if models else 'no models'}")
                if any("14b" in m for m in models):
                    print("✓ You have 14B model - perfect for 9070 XT!")
            else:
                print("ℹ Ollama not responding, will use fallback brain")
        except:
            print("ℹ Ollama not running - fallback brain will be used, start with: ollama serve")
        
        # Brain init
        try:
            from jarvis.brain import JarvisBrain
            print("🧠 Initializing brain in background...")
            brain = JarvisBrain(enable_learning=True, enable_evolution=True)
            print(f"✓ Brain: {brain.model} | Learning: {brain.learning_enabled} | Evolution: {brain.evolution_enabled}")
        except Exception as e:
            print(f"Brain background init failed (non-critical): {e}")
        
        # Codebase indexing background
        try:
            print("🧠 Indexing codebase in background...")
            from jarvis.coding import CodebaseRAG
            rag = CodebaseRAG()
            result = rag.index_workspace(force=False)
            print(f"✓ Codebase indexed: {result['files_indexed']} files")
        except Exception as e:
            print(f"Indexing failed (non-critical): {e}")
        
        # Proactive engine (don't auto-generate briefing on start, just start scheduler)
        try:
            from jarvis.config import config
            if config.PROACTIVE_ENABLED:
                print("⏰ Starting proactive engine (scheduler only, briefing on demand)...")
                from jarvis.proactive import get_proactive_engine
                # Start without immediate briefing generation for instant load
                engine = get_proactive_engine()
                # Only start scheduler and git watcher, not immediate briefing generation
                try:
                    engine.scheduler.start()
                    engine.git_watcher.start()
                    engine.is_active = True
                    print(f"✓ Proactive scheduler active, morning {engine.morning_hour:02d}:{engine.morning_minute:02d}")
                except:
                    # Fallback full start but in background
                    threading.Thread(target=lambda: engine.start(), daemon=True).start()
        except Exception as e:
            print(f"Proactive background start failed: {e}")
        
        print("--- Background init done, Sir. All systems online. ---\n")
    
    except Exception as e:
        print(f"Background init error: {e}")

def start_tray_instant(web_thread=None):
    """Tray + PyWebView after UI already shown"""
    # Try pywebview window that points to already-running web server
    try:
        import webview
        print("🚀 Opening singular app window (PyWebView) to holo UI...")
        window = webview.create_window(
            title="J.A.R.V.I.S — Singular — RX 9070 XT 16GB — Instant Load",
            url="http://localhost:8000/holo",
            width=1400,
            height=900,
            min_size=(1200, 700),
            background_color="#050608",
        )
        webview.start()
        return True
    except ImportError:
        # Fallback tray
        try:
            import pystray
            from PIL import Image
            from pystray import MenuItem as item
            icon_path = ROOT / "desktop" / "icon.png"
            if icon_path.exists():
                image = Image.open(icon_path).resize((64,64))
            else:
                image = Image.new('RGB', (64,64), color=(0,212,255))
            
            def on_show(icon, it):
                webbrowser.open("http://localhost:8000/holo")
            def on_quit(icon, it):
                icon.stop()
                os._exit(0)
            
            menu = pystray.Menu(
                item('Show Holo UI', on_show),
                item('Show Minimal UI', lambda icon, it: webbrowser.open("http://localhost:8000/")),
                item('Quit', on_quit)
            )
            tray = pystray.Icon("JARVIS", image, "JARVIS Singular Instant", menu)
            print("✓ Tray active - Close window = minimize to tray")
            tray.run()
            return True
        except:
            # Just keep alive, browser already opened
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nShutting down, Sir.")
            return False

def main():
    parser = argparse.ArgumentParser(description="JARVIS Singular Instant Load")
    parser.add_argument("--cli", action="store_true", help="CLI mode only")
    parser.add_argument("--web", action="store_true", help="Web only, no tray")
    parser.add_argument("--always-on", action="store_true", help="Always-on wake word")
    parser.add_argument("--agent", type=str, default=None, help="Coding agent task")
    parser.add_argument("--team", type=str, default=None, help="Multi-agent team task")
    parser.add_argument("--briefing", action="store_true", help="Morning briefing now")
    parser.add_argument("--index", action="store_true", help="Index codebase and exit")
    parser.add_argument("--model", type=str, default=None, help="Ollama model")
    
    args = parser.parse_args()
    
    print_banner()
    
    # Handle special modes that don't need instant UI
    if args.index:
        from jarvis.coding import CodebaseRAG
        rag = CodebaseRAG()
        print(rag.index_workspace(force=True))
        return
    if args.briefing:
        from jarvis.proactive import BriefingGenerator
        print(BriefingGenerator().generate_morning_briefing())
        return
    if args.agent:
        from jarvis.coding import CodingAgent
        from jarvis.brain import JarvisBrain
        brain = JarvisBrain(model=args.model)
        agent = CodingAgent(brain=brain)
        for event in agent.execute(args.agent):
            print(f"[{event['type']}] {str(event['data'])[:300]}")
        return
    if args.team:
        from jarvis.agents import AgentTeam
        team = AgentTeam()
        for event in team.execute(args.team):
            print(f"[{event['agent']}] {event['type']}: {str(event['data'])[:300]}")
        return
    if args.cli:
        from jarvis.app import main as cli_main
        sys.argv = [sys.argv[0]] + ([] if not args.model else ["--model", args.model])
        cli_main()
        return
    
    # INSTANT LOAD PATH (default)
    print("🚀 Starting JARVIS Singular App - INSTANT LOAD - UI first, brain background, Sir...")
    
    # 1. Start web server INSTANTLY - no checks, no brain
    web_thread = start_web_server_instant()
    
    # 2. Open browser INSTANTLY
    open_browser_instant()
    
    # 3. Heavy init in background AFTER UI
    threading.Thread(target=background_heavy_init, daemon=True).start()
    
    print("\n🎉 JARVIS UI loading INSTANTLY, Sir!")
    print("   - Minimal: http://localhost:8000/")
    print("   - Holo Movable: http://localhost:8000/holo (draggable panels, Manina Labs style)")
    print("   - Brain, indexing, proactive starting in background (non-blocking)")
    print("   - Voice: Piper free offline British premium + your ElevenLabs CwhRBWXzGAHq8TQ4Fs17 if API key set")
    print()
    
    if args.web:
        # Web only, no tray/window
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down, Sir.")
        return
    
    # 4. Tray / PyWebView window (blocks, but UI already running)
    start_tray_instant(web_thread=web_thread)

if __name__ == "__main__":
    main()
