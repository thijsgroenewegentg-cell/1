#!/usr/bin/env python3
"""
J.A.R.V.I.S Singular App - Everything in One
100% FREE, No API Keys, Optimized for RX 9070 XT 16GB

This is THE app. One file to run them all.

Features in one:
- Ollama brain (qwen2.5:14b for 9070 XT, fallback 7b)
- Minimal UI + Movable Holographic UI (Manina Labs style) at / and /holo
- Premium voice (free edge+FX / piper / xtts) - Manina style deep British
- Always-on wake word "Jarvis" 24/7 (openwakeword ONNX free local)
- Proactive agent: morning briefing 8:30, evening summary, git watcher, routine suggestions
- Multi-agent team: Planner, Researcher, Coder, Reviewer, Supervisor collaborate
- Autonomous coding agent: plans, codes, tests, fixes, commits for hours
- Codebase RAG: knows entire repo via vector search
- Git superpowers: status, diff, commit, PR
- Self-learning: vector memory, auto-extract, user profile, reflection
- Self-evolution: self-critic 0-10, prompt evolution, tool forging, memory optimization
- Self-editing: can edit own code with backup+compile check+rollback
- System tray, global hotkey, desktop notifications

Usage:
  python JARVIS.py              # Singular app - web UI at http://localhost:8000 + /holo + system tray + proactive
  python JARVIS.py --tray       # With system tray (minimize to tray)
  python JARVIS.py --always-on  # + always-on wake word "Jarvis" 24/7
  python JARVIS.py --cli        # CLI mode only
  python JARVIS.py --web        # Web only, no tray
  python JARVIS.py --agent "task" # Coding agent mode
  python JARVIS.py --team "task"  # Multi-agent team mode
  python JARVIS.py --briefing   # Morning briefing now

Optimized for RX 9070 XT 16GB:
  - Detects AMD GPU via rocm-smi or torch
  - Recommends qwen2.5:14b or 32b Q4 models
  - Uses 16384 context (fits 16GB)
  - GPU-accelerated embeddings and TTS if available

100% FREE, No API Keys, Fully Local.
"""

import os
import sys
import time
import threading
import argparse
import webbrowser
from pathlib import Path
from datetime import datetime

# Add root to path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ASCII Art
JARVIS_BANNER = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   J.A.R.V.I.S 4.0 — Singular App — RX 9070 XT 16GB           ║
║   100% FREE • No API Keys • Fully Local • Self-Evolving      ║
║   Movable Holographic UI + Premium Voice (Free) + Team       ║
║                                                              ║
║   At your service, Sir.                                      ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""

def print_banner():
    print(JARVIS_BANNER)
    print(f"Time: {datetime.now().strftime('%A, %B %d, %Y %I:%M %p')}")
    print(f"Python: {sys.version.split()[0]} | Platform: {sys.platform}")
    print()

