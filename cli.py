#!/usr/bin/env python3
"""
JARVIS CLI - Entry point
Usage:
  python cli.py
  python cli.py --voice
  python cli.py --model llama3.1:8b
  python cli.py --prompt "what time is it"
  python cli.py --desktop
  python cli.py --web
"""
import sys
from pathlib import Path

def main_cli():
    import argparse
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S - Just A Rather Very Intelligent System")
    parser.add_argument("--model", type=str, default=None, help="Ollama model")
    parser.add_argument("--voice", action="store_true", help="Enable voice I/O")
    parser.add_argument("--wake-word", action="store_true", help="Enable wake word detection")
    parser.add_argument("--prompt", type=str, default=None, help="Single prompt and exit")
    parser.add_argument("--desktop", action="store_true", help="Launch Python desktop app")
    parser.add_argument("--webview", action="store_true", help="Launch WebView desktop")
    parser.add_argument("--web", action="store_true", help="Launch web server")
    
    args, unknown = parser.parse_known_args()
    
    if args.desktop:
        print("Launching JARVIS Desktop, Sir...")
        try:
            from desktop.python.main import main as desktop_main
            desktop_main()
        except ImportError:
            print("CustomTkinter not found, installing...")
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "customtkinter", "pystray", "pillow", "--break-system-packages"])
            from desktop.python.main import main as desktop_main
            desktop_main()
        return
    
    if args.webview:
        print("Launching JARVIS WebView, Sir...")
        from desktop.python.webview_app import main as wv_main
        wv_main()
        return
    
    if args.web:
        print("Starting web server, Sir...")
        from web.server import app
        import uvicorn
        from jarvis.config import config
        uvicorn.run("web.server:app", host=config.WEB_HOST, port=config.WEB_PORT, reload=True)
        return
    
    # Normal CLI
    from jarvis.app import main as jarvis_main
    # Re-parse with jarvis app's parser (it has same args plus prompt)
    jarvis_main()

if __name__ == "__main__":
    main_cli()
