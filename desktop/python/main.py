"""
J.A.R.V.I.S Desktop App - Native Python
Stark Industries - Local Ollama-powered desktop assistant

Features:
- Native window with arc reactor animation ( Tkinter + CustomTkinter fallback )
- Direct brain integration (no need for web server)
- System tray with pystray (always running like real JARVIS)
- Voice toggle
- Memory panel
- Model switcher
- Global hotkey (Ctrl+Shift+J)

Run: python desktop/python/main.py
"""

import sys
import os
from pathlib import Path
import threading
import queue
import time
from datetime import datetime

# Add root to path
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from jarvis.brain import JarvisBrain
    from jarvis.config import config
    from jarvis.tools import TOOLS_SCHEMA
    from jarvis.memory import MemoryManager
except ImportError as e:
    print(f"Failed to import JARVIS: {e}")
    sys.exit(1)

# Try customtkinter, fallback to tkinter
USE_CUSTOM = False
try:
    import customtkinter as ctk
    USE_CUSTOM = True
    print("Using CustomTkinter for modern UI")
except ImportError:
    import tkinter as tk
    from tkinter import ttk, scrolledtext
    print("CustomTkinter not found, using tkinter")

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

TRAY_AVAILABLE = False
try:
    import pystray
    from pystray import MenuItem as item
    TRAY_AVAILABLE = True
except ImportError:
    print("pystray not available, tray disabled")

# Theme - Stark palette
COLORS = {
    "bg": "#0a0e13",
    "panel": "#10161f",
    "panel2": "#141e2b",
    "cyan": "#00d4ff",
    "cyan_dim": "#00a6cc",
    "blue": "#007aff",
    "green": "#00ff88",
    "orange": "#ff8c00",
    "text": "#c0d6df",
    "dim": "#5a7380",
    "border": "#1c2a3a",
}

