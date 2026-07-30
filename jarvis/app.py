"""
JARVIS Main App - The core loop
"""
import time
import sys
from rich.console import Console
from rich.markdown import Markdown
from rich.live import Live
from rich.panel import Panel
from .brain import JarvisBrain
from .config import config
from .voice import get_tts, get_stt

console = Console()

class JarvisApp:
    def __init__(self, model: str = None, voice: bool = False, wake_word: bool = False):
        console.print(Panel.fit(
            "[bold cyan]J.A.R.V.I.S[/bold cyan] - Just A Rather Very Intelligent System\n[dim]Booting up, Sir...[/dim]",
            border_style="cyan"
        ))
        
        self.brain = JarvisBrain(model=model)
        self.voice_enabled = voice or config.VOICE_ENABLED
        self.wake_word_enabled = wake_word
        self.running = True
        
        self.tts = None
        self.stt = None
        
        if self.voice_enabled:
            try:
                self.tts = get_tts()
                self.stt = get_stt()
                console.print("[green]✓ Voice systems online, Sir.[/green]")
            except Exception as e:
                console.print(f"[yellow]⚠️ Voice init failed: {e}. Falling back to text.[/yellow]")
                self.voice_enabled = False
        
        status = self.brain.get_status()
        console.print(f"[dim]Model: {status['model']} | Ollama: {'✓' if status['ollama_connected'] else '❌'} | Memories: {status['memory_count']}[/dim]")
        
        if status['ollama_connected']:
            console.print("[bold green]Systems online. At your service, Sir.[/bold green]\n")
        else:
            console.print("[bold red]Warning: Ollama not reachable! Run 'ollama serve'[/bold red]")
            console.print(f"[dim]Trying {config.OLLAMA_HOST}[/dim]\n")
    
    def _print_jarvis(self, text: str, with_tts: bool = True):
        console.print(f"\n[bold cyan]JARVIS:[/bold cyan] ", end="")
        # Use markdown for nice formatting
        try:
            console.print(Markdown(text))
        except:
            console.print(text)
        
        if self.voice_enabled and with_tts and self.tts:
            self.tts.speak(text, blocking=False)
    
    def _get_user_input(self) -> str:
        if self.voice_enabled and self.stt:
            if self.wake_word_enabled:
                console.print(f"\n[dim]Say '{config.WAKE_WORD}' to wake me... (or type)[/dim]")
                # Wake word loop
                while True:
                    # Check for wake word
                    heard = self.stt.listen_for_wake_word()
                    if heard:
                        console.print("[bold yellow]✓ Wake word detected, Sir. Listening...[/bold yellow]")
                        self.tts.speak("Yes, Sir?", blocking=True)
                        break
                    # Also allow typed escape
                    # Non-blocking input check would be complex, so we just listen
            
            # Normal voice input
            console.print(f"[dim]Listening... (speak or type)[/dim]")
            text = self.stt.listen(timeout=10, phrase_timeout=5)
            if text:
                console.print(f"[bold green]You (voice):[/bold green] {text}")
                return text
            else:
                console.print("[dim]Didn't catch that, Sir. Fallback to typing...[/dim]")
        
        # Text fallback
        try:
            user_input = console.input("[bold green]You:[/bold green] ")
            return user_input.strip()
        except (EOFError, KeyboardInterrupt):
            return "/exit"
    
    def run_cli(self):
        console.print("[dim]Type your message. Commands: /exit, /clear, /memory, /status, /voice on|off[/dim]\n")
        
        while self.running:
            try:
                user_input = self._get_user_input()
                
                if not user_input:
                    continue
                
                # Commands
                if user_input.lower() in ["/exit", "exit", "quit", "bye"]:
                    self._print_jarvis("Powering down, Sir. Until next time.", with_tts=True)
                    time.sleep(1)
                    break
                
                if user_input.lower() == "/clear":
                    self.brain.clear_memory()
                    console.clear()
                    console.print("[green]Memory cleared, Sir. Fresh start.[/green]")
                    continue
                
                if user_input.lower().startswith("/memory"):
                    mems = self.brain.memory.get_all_memories()
                    if not mems:
                        console.print("[dim]No memories yet[/dim]")
                    else:
                        for m in mems[-20:]:
                            console.print(f"- [cyan]{m['key']}[/cyan]: {m['value']}")
                    continue
                
                if user_input.lower() == "/status":
                    status = self.brain.get_status()
                    console.print(status)
                    continue
                
                if user_input.lower().startswith("/voice"):
                    parts = user_input.split()
                    if len(parts) > 1 and parts[1] == "on":
                        self.voice_enabled = True
                        try:
                            self.tts = get_tts()
                            self.stt = get_stt()
                            console.print("[green]Voice enabled[/green]")
                        except Exception as e:
                            console.print(f"[red]Failed: {e}[/red]")
                    elif len(parts) > 1 and parts[1] == "off":
                        self.voice_enabled = False
                        console.print("[yellow]Voice disabled[/yellow]")
                    else:
                        console.print(f"Voice: {'on' if self.voice_enabled else 'off'}")
                    continue
                
                if user_input.startswith("/"):
                    console.print(f"[red]Unknown command: {user_input}[/red]")
                    continue
                
                # Think
                console.print(f"\n[dim]JARVIS thinking with {self.brain.model}...[/dim]")
                try:
                    response = self.brain.think(user_input)
                    self._print_jarvis(response)
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")
                    import traceback
                    traceback.print_exc()
            
            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted, Sir. Type /exit to quit.[/yellow]")
                continue
            except Exception as e:
                console.print(f"[red]Fatal error: {e}[/red]")
                continue
    
    def run_once(self, prompt: str) -> str:
        """Single prompt, return response (for API)"""
        return self.brain.think(prompt)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S")
    parser.add_argument("--model", type=str, default=None, help="Ollama model")
    parser.add_argument("--voice", action="store_true", help="Enable voice I/O")
    parser.add_argument("--wake-word", action="store_true", help="Enable wake word detection")
    parser.add_argument("--prompt", type=str, default=None, help="Single prompt and exit")
    
    args = parser.parse_args()
    
    app = JarvisApp(model=args.model, voice=args.voice, wake_word=args.wake_word)
    
    if args.prompt:
        response = app.run_once(args.prompt)
        print(response)
    else:
        app.run_cli()

if __name__ == "__main__":
    main()
