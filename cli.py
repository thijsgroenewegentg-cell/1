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
  python cli.py --agent "Add JWT auth"
  python cli.py --analyze-codebase
"""
import sys
from pathlib import Path

def main_cli():
    import argparse
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S - Just A Rather Very Intelligent System - Coding Agent")
    parser.add_argument("--model", type=str, default=None, help="Ollama model")
    parser.add_argument("--voice", action="store_true", help="Enable voice I/O")
    parser.add_argument("--wake-word", action="store_true", help="Enable wake word detection")
    parser.add_argument("--prompt", type=str, default=None, help="Single prompt and exit")
    parser.add_argument("--desktop", action="store_true", help="Launch Python desktop app")
    parser.add_argument("--webview", action="store_true", help="Launch WebView desktop")
    parser.add_argument("--web", action="store_true", help="Launch web server")
    parser.add_argument("--agent", type=str, default=None, help="Run coding agent with task, e.g. --agent 'Add JWT auth'")
    parser.add_argument("--analyze-codebase", action="store_true", help="Analyze codebase and show overview")
    parser.add_argument("--search-code", type=str, default=None, help="Search codebase, e.g. --search-code 'auth logic'")
    parser.add_argument("--index", action="store_true", help="Index codebase for RAG")
    
    args, unknown = parser.parse_known_args()
    
    if args.index:
        print("🧠 Indexing codebase, Sir...")
        try:
            from jarvis.coding import CodebaseRAG
            rag = CodebaseRAG()
            result = rag.index_workspace(force=True)
            print(f"✓ Indexed: {result}")
        except Exception as e:
            print(f"Index failed: {e}")
        return
    
    if args.analyze_codebase:
        print("🔍 Analyzing codebase, Sir...")
        try:
            from jarvis.coding import CodebaseRAG
            rag = CodebaseRAG()
            overview = rag.get_overview()
            import json
            print(json.dumps(overview, indent=2))
        except Exception as e:
            print(f"Analyze failed: {e}")
        return
    
    if args.search_code:
        print(f"🔍 Searching codebase for: {args.search_code}")
        try:
            from jarvis.coding import CodebaseRAG
            rag = CodebaseRAG()
            results = rag.search(args.search_code, k=5)
            for r in results:
                print(f"\n--- {r.get('metadata',{}).get('file_path')} (score: {r.get('score',0):.2f}) ---")
                print(r.get('text','')[:800])
        except Exception as e:
            print(f"Search failed: {e}")
        return
    
    if args.agent:
        print(f"⚡ Starting JARVIS Coding Agent, Sir. Task: {args.agent}")
        try:
            from jarvis.coding import CodingAgent
            from jarvis.brain import JarvisBrain
            brain = JarvisBrain()
            agent = CodingAgent(brain=brain)
            print(f"Planning task: {args.agent}")
            todos = agent.plan(args.agent)
            print(f"Plan: {len(todos)} todos")
            for t in todos:
                print(f"  {t['id']}. {t['title']} - {t['description']} [{t['type']}]")
            print("\nExecuting...\n")
            for event in agent.execute(args.agent):
                etype = event['type']
                data = event['data']
                if etype == 'todo_start':
                    print(f"\n→ {data['todo']['title']}: {data['todo']['description']}")
                elif etype == 'todo_done':
                    print(f"✓ {data['todo']['title']} done")
                elif etype == 'todo_failed':
                    print(f"✗ {data['todo']['title']} failed: {data.get('result',{}).get('error','')[:200]}")
                elif etype == 'test_result':
                    print(f"🧪 Tests: {data.get('result',{}).get('summary','')}")
                elif etype == 'git_commit':
                    print(f"📦 Git: {str(data.get('result',''))[:200]}")
                elif etype == 'status':
                    print(f"ℹ {data.get('message','')}")
                elif etype == 'done':
                    print(f"\n{data.get('message')}")
                    print(f"Completed {data.get('completed')}/{data.get('todos_total')} in {data.get('elapsed_seconds')}s")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Agent failed: {e}")
        return
    
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
    jarvis_main()

if __name__ == "__main__":
    main_cli()