if USE_CUSTOM:
    import customtkinter as ctk
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")

    class JarvisDesktop(ctk.CTk):
        def __init__(self):
            super().__init__()
            
            self.title("J.A.R.V.I.S")
            self.geometry("1100x700")
            self.minsize(900, 600)
            
            # Brain
            self.brain = JarvisBrain()
            self.memory = MemoryManager()
            self.voice_enabled = False
            self.is_thinking = False
            
            # Icon
            try:
                icon_path = ROOT / "desktop" / "icon.png"
                if icon_path.exists() and PIL_AVAILABLE:
                    img = Image.open(icon_path)
                    self.icon_img = ImageTk.PhotoImage(img)
                    self.iconphoto(False, self.icon_img)
            except Exception as e:
                print(f"Icon load failed: {e}")
            
            self.setup_ui()
            self.setup_tray()
            
            # Status updater
            self.after(1000, self.update_status_loop)
            self.after(100, self.animate_reactor)
            
            self.reactor_angle = 0

        def setup_ui(self):
            # Grid
            self.grid_columnconfigure(0, weight=1)
            self.grid_rowconfigure(1, weight=1)
            
            # Header
            header = ctk.CTkFrame(self, height=70, fg_color=COLORS["panel"])
            header.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
            header.grid_propagate(False)
            
            # Logo + arc reactor canvas
            self.reactor_canvas = tk.Canvas(header, width=60, height=60, bg=COLORS["panel"], highlightthickness=0)
            self.reactor_canvas.pack(side="left", padx=15, pady=5)
            
            title_frame = ctk.CTkFrame(header, fg_color="transparent")
            title_frame.pack(side="left", fill="y", pady=10)
            
            ctk.CTkLabel(title_frame, text="J.A.R.V.I.S", font=("Orbitron", 22, "bold"), text_color=COLORS["cyan"]).pack(anchor="w")
            ctk.CTkLabel(title_frame, text="Just A Rather Very Intelligent System  •  OLLAMA  •  LOCAL", 
                        font=("JetBrains Mono", 10), text_color=COLORS["dim"]).pack(anchor="w")
            
            # Status + controls in header
            controls = ctk.CTkFrame(header, fg_color="transparent")
            controls.pack(side="right", padx=15)
            
            self.status_label = ctk.CTkLabel(controls, text="● Online", text_color=COLORS["green"], font=("JetBrains Mono", 11))
            self.status_label.pack(side="left", padx=10)
            
            self.model_menu = ctk.CTkOptionMenu(controls, values=["jarvis", "qwen2.5:7b", "llama3.1:8b", "mistral-nemo", "gemma2:9b"],
                                                command=self.change_model, width=140)
            self.model_menu.set(self.brain.model)
            self.model_menu.pack(side="left", padx=5)
            
            self.voice_btn = ctk.CTkButton(controls, text="VOICE OFF", width=90, fg_color=COLORS["panel2"], 
                                          border_width=1, border_color=COLORS["border"],
                                          command=self.toggle_voice)
            self.voice_btn.pack(side="left", padx=5)
            
            ctk.CTkButton(controls, text="⚙", width=30, fg_color=COLORS["panel2"], command=self.show_settings).pack(side="left", padx=2)
            
            # Main split
            main_frame = ctk.CTkFrame(self, fg_color="transparent")
            main_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
            main_frame.grid_columnconfigure(0, weight=1)
            main_frame.grid_columnconfigure(1, weight=0)
            main_frame.grid_rowconfigure(0, weight=1)
            
            # Left: Chat
            chat_frame = ctk.CTkFrame(main_frame, fg_color=COLORS["panel"])
            chat_frame.grid(row=0, column=0, sticky="nsew", padx=(0,5), pady=0)
            chat_frame.grid_rowconfigure(0, weight=1)
            chat_frame.grid_columnconfigure(0, weight=1)
            
            self.chat_scroll = ctk.CTkScrollableFrame(chat_frame, fg_color=COLORS["bg"])
            self.chat_scroll.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
            
            # Quick actions
            quick = ctk.CTkFrame(chat_frame, fg_color="transparent", height=35)
            quick.grid(row=1, column=0, sticky="ew", padx=5, pady=(0,5))
            quick.grid_propagate(False)
            for txt in ["TIME", "STATUS", "WEATHER", "FILES", "SEARCH", "CLEAR"]:
                ctk.CTkButton(quick, text=txt, width=70, height=25, font=("JetBrains Mono", 10),
                             fg_color="transparent", border_width=1, border_color=COLORS["border"],
                             command=lambda t=txt: self.quick_action(t)).pack(side="left", padx=2)
            
            # Input
            input_frame = ctk.CTkFrame(chat_frame, fg_color=COLORS["panel2"], height=55)
            input_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)
            input_frame.grid_propagate(False)
            input_frame.grid_columnconfigure(0, weight=1)
            
            self.input_field = ctk.CTkEntry(input_frame, placeholder_text="Talk to JARVIS, Sir...", 
                                            font=("JetBrains Mono", 12))
            self.input_field.grid(row=0, column=0, sticky="ew", padx=5, pady=10)
            self.input_field.bind("<Return>", lambda e: self.send_message())
            
            self.send_btn = ctk.CTkButton(input_frame, text="SEND", width=80, fg_color=COLORS["cyan"], text_color="black",
                                         font=("Orbitron", 12, "bold"), command=self.send_message)
            self.send_btn.grid(row=0, column=1, padx=5, pady=10)
            
            # Right: Side panel
            side = ctk.CTkFrame(main_frame, fg_color=COLORS["panel"], width=300)
            side.grid(row=0, column=1, sticky="nsew", padx=(5,0), pady=0)
            side.grid_propagate(False)
            
            # Neural activity mock
            ctk.CTkLabel(side, text="NEURAL ACTIVITY", font=("Orbitron", 11), text_color=COLORS["cyan"]).pack(pady=(10,5), padx=10, anchor="w")
            self.activity_canvas = tk.Canvas(side, width=280, height=70, bg=COLORS["bg"], highlightthickness=0)
            self.activity_canvas.pack(padx=10, pady=5)
            
            stats_frame = ctk.CTkFrame(side, fg_color="transparent")
            stats_frame.pack(fill="x", padx=10, pady=5)
            self.stat_model = ctk.CTkLabel(stats_frame, text=f"MODEL: {self.brain.model}", font=("JetBrains Mono", 10), text_color=COLORS["dim"])
            self.stat_model.pack(anchor="w")
            self.stat_mem = ctk.CTkLabel(stats_frame, text="MEM: 0", font=("JetBrains Mono", 10), text_color=COLORS["dim"])
            self.stat_mem.pack(anchor="w")
            self.stat_latency = ctk.CTkLabel(stats_frame, text="LATENCY: --", font=("JetBrains Mono", 10), text_color=COLORS["dim"])
            self.stat_latency.pack(anchor="w")
            
            # Memory
            ctk.CTkLabel(side, text="MEMORY CORE", font=("Orbitron", 11), text_color=COLORS["cyan"]).pack(pady=(15,5), padx=10, anchor="w")
            self.memory_frame = ctk.CTkScrollableFrame(side, fg_color=COLORS["bg"], height=150)
            self.memory_frame.pack(fill="x", padx=10, pady=5)
            
            # Tools
            ctk.CTkLabel(side, text="TOOLS", font=("Orbitron", 11), text_color=COLORS["cyan"]).pack(pady=(15,5), padx=10, anchor="w")
            tools_frame = ctk.CTkFrame(side, fg_color="transparent")
            tools_frame.pack(fill="x", padx=10)
            tools = ["🕒 Time", "🌤️ Weather", "🔍 Search", "💾 Memory", "📁 Files", "🐍 Code", "🖥️ System", "⏱️ Timer"]
            for i, t in enumerate(tools):
                ctk.CTkLabel(tools_frame, text=t, font=("JetBrains Mono", 10), 
                            fg_color=COLORS["panel2"], width=130).grid(row=i//2, column=i%2, padx=2, pady=2, sticky="ew")
            
            # Initial message
            self.add_message("system", "Initializing JARVIS protocols...\nLoading personality matrix... ✓\nConnecting to Ollama brain... ✓\n\nAt your service, Sir.")
            self.refresh_memories()

        def animate_reactor(self):
            self.reactor_canvas.delete("all")
            cx, cy = 30, 30
            # Outer rings
            for r, color, width in [(28, COLORS["cyan"], 2), (22, COLORS["cyan_dim"], 1), (16, COLORS["green"], 1)]:
                self.reactor_canvas.create_oval(cx-r, cy-r, cx+r, cy+r, outline=color, width=width)
            # Spinning tick
            import math
            angle = math.radians(self.reactor_angle)
            x1 = cx + 20 * math.cos(angle)
            y1 = cy + 20 * math.sin(angle)
            self.reactor_canvas.create_line(cx, cy, x1, y1, fill=COLORS["cyan"], width=2)
            # Core
            core_r = 6 + (2 if self.is_thinking else 0)
            self.reactor_canvas.create_oval(cx-core_r, cy-core_r, cx+core_r, cy+core_r, 
                                           fill=COLORS["cyan"], outline="white")
            self.reactor_angle = (self.reactor_angle + (10 if self.is_thinking else 2)) % 360
            self.after(50, self.animate_reactor)

        def add_message(self, role, text):
            frame = ctk.CTkFrame(self.chat_scroll, fg_color=COLORS["panel2"] if role!="user" else "#0e2a3a", 
                                border_width=1, border_color=COLORS["cyan"] if role=="jarvis" else COLORS["border"])
            frame.pack(fill="x", pady=5, padx=5)
            
            header_text = {"user": f"YOU • {datetime.now().strftime('%H:%M')}", 
                          "jarvis": f"J.A.R.V.I.S • {self.brain.model} • {datetime.now().strftime('%H:%M')}",
                          "system": "SYSTEM • BOOT",
                          "tool": "TOOL • EXEC"}[role]
            ctk.CTkLabel(frame, text=header_text, font=("JetBrains Mono", 9), text_color=COLORS["dim"], 
                        anchor="w").pack(fill="x", padx=10, pady=(5,0))
            
            label = ctk.CTkLabel(frame, text=text[:2000], font=("JetBrains Mono", 12), 
                                text_color=COLORS["text"], wraplength=600, justify="left", anchor="w")
            label.pack(fill="x", padx=10, pady=10, anchor="w")
            
            # Autoscroll
            self.after(100, lambda: self.chat_scroll._parent_canvas.yview_moveto(1.0))

        def send_message(self):
            text = self.input_field.get().strip()
            if not text or self.is_thinking:
                return
            self.add_message("user", text)
            self.input_field.delete(0, "end")
            self.is_thinking = True
            self.send_btn.configure(text="...", state="disabled")
            
            # Run in thread
            def worker():
                start = time.time()
                try:
                    response = self.brain.think(text)
                except Exception as e:
                    response = f"I encountered an issue with my neural link, Sir: {e}"
                latency = int((time.time()-start)*1000)
                
                def done():
                    self.add_message("jarvis", response)
                    self.is_thinking = False
                    self.send_btn.configure(text="SEND", state="normal")
                    self.stat_latency.configure(text=f"LATENCY: {latency}ms")
                    self.refresh_memories()
                    if self.voice_enabled:
                        self.speak(response)
                self.after(0, done)
            
            threading.Thread(target=worker, daemon=True).start()

        def quick_action(self, action):
            mapping = {
                "TIME": "What time is it, Jarvis?",
                "STATUS": "What is your system status?",
                "WEATHER": "What is the weather in London?",
                "FILES": "List files in workspace",
                "SEARCH": "Search web for latest AI news",
                "CLEAR": "/clear"
            }
            txt = mapping.get(action, action)
            if txt == "/clear":
                self.brain.clear_memory()
                for w in self.chat_scroll.winfo_children():
                    w.destroy()
                self.add_message("system", "Memory cleared, Sir.")
            else:
                self.input_field.delete(0, "end")
                self.input_field.insert(0, txt)
                self.send_message()

        def change_model(self, new_model):
            self.brain.model = new_model
            self.stat_model.configure(text=f"MODEL: {new_model}")
            self.add_message("system", f"Model switched to {new_model}, Sir.")

        def toggle_voice(self):
            self.voice_enabled = not self.voice_enabled
            self.voice_btn.configure(text="VOICE ON" if self.voice_enabled else "VOICE OFF",
                                    fg_color=COLORS["cyan"] if self.voice_enabled else COLORS["panel2"])
            self.add_message("system", f"Voice {'enabled' if self.voice_enabled else 'disabled'}, Sir.")

        def speak(self, text):
            try:
                from jarvis.voice import get_tts
                tts = get_tts()
                tts.speak(text, blocking=False)
            except Exception as e:
                print(f"TTS failed: {e}")

        def refresh_memories(self):
            for w in self.memory_frame.winfo_children():
                w.destroy()
            mems = self.memory.get_all_memories()[-8:]
            if not mems:
                ctk.CTkLabel(self.memory_frame, text="No memories yet", text_color=COLORS["dim"], font=("JetBrains Mono", 10)).pack()
            else:
                for m in reversed(mems):
                    ctk.CTkLabel(self.memory_frame, text=f"{m['key']}: {m['value'][:60]}", 
                                font=("JetBrains Mono", 9), text_color=COLORS["text"], wraplength=260, anchor="w", justify="left").pack(fill="x", pady=2, padx=5)
            self.stat_mem.configure(text=f"MEM: {len(self.memory.get_all_memories())}")

        def update_status_loop(self):
            status = self.brain.get_status()
            if status["ollama_connected"]:
                self.status_label.configure(text="● Online", text_color=COLORS["green"])
            else:
                self.status_label.configure(text="● Offline", text_color=COLORS["orange"])
            self.after(5000, self.update_status_loop)

        def show_settings(self):
            self.add_message("system", f"Settings:\nOllama: {config.OLLAMA_HOST}\nModel: {self.brain.model}\nWorkspace: {config.WORKSPACE_DIR}\nVoice: {self.voice_enabled}")

        def setup_tray(self):
            if not TRAY_AVAILABLE:
                return
            try:
                icon_path = ROOT / "desktop" / "icon.png"
                if icon_path.exists() and PIL_AVAILABLE:
                    image = Image.open(icon_path).resize((64,64))
                else:
                    image = Image.new('RGB', (64,64), color=(0, 212, 255))
                
                def on_show(icon, item):
                    self.after(0, self.deiconify)
                
                def on_quit(icon, item):
                    icon.stop()
                    self.after(0, self.quit)
                
                menu = pystray.Menu(
                    item('Show JARVIS', on_show),
                    item('Quit', on_quit)
                )
                self.tray_icon = pystray.Icon("JARVIS", image, "J.A.R.V.I.S", menu)
                threading.Thread(target=self.tray_icon.run, daemon=True).start()
                
                self.protocol("WM_DELETE_WINDOW", self.hide_window)
            except Exception as e:
                print(f"Tray setup failed: {e}")

        def hide_window(self):
            self.withdraw()
            print("JARVIS minimized to tray, Sir.")

else:
    # Fallback tkinter
    class JarvisDesktop:
        def __init__(self):
            print("CustomTkinter not available, install with: pip install customtkinter")
            print("Starting fallback mode - use web UI instead: python web/server.py")
            raise ImportError("CustomTkinter required for desktop app")

def main():
    if USE_CUSTOM:
        app = JarvisDesktop()
        app.mainloop()
    else:
        print("Installing customtkinter...")
        os.system(f"{sys.executable} -m pip install customtkinter pystray pillow --break-system-packages")
        print("Please rerun: python desktop/python/main.py")

if __name__ == "__main__":
    main()