def check_gpu():
    """Check for RX 9070 XT or AMD GPU"""
    gpu_info = {"has_amd": False, "has_nvidia": False, "vram": "unknown", "gpu_name": "unknown"}
    
    # Try rocm-smi for AMD
    try:
        import subprocess
        result = subprocess.run(["rocm-smi", "--showproductname", "--showmeminfo", "vram"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            gpu_info["has_amd"] = True
            output = result.stdout.lower()
            if "9070" in output or "9070 xt" in output:
                gpu_info["gpu_name"] = "RX 9070 XT 16GB - Perfect for JARVIS"
                gpu_info["vram"] = "16GB"
            # Parse VRAM
            if "16" in output and "gb" in output:
                gpu_info["vram"] = "16GB"
            print(f"✓ AMD GPU detected: {gpu_info['gpu_name']} | VRAM: {gpu_info['vram']}")
            return gpu_info
    except:
        pass
    
    # Try nvidia-smi
    try:
        import subprocess
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            gpu_info["has_nvidia"] = True
            gpu_info["gpu_name"] = result.stdout.strip().split(",")[0] if "," in result.stdout else result.stdout.strip()
            gpu_info["vram"] = result.stdout.strip().split(",")[1].strip() if "," in result.stdout else "unknown"
            print(f"✓ NVIDIA GPU detected: {gpu_info['gpu_name']} | {gpu_info['vram']}")
            return gpu_info
    except:
        pass
    
    # Try torch
    try:
        import torch
        if torch.cuda.is_available():
            gpu_info["has_nvidia"] = True
            gpu_info["gpu_name"] = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory // (1024**3)
            gpu_info["vram"] = f"{vram}GB"
            print(f"✓ GPU via torch: {gpu_info['gpu_name']} | {gpu_info['vram']}")
            return gpu_info
    except:
        pass
    
    # Check for AMD via torch rocm
    try:
        import torch
        if hasattr(torch, 'cuda') and torch.cuda.is_available():
            # Might be ROCm
            print(f"✓ GPU detected via torch: {torch.cuda.get_device_name(0)}")
            gpu_info["has_amd"] = True
            return gpu_info
    except:
        pass
    
    print("ℹ No dedicated GPU detected or ROCm not installed. JARVIS will run on CPU (still works, slower).")
    print("  For RX 9070 XT: Install ROCm 6.2+ and run with HSA_OVERRIDE_GFX_VERSION=12.0.0 if needed.")
    return gpu_info

def check_ollama():
    """Check Ollama and recommend model for 9070 XT"""
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            model_names = [m["name"] for m in models]
            print(f"✓ Ollama running at http://localhost:11434, models: {', '.join(model_names[:5]) if model_names else 'none'}")
            
            # Recommend model for 9070 XT
            has_14b = any("14b" in m for m in model_names)
            has_32b = any("32b" in m for m in model_names)
            has_7b = any("7b" in m for m in model_names)
            
            if has_14b or has_32b:
                print(f"✓ You have 14B/32B model - perfect for RX 9070 XT 16GB, Sir!")
            elif has_7b:
                print(f"ℹ You have 7B model. With RX 9070 XT 16GB, you can run 14B or 32B Q4 for much smarter JARVIS:")
                print(f"  ollama pull qwen2.5:14b")
                print(f"  Edit Modelfile first line to FROM qwen2.5:14b, then ollama create jarvis -f Modelfile --force")
            else:
                print(f"ℹ No models found. Pull recommended for 9070 XT:")
                print(f"  ollama pull qwen2.5:14b && ollama pull nomic-embed-text")
                print(f"  ollama create jarvis -f Modelfile.9070xt")
            
            return True
        else:
            print("⚠️ Ollama not responding at http://localhost:11434")
            return False
    except Exception as e:
        print(f"⚠️ Ollama not running or not reachable: {e}")
        print("  Start with: ollama serve")
        print("  For 9070 XT if needed: HSA_OVERRIDE_GFX_VERSION=12.0.0 ollama serve")
        return False

def index_codebase_background():
    """Index codebase in background"""
    try:
        print("🧠 Indexing codebase in background, Sir...")
        from jarvis.coding import CodebaseRAG
        rag = CodebaseRAG()
        result = rag.index_workspace(force=False)
        print(f"✓ Codebase indexed: {result['files_indexed']} files, {result['chunks']} chunks")
    except Exception as e:
        print(f"Codebase indexing failed (non-critical): {e}")

def start_proactive_background(brain=None):
    """Start proactive engine in background"""
    try:
        print("⏰ Starting proactive engine (morning briefing, git watcher)...")
        from jarvis.proactive import get_proactive_engine
        engine = get_proactive_engine(brain=brain)
        if not engine.is_active:
            engine.start()
        print(f"✓ Proactive active, morning briefing at {engine.morning_hour:02d}:{engine.morning_minute:02d}")
        return engine
    except Exception as e:
        print(f"Proactive start failed (non-critical): {e}")
        return None

def start_wakeword_background(brain=None):
    """Start always-on wake word in background if enabled"""
    try:
        from jarvis.config import config
        if not config.ALWAYS_ON_ENABLED:
            print("ℹ Always-on wake word disabled (set ALWAYS_ON_ENABLED=true in .env to enable 24/7 listening)")
            return None
        
        print("🎙️ Starting always-on wake word listener, Sir. Say 'Jarvis' anytime...")
        from jarvis.voice.wakeword import AlwaysOnService
        service = AlwaysOnService(brain=brain)
        service.start(brain=brain)
        print("✓ Always-on listening, Sir. I'm everywhere.")
        return service
    except Exception as e:
        print(f"Always-on wake word failed (non-critical): {e}")
        return None

def start_web_server():
    """Start FastAPI web server in background thread"""
    try:
        import uvicorn
        from web.server import app
        from jarvis.config import config
        
        def run_server():
            uvicorn.run(app, host=config.WEB_HOST, port=config.WEB_PORT, log_level="warning")
        
        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        time.sleep(2)  # let server start
        print(f"✓ Web server at http://{config.WEB_HOST}:{config.WEB_PORT} (minimal at / and holo at /holo)")
        return thread
    except Exception as e:
        print(f"Web server failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def open_browser():
    """Open browser to JARVIS UI"""
    try:
        from jarvis.config import config
        url = f"http://localhost:{config.WEB_PORT}/holo"
        print(f"🌐 Opening browser to {url} - Movable Holographic UI")
        webbrowser.open(url)
        # Also open minimal
        time.sleep(1)
        webbrowser.open(f"http://localhost:{config.WEB_PORT}/")
    except Exception as e:
        print(f"Could not open browser: {e}")

def start_tray_app(web_thread=None, proactive_engine=None, wakeword_service=None):
    """Start system tray or PyWebView singular app"""
    # Try pywebview first (singular app window)
    try:
        import webview
        from jarvis.config import config
        
        print("🚀 Starting singular app window with PyWebView (movable holographic UI)...")
        
        # Create window pointing to holo UI
        window = webview.create_window(
            title="J.A.R.V.I.S — Singular App — RX 9070 XT 16GB — 100% Free",
            url=f"http://localhost:{config.WEB_PORT}/holo",
            width=1400,
            height=900,
            min_size=(1200, 700),
            background_color="#050608",
            text_select=True,
        )
        
        # System tray via webview? Use pystray as fallback
        # For now just start webview
        webview.start()
        return True
    
    except ImportError:
        print("PyWebView not installed, trying tray + browser mode...")
        try:
            # Fallback to pystray + browser
            import pystray
            from PIL import Image
            from pystray import MenuItem as item
            
            icon_path = Path(__file__).parent / "desktop" / "icon.png"
            if icon_path.exists():
                image = Image.open(icon_path).resize((64,64))
            else:
                image = Image.new('RGB', (64,64), color=(0, 212, 255))
            
            def on_show(icon, it):
                open_browser()
            
            def on_quit(icon, it):
                icon.stop()
                os._exit(0)
            
            menu = pystray.Menu(
                item('Show JARVIS Holo UI', on_show),
                item('Show Minimal UI', lambda icon, it: webbrowser.open(f"http://localhost:{config.WEB_PORT}/")),
                item('Morning Briefing', lambda icon, it: print("Trigger briefing via API")),
                item('Quit', on_quit)
            )
            
            tray = pystray.Icon("JARVIS", image, "J.A.R.V.I.S Singular - RX 9070 XT", menu)
            print("✓ System tray active, Sir. JARVIS lives in tray.")
            print("  Close window = minimize to tray, stays alive")
            
            # Open browser
            open_browser()
            
            tray.run()
            return True
        
        except ImportError:
            print("No PyWebView or pystray, opening browser only...")
            open_browser()
            # Keep alive
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nShutting down, Sir.")
            return False
        except Exception as e:
            print(f"Tray failed: {e}, opening browser")
            open_browser()
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            return False

def main():
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S Singular App - Everything in One - RX 9070 XT 16GB - 100% Free")
    parser.add_argument("--cli", action="store_true", help="CLI mode only, no web/tray")
    parser.add_argument("--web", action="store_true", help="Web server only, no tray/pywebview")
    parser.add_argument("--tray", action="store_true", help="With system tray (default)")
    parser.add_argument("--always-on", action="store_true", help="Enable always-on wake word 'Jarvis' 24/7")
    parser.add_argument("--agent", type=str, default=None, help="Run coding agent with task")
    parser.add_argument("--team", type=str, default=None, help="Multi-agent team task")
    parser.add_argument("--briefing", action="store_true", help="Morning briefing now and exit")
    parser.add_argument("--index", action="store_true", help="Index codebase and exit")
    parser.add_argument("--model", type=str, default=None, help="Ollama model override, e.g. qwen2.5:14b for 9070 XT")
    
    args = parser.parse_args()
    
    print_banner()
    gpu_info = check_gpu()
    ollama_ok = check_ollama()
    
    # Handle special modes
    if args.index:
        print("🧠 Indexing codebase...")
        try:
            from jarvis.coding import CodebaseRAG
            rag = CodebaseRAG()
            result = rag.index_workspace(force=True)
            print(f"✓ Indexed: {result}")
        except Exception as e:
            print(f"Index failed: {e}")
        return
    
    if args.briefing:
        try:
            from jarvis.proactive import BriefingGenerator
            bg = BriefingGenerator()
            briefing = bg.generate_morning_briefing()
            print(f"\n🌅 Morning Briefing, Sir:\n{briefing}\n")
        except Exception as e:
            print(f"Briefing failed: {e}")
        return
    
    if args.agent:
        print(f"⚡ Coding Agent task: {args.agent}")
        try:
            from jarvis.coding import CodingAgent
            from jarvis.brain import JarvisBrain
            brain = JarvisBrain(model=args.model)
            agent = CodingAgent(brain=brain)
            print(f"Planning: {args.agent}")
            todos = agent.plan(args.agent)
            for t in todos:
                print(f"  {t['id']}. [{t.get('agent','coder')}] {t['title']} - {t['description']}")
            print("\nExecuting...\n")
            for event in agent.execute(args.agent):
                etype = event['type']
                data = event['data']
                if etype == 'todo_start':
                    print(f"→ {data['todo']['title']}")
                elif etype == 'todo_done':
                    print(f"✓ {data['todo']['title']} done")
                elif etype == 'test_result':
                    print(f"🧪 {data.get('result',{}).get('summary','Tests')}")
                elif etype == 'done':
                    print(f"\n{data.get('message')}")
        except Exception as e:
            import traceback
            traceback.print_exc()
        return
    
    if args.team:
        print(f"👥 Multi-Agent Team task: {args.team}")
        try:
            from jarvis.agents import AgentTeam
            team = AgentTeam()
            for event in team.execute(args.team):
                print(f"[{event['agent']}] {event['type']}: {str(event['data'])[:300]}")
        except Exception as e:
            import traceback
            traceback.print_exc()
        return
    
    if args.cli:
        # CLI mode
        from jarvis.app import main as cli_main
        sys.argv = [sys.argv[0]] + ([] if not args.model else ["--model", args.model])
        cli_main()
        return
    
    # Singular app mode (default)
    print("🚀 Starting JARVIS Singular App - Everything in One, Sir...")
    print(f"   Optimized for: {gpu_info['gpu_name']} | VRAM: {gpu_info['vram']}")
    print(f"   Model: {args.model or 'jarvis (from Modelfile.9070xt for 9070 XT)'}")
    print(f"   Features: Minimal UI + Holo Movable UI + Agent + Team + Proactive + Always-On + Evolution + Self-Edit + Voice")
    print()
    
    # Init brain
    try:
        from jarvis.brain import JarvisBrain
        print("🧠 Initializing brain, Sir...")
        brain = JarvisBrain(model=args.model, enable_learning=True, enable_evolution=True)
        print(f"✓ Brain: {brain.model} | Ollama: {'✓' if brain._is_ollama_up() else '✗'} | Learning: {brain.learning_enabled} | Evolution: {brain.evolution_enabled}")
    except Exception as e:
        print(f"Brain init failed: {e}")
        brain = None
    
    # Background indexing
    threading.Thread(target=index_codebase_background, daemon=True).start()
    
    # Proactive engine
    proactive_engine = None
    if not args.web:
        proactive_engine = start_proactive_background(brain=brain)
    
    # Always-on wake word if enabled or flag
    wakeword_service = None
    if args.always_on or os.getenv("ALWAYS_ON_ENABLED", "false").lower() == "true":
        wakeword_service = start_wakeword_background(brain=brain)
    
    # Web server
    web_thread = start_web_server()
    
    if args.web:
        print("\n✓ Web server only mode. Open http://localhost:8000 and /holo")
        print("  Press Ctrl+C to stop, Sir.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down, Sir.")
        return
    
    # Singular app window + tray
    print("\n🎉 JARVIS Singular App ready, Sir!")
    print("   - Minimal UI: http://localhost:8000/")
    print("   - Holographic Movable UI: http://localhost:8000/holo (draggable panels, Manina Labs style)")
    print("   - Premium Voice: manina_premium preset, 100% free edge+FX or piper/xtts offline")
    print("   - Features: Chat, Codebase RAG, Git, Agent, Team, Proactive, Memory, Evolution, Self-Edits, Voice Lab, Terminal")
    print("   - Tray: Close window = minimize to tray, stays alive like real JARVIS")
    print("   - Say 'Jarvis' if --always-on enabled")
    print()
    
    start_tray_app(web_thread=web_thread, proactive_engine=proactive_engine, wakeword_service=wakeword_service)

if __name__ == "__main__":
    main()
