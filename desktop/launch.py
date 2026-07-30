#!/usr/bin/env python3
"""
JARVIS Desktop Launcher - Picks best available desktop mode
Usage: python desktop/launch.py [python|webview|electron]
"""
import sys
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

def launch_python():
    print("🚀 Launching JARVIS Python Desktop...")
    try:
        # Try customtkinter version
        from desktop.python.main import main
        main()
    except ImportError as e:
        print(f"CustomTkinter missing, installing... {e}")
        subprocess.run([sys.executable, "-m", "pip", "install", "customtkinter", "pystray", "pillow", "--break-system-packages"])
        try:
            from desktop.python.main import main
            main()
        except Exception as e2:
            print(f"Failed: {e2}, falling back to webview...")
            launch_webview()

def launch_webview():
    print("🌐 Launching JARVIS via WebView (pywebview)...")
    # Start FastAPI in background thread, open webview
    try:
        import webview
        import threading
        import time
        from jarvis.config import config
        
        def start_server():
            try:
                import uvicorn
                from web.server import app
                uvicorn.run(app, host="127.0.0.1", port=config.WEB_PORT, log_level="warning")
            except Exception as e:
                print(f"Server error: {e}")
        
        t = threading.Thread(target=start_server, daemon=True)
        t.start()
        time.sleep(2)
        
        webview.create_window(
            "J.A.R.V.I.S - Just A Rather Very Intelligent System",
            f"http://127.0.0.1:{config.WEB_PORT}",
            width=1200,
            height=800,
            min_size=(900, 600),
            background_color="#0a0e13"
        )
        webview.start()
    except ImportError:
        print("pywebview not installed, installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pywebview", "--break-system-packages"])
        launch_webview()
    except Exception as e:
        print(f"Webview failed: {e}, opening browser instead...")
        launch_browser()

def launch_browser():
    print("🌐 Opening JARVIS Web UI in browser...")
    import threading
    import webbrowser
    import time
    from jarvis.config import config
    
    def start_server():
        try:
            import uvicorn
            from web.server import app
            uvicorn.run(app, host="0.0.0.0", port=config.WEB_PORT)
        except Exception as e:
            print(f"Server error: {e}")
    
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    time.sleep(2)
    webbrowser.open(f"http://localhost:{config.WEB_PORT}")
    
    print(f"JARVIS Web UI at http://localhost:{config.WEB_PORT}")
    print("Press Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down, Sir.")

def launch_electron():
    print("⚡ Launching JARVIS Electron...")
    electron_dir = ROOT / "desktop" / "electron"
    if not (electron_dir / "node_modules").exists():
        print("Installing npm deps...")
        subprocess.run(["npm", "install"], cwd=str(electron_dir))
    
    subprocess.run(["npm", "start"], cwd=str(electron_dir))

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    
    if mode == "python":
        launch_python()
    elif mode == "webview":
        launch_webview()
    elif mode == "browser":
        launch_browser()
    elif mode == "electron":
        launch_electron()
    else:
        # Auto: try python, then webview, then browser
        try:
            import customtkinter
            launch_python()
        except ImportError:
            try:
                import webview
                launch_webview()
            except ImportError:
                launch_browser()
