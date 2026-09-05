# /modules/system_control.py
"""Control the host computer: apps, screenshots, stats, volume, input, shell.

Everything is cross-platform — the module detects Windows / macOS / Linux at
import time and picks the right mechanism, degrading to a clear error message
when an optional dependency (pyautogui, pycaw, pactl …) is missing.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.helpers import (
    IS_LINUX,
    IS_MACOS,
    IS_WINDOWS,
    detect_os,
    friendly_time,
    has_display,
    human_bytes,
    human_duration,
    resolve_user_path,
    run_command,
    safe_filename,
    truncate,
    which,
)

# Common spoken names -> per-platform launch targets.
APP_ALIASES: Dict[str, Dict[str, List[str]]] = {
    "chrome": {
        "windows": ["chrome"],
        "macos": ["Google Chrome"],
        "linux": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
    },
    "firefox": {"windows": ["firefox"], "macos": ["Firefox"], "linux": ["firefox"]},
    "edge": {
        "windows": ["msedge"],
        "macos": ["Microsoft Edge"],
        "linux": ["microsoft-edge", "microsoft-edge-stable"],
    },
    "safari": {"macos": ["Safari"], "windows": [], "linux": []},
    "browser": {
        "windows": ["msedge", "chrome"],
        "macos": ["Safari"],
        "linux": ["xdg-open https://duckduckgo.com"],
    },
    "terminal": {
        "windows": ["wt", "cmd"],
        "macos": ["Terminal"],
        "linux": ["gnome-terminal", "konsole", "xfce4-terminal", "alacritty", "kitty", "xterm"],
    },
    "code": {
        "windows": ["code"],
        "macos": ["Visual Studio Code"],
        "linux": ["code", "codium"],
    },
    "vscode": {
        "windows": ["code"],
        "macos": ["Visual Studio Code"],
        "linux": ["code", "codium"],
    },
    "spotify": {"windows": ["spotify"], "macos": ["Spotify"], "linux": ["spotify"]},
    "calculator": {
        "windows": ["calc"],
        "macos": ["Calculator"],
        "linux": ["gnome-calculator", "kcalc", "galculator"],
    },
    "files": {
        "windows": ["explorer"],
        "macos": ["Finder"],
        "linux": ["nautilus", "dolphin", "thunar", "nemo"],
    },
    "explorer": {"windows": ["explorer"], "macos": ["Finder"], "linux": ["nautilus"]},
    "finder": {"macos": ["Finder"], "windows": ["explorer"], "linux": ["nautilus"]},
    "notepad": {
        "windows": ["notepad"],
        "macos": ["TextEdit"],
        "linux": ["gedit", "kate", "mousepad"],
    },
    "notes": {"windows": ["notepad"], "macos": ["Notes"], "linux": ["gedit"]},
    "settings": {
        "windows": ["ms-settings:"],
        "macos": ["System Settings"],
        "linux": ["gnome-control-center", "systemsettings"],
    },
    "slack": {"windows": ["slack"], "macos": ["Slack"], "linux": ["slack"]},
    "discord": {"windows": ["discord"], "macos": ["Discord"], "linux": ["discord"]},
    "mail": {"windows": ["outlook"], "macos": ["Mail"], "linux": ["thunderbird"]},
}


class SystemControl(BaseModule):
    """Applications, hardware stats, media keys, input automation and shell."""

    name = "system_control"
    description = (
        "Control the computer: open/close applications, screenshots, CPU/RAM/disk/battery "
        "stats, volume, lock screen, clipboard, keyboard/mouse automation, the current "
        "time, and running shell commands."
    )
    intent_examples = [
        "open chrome",
        "what time is it",
        "take a screenshot",
        "how much RAM am I using",
        "set the volume to 30",
        "lock my screen",
    ]

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Initialise paths and detect the platform."""
        super().__init__(config, llm=llm, security=security)
        self.os_name = detect_os()
        self.screenshot_dir = config.path_for("screenshots")
        self.shell_timeout = float(config.get("security.shell_timeout", 60))
        self._pyautogui: Optional[Any] = None

    # ------------------------------------------------------------- utilities
    def _gui(self) -> Optional[Any]:
        """Lazily import pyautogui (it opens a display connection)."""
        if self._pyautogui is None:
            try:
                if not has_display():
                    return None
                import pyautogui

                pyautogui.FAILSAFE = True
                pyautogui.PAUSE = 0.05
                self._pyautogui = pyautogui
            except Exception as exc:
                self.log.debug("pyautogui unavailable: %s", exc)
                return None
        return self._pyautogui

    # ---------------------------------------------------------- offline route
    def offline_router(self, command: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """Rule-based routing with parameter extraction (used without an LLM)."""
        text = strip_command_prefix(command)
        lowered = text.lower()

        if any(phrase in lowered for phrase in
               ("what time", "the time", "what date", "what day", "today's date")):
            return "current_time", {}

        if any(phrase in lowered for phrase in
               ("screenshot", "screen shot", "capture the screen", "grab the screen")):
            return "take_screenshot", {}

        if "lock" in lowered and any(w in lowered for w in ("screen", "computer", "machine", "pc")):
            return "lock_screen", {}

        if any(phrase in lowered for phrase in
               ("system stats", "cpu", "ram", "memory usage", "battery", "how is my computer",
                "resource usage", "uptime", "disk space")):
            return "system_stats", {}

        volume = re.search(r"\bvolume\b.*?(\d{1,3})|\bset\s+volume\s+to\s+(\d{1,3})", lowered)
        if volume:
            level = volume.group(1) or volume.group(2)
            return "set_volume", {"level": int(level)}
        if "mute" in lowered:
            return "mute", {"mute": "unmute" not in lowered}
        if "volume" in lowered:
            if any(w in lowered for w in ("up", "louder", "increase")):
                return "set_volume", {"level": 80}
            if any(w in lowered for w in ("down", "quieter", "lower", "decrease")):
                return "set_volume", {"level": 25}

        shell = re.search(r"\b(?:run|execute)\s+(?:the\s+)?(?:shell\s+|terminal\s+)?command\s+(.+)",
                          lowered)
        if shell:
            index = lowered.index(shell.group(1))
            return "run_shell", {"command": text[index:].strip().strip("\"'")}

        url = re.search(r"(https?://\S+|www\.\S+)", text)
        if url and any(w in lowered for w in ("open", "go to", "browse")):
            return "open_url", {"url": url.group(1)}

        launch = re.search(r"\b(?:open|launch|start|fire up)\s+(?:the\s+|my\s+)?([\w .-]+)", lowered)
        if launch:
            name = launch.group(1).strip().removesuffix(" app").removesuffix(" application")
            if name and name not in {"a", "the", "it", "file", "folder", "url", "website"}:
                return "open_app", {"name": name}

        close = re.search(r"\b(?:close|quit|kill)\s+(?:the\s+)?([\w .-]+)", lowered)
        if close:
            return "close_app", {"name": close.group(1).strip()}

        if any(phrase in lowered for phrase in ("processes", "what's running", "task manager")):
            return "list_processes", {}

        if "clipboard" in lowered:
            return "clipboard", {"action": "set" if "copy" in lowered else "get"}

        return None

    # ------------------------------------------------------------------ apps
    @tool(
        description="Launch an application by name (chrome, spotify, terminal, code…).",
        params={"name": {"type": "string", "description": "Application name", "required": True}},
        keywords=["open", "launch", "start", "run app", "fire up"],
        examples=['open_app(name="chrome")'],
    )
    async def open_app(self, name: str) -> ModuleResult:
        """Open an application, resolving common aliases per platform.

        Args:
            name: Spoken application name.

        Returns:
            A :class:`ModuleResult` describing what was launched.
        """
        raw = (name or "").strip().strip("\"'")
        if not raw:
            return ModuleResult.fail("Which application, sir?")

        key = raw.lower().removeprefix("the ").strip()
        candidates = APP_ALIASES.get(key, {}).get(self.os_name, []) or [raw]

        for candidate in candidates:
            code, out, err = await self._launch(candidate)
            if code == 0:
                return ModuleResult.ok(f"Opening {raw}.", app=candidate, target=candidate)
            self.log.debug("Launch attempt failed (%s): %s", candidate, err or out)

        hint = ""
        if self.os_name == "linux" and not has_display():
            hint = " No graphical session detected — is this a headless machine?"
        return ModuleResult.fail(f"I couldn't find an application called '{raw}'.{hint}")

    async def _launch(self, target: str) -> tuple[int, str, str]:
        """Platform-specific application launch."""
        if IS_WINDOWS:
            return await run_command(f'start "" "{target}"', shell=True, timeout=15)
        if IS_MACOS:
            code, out, err = await run_command(["open", "-a", target], timeout=15)
            if code == 0:
                return code, out, err
            return await run_command(["open", target], timeout=15)
        # Linux
        if " " in target:  # already a full command line
            return await run_command(target, shell=True, timeout=15)
        if which(target):
            return await run_command(f"nohup {target} >/dev/null 2>&1 &", shell=True, timeout=10)
        if which("gtk-launch"):
            code, out, err = await run_command(["gtk-launch", target], timeout=10)
            if code == 0:
                return code, out, err
        if which("xdg-open"):
            return await run_command(["xdg-open", target], timeout=10)
        return 127, "", f"'{target}' not found on PATH"

    @tool(
        description="Close/quit a running application by name.",
        params={"name": {"type": "string", "description": "Application name", "required": True}},
        dangerous=True,
        keywords=["close", "quit", "kill app", "terminate", "exit app"],
    )
    async def close_app(self, name: str) -> ModuleResult:
        """Terminate an application by (partial) process name."""
        target = (name or "").strip()
        if not target:
            return ModuleResult.fail("Which application should I close?")

        if IS_WINDOWS:
            executable = target if target.lower().endswith(".exe") else f"{target}.exe"
            code, out, err = await run_command(["taskkill", "/IM", executable, "/F"], timeout=15)
        elif IS_MACOS:
            code, out, err = await run_command(
                ["osascript", "-e", f'quit app "{target}"'], timeout=15
            )
            if code != 0:
                code, out, err = await run_command(["pkill", "-f", target], timeout=10)
        else:
            code, out, err = await run_command(["pkill", "-f", target], timeout=10)

        if code == 0:
            return ModuleResult.ok(f"{target} has been closed.")
        return ModuleResult.fail(f"Couldn't close '{target}': {truncate(err or out, 160)}")

    @tool(
        description="Open a URL in the default web browser.",
        params={"url": {"type": "string", "description": "Full URL", "required": True}},
        keywords=["open website", "go to", "browse to", "open url"],
    )
    async def open_url(self, url: str) -> ModuleResult:
        """Open ``url`` in the user's default browser."""
        target = (url or "").strip()
        if not target:
            return ModuleResult.fail("No URL supplied.")
        if not target.startswith(("http://", "https://")):
            target = f"https://{target}"
        try:
            import webbrowser

            opened = webbrowser.open(target)
            if opened:
                return ModuleResult.ok(f"Opening {target}.")
        except Exception:
            pass
        code, _, err = await self._launch(target)
        if code == 0:
            return ModuleResult.ok(f"Opening {target}.")
        return ModuleResult.fail(f"Could not open the browser: {err}")

    @tool(
        description="List the top running processes by CPU or memory usage.",
        params={
            "sort_by": {"type": "string", "description": "cpu or memory", "default": "cpu"},
            "limit": {"type": "integer", "description": "How many to list", "default": 8},
        },
        keywords=["processes", "what's running", "task manager", "top processes"],
    )
    async def list_processes(self, sort_by: str = "cpu", limit: int = 8) -> ModuleResult:
        """Return the heaviest running processes."""
        try:
            import psutil
        except Exception:
            return ModuleResult.fail("psutil isn't installed — run: pip install psutil")

        key = "memory_percent" if str(sort_by).lower().startswith("mem") else "cpu_percent"
        processes: List[Dict[str, Any]] = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = proc.info
                processes.append(
                    {
                        "pid": info.get("pid"),
                        "name": info.get("name") or "?",
                        "cpu": float(info.get("cpu_percent") or 0.0),
                        "memory": float(info.get("memory_percent") or 0.0),
                    }
                )
            except Exception:
                continue

        sort_key = "memory" if key == "memory_percent" else "cpu"
        processes.sort(key=lambda item: item[sort_key], reverse=True)
        top = processes[: max(1, int(limit))]
        lines = [
            f"{item['name']} (pid {item['pid']}) — CPU {item['cpu']:.1f}%, "
            f"RAM {item['memory']:.1f}%"
            for item in top
        ]
        return ModuleResult.ok("\n".join(lines) or "No processes found.", processes=top)

    # ----------------------------------------------------------- screenshots
    @tool(
        description="Take a screenshot of the whole screen and save it to disk.",
        params={
            "filename": {"type": "string", "description": "Optional file name", "default": ""}
        },
        keywords=["screenshot", "screen shot", "capture screen", "grab screen"],
    )
    async def take_screenshot(self, filename: str = "") -> ModuleResult:
        """Capture the screen. Returns the saved path."""
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = safe_filename(filename or f"screenshot-{stamp}", ".png")
        target = self.screenshot_dir / name

        gui = self._gui()
        if gui is not None:
            try:
                image = gui.screenshot()
                image.save(str(target))
                return ModuleResult.ok(f"Screenshot saved to {target}", path=str(target))
            except Exception as exc:
                self.log.debug("pyautogui screenshot failed: %s", exc)

        commands: List[List[str]] = []
        if IS_MACOS:
            commands = [["screencapture", "-x", str(target)]]
        elif IS_LINUX:
            for binary, args in (
                ("gnome-screenshot", ["-f", str(target)]),
                ("spectacle", ["-b", "-n", "-o", str(target)]),
                ("scrot", [str(target)]),
                ("import", ["-window", "root", str(target)]),
                ("grim", [str(target)]),
            ):
                if which(binary):
                    commands.append([binary, *args])
        elif IS_WINDOWS:
            script = (
                "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
                "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; "
                "$g=[System.Drawing.Graphics]::FromImage($bmp); "
                "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); "
                f"$bmp.Save('{target}')"
            )
            commands.append(["powershell", "-NoProfile", "-Command", script])

        for command in commands:
            code, _, err = await run_command(command, timeout=20)
            if code == 0 and target.exists():
                return ModuleResult.ok(f"Screenshot saved to {target}", path=str(target))
            self.log.debug("Screenshot command failed: %s (%s)", command[0], err)

        return ModuleResult.fail(
            "Screen capture failed — no working capture backend "
            "(install pyautogui, or scrot/gnome-screenshot on Linux)."
        )

    # ------------------------------------------------------------ statistics
    @tool(
        description="Report CPU, RAM, disk, battery, uptime and network stats.",
        params={},
        keywords=["system stats", "cpu", "ram", "memory usage", "disk space", "battery",
                  "how is my computer", "resource usage", "uptime"],
    )
    async def system_stats(self) -> ModuleResult:
        """Collect a full hardware status snapshot."""
        try:
            import psutil
        except Exception:
            return ModuleResult.fail("psutil isn't installed — run: pip install psutil")

        cpu_percent = psutil.cpu_percent(interval=0.4)
        cores = psutil.cpu_count(logical=True) or 1
        virtual = psutil.virtual_memory()
        disk = psutil.disk_usage(str(Path.home().anchor or "/"))
        boot_time = psutil.boot_time()
        uptime = human_duration(time.time() - boot_time)

        data: Dict[str, Any] = {
            "os": f"{detect_os()} ({os.name})",
            "cpu_percent": cpu_percent,
            "cpu_cores": cores,
            "ram_used": human_bytes(virtual.used),
            "ram_total": human_bytes(virtual.total),
            "ram_percent": virtual.percent,
            "disk_used": human_bytes(disk.used),
            "disk_total": human_bytes(disk.total),
            "disk_percent": disk.percent,
            "uptime": uptime,
        }

        lines = [
            f"CPU: {cpu_percent:.0f}% across {cores} cores",
            f"RAM: {data['ram_used']} / {data['ram_total']} ({virtual.percent:.0f}%)",
            f"Disk: {data['disk_used']} / {data['disk_total']} ({disk.percent:.0f}%)",
            f"Uptime: {uptime}",
        ]

        try:
            battery = psutil.sensors_battery()
            if battery is not None:
                plugged = "charging" if battery.power_plugged else "on battery"
                remaining = ""
                if not battery.power_plugged and battery.secsleft and battery.secsleft > 0:
                    remaining = f", ~{human_duration(battery.secsleft)} left"
                lines.append(f"Battery: {battery.percent:.0f}% ({plugged}{remaining})")
                data["battery_percent"] = battery.percent
                data["battery_plugged"] = battery.power_plugged
        except Exception:
            pass

        try:
            temperatures = psutil.sensors_temperatures() or {}
            for _, entries in temperatures.items():
                if entries and entries[0].current:
                    lines.append(f"Temperature: {entries[0].current:.0f}°C")
                    data["temperature_c"] = entries[0].current
                    break
        except Exception:
            pass

        return ModuleResult(success=True, output="\n".join(lines), data=data)

    @tool(
        description="Get the current time and date.",
        params={},
        keywords=["what time", "current time", "the time", "what date", "today's date",
                  "what day is it"],
    )
    async def current_time(self) -> ModuleResult:
        """Return the local time and date."""
        now = datetime.now()
        spoken = now.strftime("%I:%M %p").lstrip("0")
        return ModuleResult(
            success=True,
            output=friendly_time(now),
            speak=f"It's {spoken} on {now.strftime('%A, %d %B %Y')}.",
            data={"iso": now.isoformat(timespec="seconds")},
        )

    # ---------------------------------------------------------------- volume
    @tool(
        description="Set the system output volume to a percentage (0-100).",
        params={
            "level": {"type": "integer", "description": "0-100", "required": True},
        },
        keywords=["volume", "louder", "quieter", "turn it up", "turn it down", "sound level"],
    )
    async def set_volume(self, level: int) -> ModuleResult:
        """Set the master output volume."""
        try:
            value = max(0, min(100, int(level)))
        except Exception:
            return ModuleResult.fail("Volume must be a number between 0 and 100.")

        if IS_MACOS:
            code, _, err = await run_command(
                ["osascript", "-e", f"set volume output volume {value}"], timeout=10
            )
        elif IS_WINDOWS:
            code, err = 1, "no backend"
            try:
                from ctypes import POINTER, cast  # type: ignore

                from comtypes import CLSCTX_ALL  # type: ignore
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore

                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                volume.SetMasterVolumeLevelScalar(value / 100.0, None)
                code, err = 0, ""
            except Exception as exc:
                err = f"pycaw unavailable ({exc})"
        else:
            code, err = 1, "no mixer found"
            if which("pactl"):
                code, _, err = await run_command(
                    ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"], timeout=10
                )
            elif which("wpctl"):
                code, _, err = await run_command(
                    ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{value/100:.2f}"],
                    timeout=10,
                )
            elif which("amixer"):
                code, _, err = await run_command(
                    ["amixer", "-q", "sset", "Master", f"{value}%"], timeout=10
                )

        if code == 0:
            return ModuleResult.ok(f"Volume set to {value}%.", level=value)
        return ModuleResult.fail(f"Volume control failed: {truncate(str(err), 140)}")

    @tool(
        description="Mute or unmute the system audio.",
        params={"mute": {"type": "boolean", "description": "True to mute", "default": True}},
        keywords=["mute", "unmute", "silence the", "sound off", "sound on"],
    )
    async def mute(self, mute: bool = True) -> ModuleResult:
        """Toggle system mute."""
        if IS_MACOS:
            state = "true" if mute else "false"
            code, _, err = await run_command(
                ["osascript", "-e", f"set volume output muted {state}"], timeout=10
            )
        elif IS_WINDOWS:
            code, err = 1, "no backend"
            try:
                from ctypes import POINTER, cast  # type: ignore

                from comtypes import CLSCTX_ALL  # type: ignore
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore

                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                volume.SetMute(1 if mute else 0, None)
                code, err = 0, ""
            except Exception as exc:
                err = str(exc)
        else:
            flag = "1" if mute else "0"
            if which("pactl"):
                code, _, err = await run_command(
                    ["pactl", "set-sink-mute", "@DEFAULT_SINK@", flag], timeout=10
                )
            elif which("amixer"):
                code, _, err = await run_command(
                    ["amixer", "-q", "sset", "Master", "mute" if mute else "unmute"], timeout=10
                )
            else:
                code, err = 1, "no mixer found"

        if code == 0:
            return ModuleResult.ok("Muted." if mute else "Unmuted.")
        return ModuleResult.fail(f"Mute failed: {truncate(str(err), 140)}")

    # ------------------------------------------------------------------ lock
    @tool(
        description="Lock the screen immediately.",
        params={},
        dangerous=False,
        keywords=["lock screen", "lock the computer", "lock my machine", "secure the"],
    )
    async def lock_screen(self) -> ModuleResult:
        """Lock the desktop session."""
        if IS_WINDOWS:
            commands = [["rundll32.exe", "user32.dll,LockWorkStation"]]
        elif IS_MACOS:
            commands = [
                ["pmset", "displaysleepnow"],
                [
                    "/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/"
                    "CGSession",
                    "-suspend",
                ],
            ]
        else:
            commands = []
            for binary, args in (
                ("loginctl", ["lock-session"]),
                ("xdg-screensaver", ["lock"]),
                ("gnome-screensaver-command", ["-l"]),
                ("i3lock", []),
                ("swaylock", []),
            ):
                if which(binary):
                    commands.append([binary, *args])

        for command in commands:
            code, _, _ = await run_command(command, timeout=10)
            if code == 0:
                return ModuleResult.ok("Screen locked. Do try to remember your password.")
        return ModuleResult.fail("No screen-lock mechanism available on this system.")

    # ----------------------------------------------------------------- input
    @tool(
        description="Type text on the keyboard as if the user typed it.",
        params={
            "text": {"type": "string", "description": "Text to type", "required": True},
            "interval": {"type": "number", "description": "Seconds per key", "default": 0.01},
        },
        keywords=["type this", "type out", "write this for me", "enter text"],
    )
    async def type_text(self, text: str, interval: float = 0.01) -> ModuleResult:
        """Type ``text`` into the focused window."""
        gui = self._gui()
        if gui is None:
            return ModuleResult.fail("Keyboard automation needs pyautogui and a desktop session.")
        try:
            gui.typewrite(str(text), interval=float(interval))
            return ModuleResult.ok(f"Typed {len(text)} characters.")
        except Exception as exc:
            return ModuleResult.fail(f"Typing failed: {exc}")

    @tool(
        description="Press a keyboard shortcut, e.g. 'ctrl+s' or 'cmd+space'.",
        params={"keys": {"type": "string", "description": "Keys joined by +", "required": True}},
        keywords=["press", "hotkey", "keyboard shortcut", "hit key"],
    )
    async def press_keys(self, keys: str) -> ModuleResult:
        """Press a key combination."""
        gui = self._gui()
        if gui is None:
            return ModuleResult.fail("Keyboard automation needs pyautogui and a desktop session.")
        combo = [part.strip().lower() for part in str(keys).replace(" ", "+").split("+") if part]
        if not combo:
            return ModuleResult.fail("No keys given.")
        try:
            if len(combo) == 1:
                gui.press(combo[0])
            else:
                gui.hotkey(*combo)
            return ModuleResult.ok(f"Pressed {'+'.join(combo)}.")
        except Exception as exc:
            return ModuleResult.fail(f"Key press failed: {exc}")

    @tool(
        description="Move the mouse and click at screen coordinates.",
        params={
            "x": {"type": "integer", "description": "X coordinate", "required": True},
            "y": {"type": "integer", "description": "Y coordinate", "required": True},
            "button": {"type": "string", "description": "left/right/middle", "default": "left"},
            "clicks": {"type": "integer", "description": "Number of clicks", "default": 1},
        },
        keywords=["click at", "mouse click", "double click"],
    )
    async def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> ModuleResult:
        """Click at an absolute screen position."""
        gui = self._gui()
        if gui is None:
            return ModuleResult.fail("Mouse automation needs pyautogui and a desktop session.")
        try:
            gui.click(x=int(x), y=int(y), clicks=int(clicks), button=str(button))
            return ModuleResult.ok(f"Clicked at ({x}, {y}).")
        except Exception as exc:
            return ModuleResult.fail(f"Click failed: {exc}")

    @tool(
        description="Read from or write to the system clipboard.",
        params={
            "action": {"type": "string", "description": "get or set", "default": "get"},
            "text": {"type": "string", "description": "Text to copy when setting", "default": ""},
        },
        keywords=["clipboard", "copy this", "what did i copy", "paste buffer"],
    )
    async def clipboard(self, action: str = "get", text: str = "") -> ModuleResult:
        """Get or set clipboard contents."""
        try:
            import pyperclip
        except Exception:
            return ModuleResult.fail("pyperclip isn't installed — run: pip install pyperclip")
        try:
            if str(action).lower().startswith("s"):
                pyperclip.copy(str(text))
                return ModuleResult.ok("Copied to clipboard.")
            content = pyperclip.paste() or ""
            return ModuleResult.ok(
                f"Clipboard contains: {truncate(content, 500)}" if content else "Clipboard is empty.",
                content=content,
            )
        except Exception as exc:
            return ModuleResult.fail(f"Clipboard unavailable: {exc}")

    # ----------------------------------------------------------------- shell
    @tool(
        description="Run a shell command on the host (guarded by a safety check).",
        params={
            "command": {"type": "string", "description": "Command line", "required": True},
            "cwd": {"type": "string", "description": "Working directory", "default": ""},
        },
        keywords=["run command", "shell", "terminal command", "execute command", "bash"],
    )
    async def run_shell(self, command: str, cwd: str = "") -> ModuleResult:
        """Execute a shell command after a risk assessment.

        Dangerous commands require explicit confirmation; blocked patterns are
        refused outright.
        """
        command = (command or "").strip()
        if not command:
            return ModuleResult.fail("No command supplied.")
        if self.security is None:
            return ModuleResult.fail("Security guard unavailable; refusing to run shell commands.")

        assessment = await self.security.authorize(command, f"Run shell command: {command}")
        if assessment.blocked:
            return ModuleResult.fail(f"Refused: {assessment.reason}.")

        directory = str(resolve_user_path(cwd)) if cwd else None
        code, out, err = await run_command(
            command, shell=True, timeout=self.shell_timeout, cwd=directory
        )
        body = out or err or "(no output)"
        if code == 0:
            return ModuleResult.ok(truncate(body, 4000), exit_code=code)
        return ModuleResult(
            success=False,
            output=f"Exit code {code}: {truncate(body, 2000)}",
            error=truncate(err or body, 500),
            data={"exit_code": code},
        )

    @tool(
        description="Show information about the operating system and hardware.",
        params={},
        keywords=["what os", "which system", "machine info", "specs"],
    )
    async def system_info(self) -> ModuleResult:
        """Return static machine information."""
        import platform

        info = {
            "system": platform.system(),
            "release": platform.release(),
            "version": truncate(platform.version(), 60),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "python": platform.python_version(),
            "hostname": platform.node(),
            "home": str(Path.home()),
            "shell": os.environ.get("SHELL") or os.environ.get("COMSPEC", "unknown"),
            "display": has_display(),
        }
        lines = [f"{key.replace('_', ' ').title()}: {value}" for key, value in info.items()]
        return ModuleResult(success=True, output="\n".join(lines), data=info)

    @tool(
        description="Put the computer to sleep.",
        params={},
        dangerous=True,
        keywords=["go to sleep", "suspend the computer", "sleep the machine"],
    )
    async def sleep_computer(self) -> ModuleResult:
        """Suspend the machine."""
        if IS_WINDOWS:
            command = ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]
        elif IS_MACOS:
            command = ["pmset", "sleepnow"]
        else:
            command = ["systemctl", "suspend"]
        code, _, err = await run_command(command, timeout=10)
        if code == 0:
            return ModuleResult.ok("Going to sleep. Wake me when you need me.")
        return ModuleResult.fail(f"Suspend failed: {truncate(err, 140)}")

    @tool(
        description="Check how much free space a disk or folder has.",
        params={"path": {"type": "string", "description": "Path to check", "default": "~"}},
        keywords=["free space", "disk usage", "how full", "storage left"],
    )
    async def disk_free(self, path: str = "~") -> ModuleResult:
        """Report free space for the volume containing ``path``."""
        try:
            target = resolve_user_path(path)
            usage = shutil.disk_usage(str(target if target.exists() else Path.home()))
            percent = usage.used / usage.total * 100 if usage.total else 0
            return ModuleResult(
                success=True,
                output=(
                    f"{human_bytes(usage.free)} free of {human_bytes(usage.total)} "
                    f"({percent:.0f}% used) on {target}"
                ),
                data={"free": usage.free, "total": usage.total, "used_percent": percent},
            )
        except Exception as exc:
            return ModuleResult.fail(f"Could not read disk usage: {exc}")


__all__ = ["SystemControl"]
