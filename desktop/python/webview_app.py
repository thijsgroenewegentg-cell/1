"""
JARVIS Desktop - PyWebView version (lightweight Electron alternative)
Uses pywebview to display the holographic web UI in a native window

Features:
- Native window, no browser chrome
- Same holographic UI as web
- Auto-starts FastAPI backend
- Tiny, fast

Run: python desktop/python/webview_app.py
"""
import sys
from pathlib import Path
import threading
import time
import os

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from jarvis.config import config

def start_backend():
    try:
        import uvicorn
        from web.server import app
        print(f"Starting backend on {config.WEB_HOST}:{config.WEB_PORT}, Sir.")
        uvicorn.run(app, host="127.0.0.1", port=config.WEB_PORT, log_level="warning")
    except Exception as e:
        print(f"Backend failed, Sir: {e}")

def main():
    # Start backend in thread
    backend_thread = threading.Thread(target=start_backend, daemon=True)
    backend_thread.start()
    
    time.sleep(1.5)
    
    try:
        import webview
        
        # Create window with JARVIS styling
        window = webview.create_window(
            title="J.A.R.V.I.S",
            url=f"http://127.0.0.1:{config.WEB_PORT}",
            width=1200,
            height=800,
            min_size=(1000, 600),
            background_color="#0a0e13",
            text_select=False,
            easy_drag=True,
        )
        
        # Optional: expose API to JS
        class Api:
            def get_status(self):
                from jarvis.brain import JarvisBrain
                b = JarvisBrain()
                return b.get_status()
            
            def minimize(self):
                window.minimize()
        
        webview.start(debug=False)
        
    except ImportError:
        print("pywebview not installed, Sir.")
        print("Installing...")
        os.system(f"{sys.executable} -m pip install pywebview --break-system-packages")
        main()
    except Exception as e:
        print(f"Webview error: {e}")
        print("Falling back to browser...")
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{config.WEB_PORT}")
        backend_thread.join()

if __name__ == "__main__":
    main()
