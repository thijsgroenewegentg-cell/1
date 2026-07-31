"""
J.A.R.V.I.S Desktop - Minimal Clean + Self-Learning
Native Python desktop, customtkinter

Design principles:
- Minimal, lots of whitespace, like Linear / ChatGPT
- Centered chat column, no clutter
- Reactor as tiny dot pulsing
- Drawer hidden by default
- Self-learning toast: "Learned: ..."
"""

import sys
from pathlib import Path
import threading
import time
from datetime import datetime

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from jarvis.brain import JarvisBrain
from jarvis.config import config

USE_CUSTOM = False
try:
    import customtkinter as ctk
    USE_CUSTOM = True
except ImportError:
    import tkinter as tk
    print("CustomTkinter required. Install: pip install customtkinter")

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
    pass

COLORS = {
    "bg": "#08090a",
    "bg2": "#101114",
    "panel": "#15171a",
    "border": "#1e2024",
    "border2": "#2a2d33",
    "text": "#e6e8eb",
    "dim": "#8a8f98",
    "faint": "#5a5e66",
    "green": "#00c950",
}

if USE_CUSTOM:
    import tkinter as tk
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")

    class JarvisMinimalDesktop(ctk.CTk):
        def __init__(self):
            super().__init__()
            self.title("JARVIS")
            self.geometry("960x700")
            self.minsize(800, 560)
            self.configure(fg_color=COLORS["bg"])

            self.brain = JarvisBrain(enable_learning=True)
            self.is_thinking = False
            self.voice_enabled = False

            self.chat_messages = []  # store widgets

            # Icon
            try:
                icon_path = ROOT / "desktop" / "icon.png"
                if icon_path.exists() and PIL_AVAILABLE:
                    img = Image.open(icon_path)
                    self.icon_img = ImageTk.PhotoImage(img)
                    self.iconphoto(False, self.icon_img)
            except:
                pass

            self.setup_ui()
            self.setup_tray()
            self.after(1000, self.update_status)
            self.after(100, self.animate_dot)
            self.dot_phase = 0

        def setup_ui(self):
            self.grid_columnconfigure(0, weight=1)
            self.grid_rowconfigure(1, weight=1)

            # Header - minimal 52px
            header = ctk.CTkFrame(self, height=52, fg_color=COLORS["bg"], corner_radius=0)
            header.grid(row=0, column=0, sticky="ew")
            header.grid_propagate(False)
            header.grid_columnconfigure(1, weight=1)

            # Left logo
            left = ctk.CTkFrame(header, fg_color="transparent")
            left.grid(row=0, column=0, sticky="w", padx=18)

            self.dot_canvas = tk.Canvas(left, width=14, height=14, bg=COLORS["bg"], highlightthickness=0)
            self.dot_canvas.pack(side="left")
            self.dot_canvas.create_oval(2,2,12,12, fill="#e6e8eb", outline="")

            ctk.CTkLabel(left, text="JARVIS", font=("Inter", 13, "bold"), text_color=COLORS["text"]).pack(side="left", padx=(10,0))
            self.model_label = ctk.CTkLabel(left, text=f"{self.brain.model} • learning", font=("JetBrains Mono", 11), text_color=COLORS["dim"])
            self.model_label.pack(side="left", padx=(12,0))

            # Right controls
            right = ctk.CTkFrame(header, fg_color="transparent")
            right.grid(row=0, column=2, sticky="e", padx=12)

            self.status_label = ctk.CTkLabel(right, text="online", font=("JetBrains Mono", 11), text_color=COLORS["dim"])
            self.status_label.pack(side="left", padx=8)

            ctk.CTkButton(right, text="Learnings", width=80, height=28, font=("Inter", 12),
                          fg_color=COLORS["panel"], border_width=1, border_color=COLORS["border"],
                          command=self.show_learnings).pack(side="left", padx=4)

            ctk.CTkButton(right, text="☰", width=32, height=28, font=("Inter", 14),
                          fg_color="transparent", border_width=1, border_color=COLORS["border"],
                          command=self.toggle_drawer).pack(side="left", padx=4)

            # Border bottom
            border = ctk.CTkFrame(self, height=1, fg_color=COLORS["border"])
            border.grid(row=0, column=0, sticky="ew", pady=(52,0))

            # Main - centered chat
            self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
            self.main_frame.grid(row=1, column=0, sticky="nsew")
            self.main_frame.grid_columnconfigure(0, weight=1)
            self.main_frame.grid_rowconfigure(0, weight=1)

            # Chat scroll - centered max 720
            self.chat_container = ctk.CTkFrame(self.main_frame, fg_color="transparent")
            self.chat_container.grid(row=0, column=0, sticky="nsew")
            self.chat_container.grid_columnconfigure(0, weight=1)
            self.chat_container.grid_rowconfigure(0, weight=1)

            self.chat_scroll = ctk.CTkScrollableFrame(self.chat_container, fg_color="transparent")
            self.chat_scroll.grid(row=0, column=0, sticky="nsew")
            # Center content with max width
            self.chat_scroll.grid_columnconfigure(0, weight=1)

            self.chat_inner = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
            self.chat_inner.grid(row=0, column=0, sticky="n")
            self.chat_inner.grid_columnconfigure(0, weight=1)

            # Welcome
            self.welcome_frame = ctk.CTkFrame(self.chat_inner, fg_color="transparent")
            self.welcome_frame.grid(row=0, column=0, pady=(80,40))

            ctk.CTkLabel(self.welcome_frame, text="Good evening, Sir.", font=("Inter", 24, "bold"), text_color=COLORS["text"]).pack(pady=(0,6))
            ctk.CTkLabel(self.welcome_frame, text="Private, local, and learning.", font=("Inter", 14), text_color=COLORS["dim"]).pack()

            suggest = ctk.CTkFrame(self.welcome_frame, fg_color="transparent")
            suggest.pack(pady=20)
            for txt, q in [("Time", "What time is it?"), ("Memory", "What do you remember?"), ("Profile", "Show my profile"), ("Status", "System status")]:
                ctk.CTkButton(suggest, text=txt, width=80, height=32, font=("Inter", 12),
                              fg_color=COLORS["panel"], border_width=1, border_color=COLORS["border"],
                              command=lambda qq=q: self.quick(qq)).pack(side="left", padx=4)

            self.learning_toast = ctk.CTkLabel(self.welcome_frame, text="", font=("JetBrains Mono", 11), text_color=COLORS["dim"], fg_color=COLORS["panel"], corner_radius=16, padx=12, pady=6)
            # hidden initially

            # Input - floating bottom minimal
            input_wrap = ctk.CTkFrame(self.main_frame, fg_color=COLORS["bg"])
            input_wrap.grid(row=1, column=0, sticky="ew", pady=(0,0))
            input_wrap.grid_columnconfigure(0, weight=1)

            # Center input max 720
            input_center = ctk.CTkFrame(input_wrap, fg_color="transparent")
            input_center.grid(row=0, column=0, sticky="ew")
            input_center.grid_columnconfigure(0, weight=1)

            self.input_frame = ctk.CTkFrame(input_center, fg_color=COLORS["panel"], corner_radius=24, border_width=1, border_color=COLORS["border2"])
            self.input_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(12,0))
            self.input_frame.grid_columnconfigure(0, weight=1)

            self.input_field = ctk.CTkEntry(self.input_frame, placeholder_text="Message JARVIS...", font=("Inter", 14),
                                            fg_color="transparent", border_width=0, height=48)
            self.input_field.grid(row=0, column=0, sticky="ew", padx=(16,0), pady=4)
            self.input_field.bind("<Return>", lambda e: self.send())

            self.send_btn = ctk.CTkButton(self.input_frame, text="↑", width=36, height=36, corner_radius=18,
                                          fg_color=COLORS["text"], text_color=COLORS["bg"], font=("Inter", 16, "bold"),
                                          command=self.send)
            self.send_btn.grid(row=0, column=1, padx=8, pady=6)

            # Footer
            footer = ctk.CTkLabel(input_wrap, text="JARVIS runs locally • 100% private • Self-learning enabled", font=("JetBrains Mono", 10), text_color=COLORS["faint"])
            footer.grid(row=1, column=0, pady=(8,16))

            # Drawer - right slide (initially hidden)
            self.drawer = ctk.CTkFrame(self, width=340, fg_color=COLORS["bg2"], corner_radius=0, border_width=1, border_color=COLORS["border"])
            # We'll place it with place() for slide effect
            self.drawer_open = False

            self.build_drawer()

        def build_drawer(self):
            # Header inside drawer
            h = ctk.CTkFrame(self.drawer, fg_color="transparent", height=52)
            h.pack(fill="x", padx=16, pady=0)
            h.pack_propagate(False)
            ctk.CTkLabel(h, text="SYSTEM", font=("Inter", 11, "bold"), text_color=COLORS["dim"]).pack(side="left")
            ctk.CTkButton(h, text="✕", width=28, height=28, fg_color="transparent", border_width=1, border_color=COLORS["border"],
                          command=self.toggle_drawer).pack(side="right")

            scroll = ctk.CTkScrollableFrame(self.drawer, fg_color="transparent")
            scroll.pack(fill="both", expand=True, padx=12, pady=10)

            # Model
            ctk.CTkLabel(scroll, text="MODEL", font=("Inter", 10, "bold"), text_color=COLORS["faint"]).pack(anchor="w", pady=(10,6))
            self.model_menu = ctk.CTkOptionMenu(scroll, values=["jarvis", "qwen2.5:7b", "llama3.1:8b", "mistral-nemo", "gemma2:9b"],
                                                command=self.change_model, fg_color=COLORS["panel"], button_color=COLORS["panel"])
            self.model_menu.set(self.brain.model)
            self.model_menu.pack(fill="x")

            # Learning stats
            ctk.CTkLabel(scroll, text="LEARNING • SELF-EVOLVING", font=("Inter", 10, "bold"), text_color=COLORS["faint"]).pack(anchor="w", pady=(20,6))
            stats = ctk.CTkFrame(scroll, fg_color=COLORS["panel"], corner_radius=8)
            stats.pack(fill="x", pady=6)
            stats.grid_columnconfigure((0,1,2), weight=1)
            self.stat_vectors = ctk.CTkLabel(stats, text="0\nmemories", font=("JetBrains Mono", 12), text_color=COLORS["text"])
            self.stat_vectors.grid(row=0, column=0, padx=10, pady=10)
            self.stat_satis = ctk.CTkLabel(stats, text="—\nsatisfaction", font=("JetBrains Mono", 12), text_color=COLORS["text"])
            self.stat_satis.grid(row=0, column=1, padx=10, pady=10)
            self.stat_msgs = ctk.CTkLabel(stats, text="0\ninteractions", font=("JetBrains Mono", 12), text_color=COLORS["text"])
            self.stat_msgs.grid(row=0, column=2, padx=10, pady=10)

            self.profile_box = ctk.CTkLabel(scroll, text="No profile yet, Sir. Talk to me and I'll learn.", font=("JetBrains Mono", 11),
                                            text_color=COLORS["dim"], fg_color=COLORS["panel"], corner_radius=8,
                                            wraplength=300, justify="left", anchor="w", padx=10, pady=10)
            self.profile_box.pack(fill="x", pady=6)

            ctk.CTkButton(scroll, text="Reflect now", fg_color=COLORS["text"], text_color=COLORS["bg"], command=self.do_reflect).pack(fill="x", pady=4)
            ctk.CTkButton(scroll, text="View all learnings", fg_color="transparent", border_width=1, border_color=COLORS["border"], command=self.show_learnings).pack(fill="x", pady=4)

            # Memory
            ctk.CTkLabel(scroll, text="MEMORY", font=("Inter", 10, "bold"), text_color=COLORS["faint"]).pack(anchor="w", pady=(20,6))
            self.memory_list = ctk.CTkFrame(scroll, fg_color="transparent")
            self.memory_list.pack(fill="x")

            # Actions
            ctk.CTkLabel(scroll, text="ACTIONS", font=("Inter", 10, "bold"), text_color=COLORS["faint"]).pack(anchor="w", pady=(20,6))
            ctk.CTkButton(scroll, text="Clear chat", fg_color="transparent", border_width=1, border_color=COLORS["border"], command=self.clear_chat).pack(fill="x", pady=2)
            ctk.CTkButton(scroll, text="Clear learnings", fg_color="transparent", border_width=1, border_color=COLORS["border"], command=self.clear_learnings).pack(fill="x", pady=2)

        def animate_dot(self):
            # Subtle pulse of dot
            import math
            self.dot_phase = (self.dot_phase + 0.08) % (2*math.pi)
            scale = 1 + 0.15*math.sin(self.dot_phase) if self.is_thinking else 1 + 0.05*math.sin(self.dot_phase/2)
            # Update canvas oval
            try:
                self.dot_canvas.delete("all")
                # Thinking = brighter + bigger
                r = 5 + (2 if self.is_thinking else 0)
                cx, cy = 7,7
                color = "#e6e8eb" if not self.is_thinking else "#ffffff"
                self.dot_canvas.create_oval(cx-r, cy-r, cx+r, cy+r, fill=color, outline="")
                if self.is_thinking:
                    # outer ring
                    self.dot_canvas.create_oval(cx-r-3, cy-r-3, cx+r+3, cy+r+3, outline="#2a2d33", width=1)
            except:
                pass
            self.after(50, self.animate_dot)

        def add_message(self, role, text):
            # Hide welcome
            if self.welcome_frame.winfo_exists():
                self.welcome_frame.grid_remove()

            # Container for message centered
            msg_wrap = ctk.CTkFrame(self.chat_inner, fg_color="transparent")
            msg_wrap.pack(fill="x", pady=8)
            msg_wrap.grid_columnconfigure(0, weight=1)

            # Meta
            meta_text = {"user": "You", "jarvis": "JARVIS", "system": "SYSTEM", "tool": "TOOL"}[role]
            meta = ctk.CTkLabel(msg_wrap, text=f"{meta_text} • {datetime.now().strftime('%H:%M')}", font=("JetBrains Mono", 10), text_color=COLORS["faint"], anchor="w")
            meta.pack(anchor="w" if role!="user" else "e", padx=10)

            # Bubble - minimal
            max_w = 560
            if role == "user":
                bubble = ctk.CTkFrame(msg_wrap, fg_color=COLORS["text"], corner_radius=18)
                bubble.pack(anchor="e", padx=10, pady=(2,0))
                label = ctk.CTkLabel(bubble, text=text[:2000], font=("Inter", 14), text_color=COLORS["bg"], wraplength=max_w-20, justify="left", anchor="w")
                label.pack(padx=14, pady=10)
            else:
                bubble = ctk.CTkFrame(msg_wrap, fg_color=COLORS["panel"], corner_radius=18, border_width=1, border_color=COLORS["border"])
                bubble.pack(anchor="w", padx=10, pady=(2,0))
                label = ctk.CTkLabel(bubble, text=text[:2000], font=("Inter", 14), text_color=COLORS["text"], wraplength=max_w-20, justify="left", anchor="w")
                label.pack(padx=14, pady=10, anchor="w")

            # Autoscroll
            self.after(50, lambda: self.chat_scroll._parent_canvas.yview_moveto(1.0))
            return bubble

        def send(self):
            text = self.input_field.get().strip()
            if not text or self.is_thinking:
                return
            self.add_message("user", text)
            self.input_field.delete(0, "end")
            self.is_thinking = True
            self.send_btn.configure(state="disabled")

            def worker():
                start = time.time()
                try:
                    resp = self.brain.think(text)
                except Exception as e:
                    resp = f"Error, Sir: {e}"
                latency = int((time.time()-start)*1000)

                def done():
                    self.add_message("jarvis", resp)
                    self.is_thinking = False
                    self.send_btn.configure(state="normal")
                    self.refresh_learning_ui()
                    # Show toast if learned
                    self.show_learning_toast()

                self.after(0, done)

            threading.Thread(target=worker, daemon=True).start()

        def quick(self, q):
            self.input_field.delete(0, "end")
            self.input_field.insert(0, q)
            self.send()

        def show_learning_toast(self):
            try:
                if self.brain.learning_enabled and self.brain.learning_engine:
                    recent = self.brain.learning_engine.vector_store.get_all(limit=1)
                    if recent:
                        txt = recent[0].get("text","")[:60]
                        self.learning_toast.configure(text=f"🧠 Learned: {txt}")
                        self.learning_toast.pack(pady=10)
                        self.after(4000, lambda: self.learning_toast.pack_forget())
            except:
                pass

        def change_model(self, new_model):
            self.brain.model = new_model
            self.model_label.configure(text=f"{new_model} • learning")

        def toggle_drawer(self):
            if not self.drawer_open:
                self.drawer.place(relx=1.0, rely=0, anchor="ne", relwidth=0, width=340, relheight=1.0)
                # Animate
                self.drawer.place_configure(relx=1.0, x=-340)
                self.drawer_open = True
                self.refresh_learning_ui()
            else:
                self.drawer.place_forget()
                self.drawer_open = False

        def refresh_learning_ui(self):
            try:
                if self.brain.learning_enabled and self.brain.learning_engine:
                    eng = self.brain.learning_engine
                    self.stat_vectors.configure(text=f"{len(eng.vector_store.vectors)}\nmemories")
                    prof = eng.user_profile.get()
                    satis = prof["interaction_stats"].get("satisfaction_score", 0.5)
                    self.stat_satis.configure(text=f"{int(satis*100)}%\nsatisfaction")
                    self.stat_msgs.configure(text=f"{eng.message_count}\ninteractions")
                    # Profile
                    summary = eng.user_profile.get_summary_for_prompt()
                    if summary:
                        self.profile_box.configure(text=summary[:500])
                    # Memory list
                    for w in self.memory_list.winfo_children():
                        w.destroy()
                    mems = eng.vector_store.get_all(limit=6)
                    for m in mems:
                        l = ctk.CTkLabel(self.memory_list, text=f"{m.get('text','')[:60]}", font=("JetBrains Mono", 10),
                                         fg_color=COLORS["panel"], corner_radius=6, wraplength=300, anchor="w", justify="left", padx=8, pady=6)
                        l.pack(fill="x", pady=2)
            except Exception as e:
                print(f"Refresh UI failed: {e}")

        def do_reflect(self):
            def worker():
                try:
                    insights = self.brain.learning_engine.reflect()
                    def done():
                        self.add_message("system", f"Reflection: {insights}")
                    self.after(0, done)
                except Exception as e:
                    self.after(0, lambda: self.add_message("system", f"Reflection failed: {e}"))
            threading.Thread(target=worker, daemon=True).start()

        def show_learnings(self):
            self.refresh_learning_ui()
            if not self.drawer_open:
                self.toggle_drawer()

        def clear_chat(self):
            self.brain.clear_memory()
            for w in self.chat_inner.winfo_children():
                if w != self.welcome_frame:
                    w.destroy()
            self.welcome_frame.grid()

        def clear_learnings(self):
            self.brain.clear_all()
            self.refresh_learning_ui()
            self.add_message("system", "Learnings cleared, Sir. Fresh start.")

        def update_status(self):
            status = self.brain.get_status()
            if status["ollama_connected"]:
                self.status_label.configure(text="online")
            else:
                self.status_label.configure(text="offline")
            self.after(5000, self.update_status)

        def setup_tray(self):
            if not TRAY_AVAILABLE:
                return
            try:
                icon_path = ROOT / "desktop" / "icon.png"
                if icon_path.exists() and PIL_AVAILABLE:
                    image = Image.open(icon_path).resize((64,64))
                else:
                    image = Image.new('RGB', (64,64), color=(8,9,10))

                def on_show(icon, item):
                    self.after(0, self.deiconify)
                def on_quit(icon, item):
                    icon.stop()
                    self.after(0, self.quit)

                menu = pystray.Menu(
                    item('Show JARVIS', on_show),
                    item('Quit', on_quit)
                )
                self.tray_icon = pystray.Icon("JARVIS", image, "JARVIS - Minimal • Learning", menu)
                threading.Thread(target=self.tray_icon.run, daemon=True).start()
                self.protocol("WM_DELETE_WINDOW", self.hide_window)
            except Exception as e:
                print(f"Tray failed: {e}")

        def hide_window(self):
            self.withdraw()

    def main():
        app = JarvisMinimalDesktop()
        app.mainloop()

else:
    def main():
        print("CustomTkinter required. Installing...")
        import os
        os.system(f"{sys.executable} -m pip install customtkinter --break-system-packages")
        print("Rerun: python desktop/python/main.py")

if __name__ == "__main__":
    main()
