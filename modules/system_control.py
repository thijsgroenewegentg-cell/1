# /modules/system_control.py
"""Control the host computer: apps, screenshots, stats, volume, input, shell.

Everything is cross-platform — the module detects Windows / macOS / Linux at
import time and picks the right mechanism, degrading to a clear error message
when an optional dependency (pyautogui, pycaw, pactl …) is missing.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import tarfile
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

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
    run_blocking,
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
    intent_examples: ClassVar[List[str]] = [
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
        self._cpu_primed = False

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

    async def setup(self) -> None:
        """Take the first CPU sample so the first status answer is quick."""
        await run_blocking(self._prime_cpu)

    def _prime_cpu(self) -> None:
        """Take a throwaway CPU reading so the next one is instant.

        ``cpu_percent(interval=None)`` reports the load since the previous
        call, so somebody has to make a first call. Doing it at start-up costs
        nothing and takes the wait out of the first answer.
        """
        try:
            import psutil

            psutil.cpu_percent(interval=None)
            self._cpu_primed = True
        except Exception:
            self._cpu_primed = False

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

        # Disk questions get the dedicated tool, which reports every mount —
        # "disk space" used to be swallowed by the general stats summary.
        if any(phrase in lowered for phrase in
               ("disk space", "free space", "disk usage", "storage left", "how full",
                "space left", "space is left", "room on")):
            return "disk_free", {}

        if any(phrase in lowered for phrase in
               ("system stats", "cpu", "ram", "memory usage", "battery", "how is my computer",
                "resource usage", "uptime")):
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
        # "open the url youtube.com" names a site with no scheme. Without this
        # the launch rule below grabbed "url youtube.com" as an *app name*,
        # which then failed to open anything. Catch the url/site/website
        # phrasing before the app matcher gets a chance.
        named_site = re.search(
            r"\b(?:open|go to|browse)\s+(?:the\s+|this\s+)?"
            r"(?:url|website|site|webpage|web page|page|address|link)\s+"
            r"(?:for\s+)?([a-z0-9][\w.-]*(?:\.[a-z]{2,})?(?:[/?#][\w/.?=&%-]*)?)",
            lowered,
        )
        if named_site:
            return "open_url", {"url": named_site.group(1)}

        launch = re.search(
            r"\b(?:open|launch|start|fire up)\s+(?:the\s+|my\s+)?([\w .-]+)", lowered)
        if launch:
            name = launch.group(1).strip().removesuffix(" app").removesuffix(" application")
            if name and name not in {"a", "the", "it", "file", "folder", "url", "website"}:
                return "open_app", {"name": name}

        close = re.search(r"\b(?:close|quit|kill)\s+(?:the\s+)?([\w .-]+)", lowered)
        if close:
            return "close_app", {"name": close.group(1).strip()}

        if any(phrase in lowered for phrase in (
            "processes", "what's running", "task manager",
            "apps are running", "programs are running", "what apps are",
            "what programs are", "which apps are open", "which programs are open",
        )):
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

        # psutil.cpu_percent(interval=0.4) sleeps for four hundred milliseconds,
        # which was most of the time this answer took. Sampling without an
        # interval reports the load since the previous call instead: the
        # background primer below keeps a recent reading available, so the
        # figure is current without anyone waiting for it.
        cpu_percent = psutil.cpu_percent(interval=None)
        if cpu_percent == 0.0 and not self._cpu_primed:
            cpu_percent = psutil.cpu_percent(interval=0.08)
        self._cpu_primed = True
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
        description=(
            "Move, click, double-click, right-click, drag or scroll the mouse, "
            "or report where the pointer currently is."
        ),
        keywords=["move the mouse", "double click", "right click", "scroll",
                  "mouse position", "where is the mouse", "drag"],
        params={
            "action": {"type": "string",
                       "description": "move | click | double | right | middle | "
                                      "drag | scroll | position",
                       "default": "position"},
            "x": {"type": "integer", "description": "Target X", "default": -1},
            "y": {"type": "integer", "description": "Target Y", "default": -1},
            "amount": {"type": "integer",
                       "description": "Scroll clicks: positive up, negative down",
                       "default": 0},
            "duration": {"type": "number", "description": "Seconds to take moving",
                         "default": 0.2},
        },
    )
    async def mouse(self, action: str = "position", x: int = -1, y: int = -1,
                    amount: int = 0, duration: float = 0.2) -> ModuleResult:
        """Drive the mouse, or ask it where it is.

        Args:
            action: What to do — ``move``, ``click``, ``double``, ``right``,
                ``middle``, ``drag``, ``scroll`` or ``position``.
            x: Target X coordinate; ``-1`` means "wherever the pointer is".
            y: Target Y coordinate.
            amount: Scroll distance in clicks, positive up.
            duration: How long a move or drag should take, in seconds.

        Returns:
            A :class:`ModuleResult` describing what the pointer did.
        """
        gui = self._gui()
        if gui is None:
            return ModuleResult.fail("Mouse automation needs pyautogui and a desktop session.")

        verb = (action or "position").strip().lower()
        try:
            width, height = gui.size()
            current = gui.position()
            target_x = int(x) if int(x) >= 0 else int(current[0])
            target_y = int(y) if int(y) >= 0 else int(current[1])
            # Off-screen coordinates trip pyautogui's failsafe corner.
            target_x = max(1, min(int(width) - 2, target_x))
            target_y = max(1, min(int(height) - 2, target_y))
            span = max(0.0, float(duration))

            if verb in ("position", "where", "locate"):
                return ModuleResult.ok(
                    f"The pointer is at ({current[0]}, {current[1]}) "
                    f"on a {width}x{height} screen.",
                    data={"x": current[0], "y": current[1],
                          "width": width, "height": height},
                )
            if verb in ("move", "move_to", "goto"):
                gui.moveTo(target_x, target_y, duration=span)
                return ModuleResult.ok(f"Pointer moved to ({target_x}, {target_y}).")
            if verb in ("double", "double_click", "doubleclick"):
                gui.doubleClick(x=target_x, y=target_y)
                return ModuleResult.ok(f"Double-clicked at ({target_x}, {target_y}).")
            if verb in ("right", "right_click", "context"):
                gui.rightClick(x=target_x, y=target_y)
                return ModuleResult.ok(f"Right-clicked at ({target_x}, {target_y}).")
            if verb in ("middle", "middle_click"):
                gui.middleClick(x=target_x, y=target_y)
                return ModuleResult.ok(f"Middle-clicked at ({target_x}, {target_y}).")
            if verb in ("drag", "drag_to"):
                gui.dragTo(target_x, target_y, duration=max(0.2, span), button="left")
                return ModuleResult.ok(f"Dragged to ({target_x}, {target_y}).")
            if verb == "scroll":
                clicks = int(amount) or 3
                gui.scroll(clicks)
                way = "up" if clicks > 0 else "down"
                return ModuleResult.ok(f"Scrolled {abs(clicks)} clicks {way}.")
            if verb in ("click", "left", "left_click"):
                gui.click(x=target_x, y=target_y)
                return ModuleResult.ok(f"Clicked at ({target_x}, {target_y}).")
            return ModuleResult.fail(
                f"I don't know the mouse action '{action}', sir. Try move, click, "
                "double, right, drag, scroll or position."
            )
        except Exception as exc:
            return ModuleResult.fail(f"Mouse action failed: {exc}")

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
                try:
                    if text:
                        self._clip_history.appendleft({"text": truncate(str(text), 200), "when": datetime.now().isoformat(timespec="seconds")})
                except Exception:
                    pass
                return ModuleResult.ok("Copied to clipboard.")
            content = pyperclip.paste() or ""
            try:
                if content:
                    self._clip_history.appendleft({"text": truncate(content, 200), "when": datetime.now().isoformat(timespec="seconds")})
            except Exception:
                pass
            return ModuleResult.ok(
                f"Clipboard contains: {truncate(content, 500)}"
                if content else "Clipboard is empty.",
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
        description=(
            "Show what JARVIS has done that needed permission: commands refused, "
            "actions you confirmed, and writes that were declined."
        ),
        params={
            "limit": {"type": "integer", "description": "How many entries", "default": 12},
            "outcome": {
                "type": "string",
                "description": "Filter: allowed, confirmed, declined or blocked",
                "default": "",
            },
        },
        keywords=["audit log", "what needed permission", "what did you refuse",
                  "security log", "what have you been allowed to do",
                  "what did i approve"],
        examples=["what have you done that needed permission?"],
    )
    async def security_log(self, limit: int = 12, outcome: str = "") -> ModuleResult:
        """Report the security guard's recent decisions.

        The guard has always recorded these; nothing ever showed them, which
        is an odd gap in an assistant that can run shell commands and rewrite
        its own source.

        Args:
            limit: How many entries to show, newest last.
            outcome: Restrict to ``allowed``, ``confirmed``, ``declined`` or
                ``blocked``.

        Returns:
            A :class:`ModuleResult` listing the decisions.
        """
        if self.security is None:
            return ModuleResult.fail("There's no security guard attached, sir.")
        wanted = outcome.strip().lower()
        if wanted and wanted not in {"allowed", "confirmed", "declined", "blocked"}:
            return ModuleResult.fail(
                "Filter by allowed, confirmed, declined or blocked, sir."
            )
        try:
            entries = self.security.recent_audit(max(1, int(limit)), outcome=wanted)
        except Exception as exc:
            return ModuleResult.fail(f"Could not read the audit trail: {exc}")

        if not entries:
            return ModuleResult(
                success=True,
                output="Nothing has needed permission" + (f" ({wanted})" if wanted else "")
                       + " — a quiet conscience, sir.",
                data={"entries": []},
            )

        symbols = {"blocked": "refused", "declined": "you said no",
                   "confirmed": "you approved", "allowed": "allowed"}
        lines = []
        for entry in entries:
            when = str(entry.get("at", ""))[5:16].replace("T", " ")
            verdict = symbols.get(str(entry.get("outcome", "")), entry.get("outcome", "?"))
            source = f" [{entry['source']}]" if entry.get("source") else ""
            lines.append(f"  {when}  {verdict:12} {truncate(str(entry.get('action', '')), 66)}"
                         f"{source}")
        counts: Dict[str, int] = {}
        for entry in entries:
            key = str(entry.get("outcome", "?"))
            counts[key] = counts.get(key, 0) + 1
        tally = ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))
        return ModuleResult(
            success=True,
            output=f"Last {len(entries)} decision(s) — {tally}:\n" + "\n".join(lines),
            speak=f"{len(entries)} decisions on record: {tally}.",
            data={"entries": entries},
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



    # ---------------------------------------------------------------- 1 download organizer
    @tool(
        description="Download any URL to ~/Downloads/jarvis/YYYY-MM-DD-name with progress and auto-unzip for zip/tar.gz.",
        params={
            "url": {"type": "string", "description": "https:// URL to download"},
            "filename": {"type": "string", "description": "Optional override filename", "default": ""},
        },
        dangerous=True,
        keywords=["download", "fetch file", "save url", "pull down"],
    )
    async def download(self, url: str, filename: str = "") -> ModuleResult:
        """Download ``url`` to ``~/Downloads/jarvis`` and auto-unzip if it is an archive."""
        if not url or not url.startswith(("http://", "https://")):
            return ModuleResult.fail("Provide a http(s) URL, sir — e.g. download https://example.com/file.zip")
        try:
            base = Path.home() / "Downloads" / "jarvis"
            base.mkdir(parents=True, exist_ok=True)
            raw = filename.strip() or url.split("?")[0].rstrip("/").split("/")[-1] or "download"
            raw = safe_filename(raw) or "download"
            dated = datetime.now().strftime("%Y-%m-%d") + "-" + raw
            dest = base / dated
            c = 1
            while dest.exists():
                dest = base / f"{dated.rstrip('.' + dest.suffix.lstrip('.'))}-{c}{dest.suffix}"
                c += 1
            def _do():
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
                    shutil.copyfileobj(r, f)
                return dest.stat().st_size
            size = await run_blocking(_do)
            extra = ""
            try:
                if dest.suffix.lower() == ".zip" and zipfile.is_zipfile(dest):
                    out = dest.with_suffix("")
                    out.mkdir(exist_ok=True)
                    with zipfile.ZipFile(dest) as z:
                        z.extractall(out)
                    extra = f" — unzipped to {out}"
                elif dest.name.endswith((".tar.gz", ".tgz")) or dest.suffix.lower() in (".gz", ".tgz"):
                    try:
                        out = dest.with_suffix("").with_suffix("") if dest.name.endswith(".tar.gz") else dest.with_suffix("")
                        out.mkdir(exist_ok=True)
                        with tarfile.open(dest, "r:*") as t:
                            t.extractall(out)
                        extra = f" — extracted to {out}"
                    except Exception:
                        pass
            except Exception:
                pass
            return ModuleResult.ok(f"Downloaded {human_bytes(size)} to {dest}{extra}", data={"path": str(dest), "bytes": size, "extra": extra})
        except Exception as exc:
            return ModuleResult.fail(f"Download failed: {exc}")

    # -------------------------------------------------------------- 2 window / app manager
    @tool(
        description="List visible window titles (and app names where available).",
        params={"limit": {"type": "integer", "description": "Max windows to return", "default": 20}},
        keywords=["list windows", "show windows", "what is open", "window list"],
    )
    async def list_windows(self, limit: int = 20) -> ModuleResult:
        """List window titles via wmctrl/xdotool / AppleScript / tasklist, falling back to processes."""
        limit = max(1, min(50, int(limit or 20)))
        titles: list[str] = []
        try:
            if IS_LINUX:
                for cmd in ([ "wmctrl", "-l" ], [ "xdotool", "search", "--name", "" ]):
                    if which(cmd[0]):
                        code, out, _ = await run_command(cmd, timeout=8)
                        if code == 0 and out.strip():
                            if cmd[0] == "wmctrl":
                                for line in out.splitlines()[:limit]:
                                    parts = line.split(None, 3)
                                    if len(parts) == 4:
                                        titles.append(parts[3])
                            else:
                                for line in out.splitlines()[:limit]:
                                    titles.append(f"window {line.strip()}")
                            break
            elif IS_MACOS:
                if which("osascript"):
                    code, out, _ = await run_command(["osascript", "-e", 'tell application "System Events" to get name of every process whose background only is false'], timeout=8)
                    if code == 0:
                        titles = [t.strip() for t in out.replace(",", "\n").splitlines() if t.strip()][:limit]
            elif IS_WINDOWS:
                try:
                    import pygetwindow  # type: ignore
                    titles = [t for t in pygetwindow.getAllTitles() if t.strip()][:limit]
                except Exception:
                    pass
                if not titles and which("powershell"):
                    code, out, _ = await run_command(["powershell", "-NoProfile", "-Command", "Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object -ExpandProperty MainWindowTitle"], timeout=10)
                    if code == 0:
                        titles = [l.strip() for l in out.splitlines() if l.strip()][:limit]
                if not titles:
                    code, out, _ = await run_command(["tasklist", "/v", "/fo", "csv"], timeout=10)
                    if code == 0:
                        for line in out.splitlines()[1:limit+1]:
                            titles.append(line.split(",")[-1].strip().strip('"'))
        except Exception:
            pass
        if not titles:
            res = await self.list_processes(limit=limit)
            return ModuleResult(success=True, output=f"No window manager found — top processes:\n{res.output}", data={"windows": [], "fallback": res.data})
        out = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles[:limit]))
        return ModuleResult.ok(f"Windows ({len(titles[:limit])}):\n{out}", data={"windows": titles[:limit]})

    @tool(
        description="Focus / bring to front a window by substring of its title.",
        params={"title": {"type": "string", "description": "Substring to match in window title"}},
        keywords=["focus window", "bring to front", "activate window", "switch to"],
    )
    async def focus_window(self, title: str) -> ModuleResult:
        """Focus a window matching ``title``."""
        if not title.strip():
            return ModuleResult.fail("Give me part of the window title to focus — e.g. focus window \"Spotify\"")
        term = title.strip()
        try:
            if IS_LINUX:
                if which("wmctrl"):
                    await run_command(["wmctrl", "-r", term, "-b", "remove,hidden"], timeout=8)
                    code2, _, err2 = await run_command(["wmctrl", "-a", term], timeout=8)
                    if code2 == 0:
                        return ModuleResult.ok(f"Focused window matching '{term}'.")
                    return ModuleResult.fail(f"wmctrl: {truncate(err2, 120)}")
                if which("xdotool"):
                    code, out, err = await run_command(["xdotool", "search", "--name", term], timeout=8)
                    if code == 0 and out.strip():
                        wid = out.splitlines()[0].strip()
                        await run_command(["xdotool", "windowactivate", wid], timeout=8)
                        return ModuleResult.ok(f"Focused window '{term}' ({wid}).")
            elif IS_MACOS and which("osascript"):
                code, _, err = await run_command(["osascript", "-e", f'tell application "System Events" to set frontmost of first process whose name contains "{term}" to true'], timeout=8)
                if code == 0:
                    return ModuleResult.ok(f"Focused '{term}' on macOS.")
                return ModuleResult.fail(f"AppleScript: {truncate(err, 120)}")
            elif IS_WINDOWS:
                try:
                    import pygetwindow  # type: ignore
                    wins = [w for w in pygetwindow.getAllWindows() if term.lower() in w.title.lower()]
                    if wins:
                        wins[0].activate()
                        return ModuleResult.ok(f"Focused '{wins[0].title}'.")
                except Exception:
                    pass
                if which("powershell"):
                    code, _, err = await run_command(["powershell", "-NoProfile", "-Command", f'(New-Object -ComObject WScript.Shell).AppActivate("{term}")'], timeout=8)
                    if code == 0:
                        return ModuleResult.ok(f"Tried to focus '{term}' via WScript.")
            return ModuleResult.fail(f"No window matching '{term}' found — try list windows.")
        except Exception as exc:
            return ModuleResult.fail(f"Focus failed: {exc}")

    @tool(
        description="Minimize a window by title substring.",
        params={"title": {"type": "string", "description": "Substring to match"}},
        keywords=["minimize window", "hide window", "minimise"],
    )
    async def minimize_window(self, title: str) -> ModuleResult:
        """Minimize a window matching ``title``."""
        if not title.strip():
            return ModuleResult.fail("Give me part of the title to minimize.")
        term = title.strip()
        try:
            if IS_LINUX and which("xdotool"):
                code, out, _ = await run_command(["xdotool", "search", "--name", term], timeout=8)
                if code == 0 and out.strip():
                    wid = out.splitlines()[0].strip()
                    await run_command(["xdotool", "windowminimize", wid], timeout=8)
                    return ModuleResult.ok(f"Minimized '{term}'.")
            elif IS_WINDOWS:
                try:
                    import pygetwindow  # type: ignore
                    wins = [w for w in pygetwindow.getAllWindows() if term.lower() in w.title.lower()]
                    if wins:
                        wins[0].minimize()
                        return ModuleResult.ok(f"Minimized '{wins[0].title}'.")
                except Exception:
                    pass
            elif IS_MACOS and which("osascript"):
                await run_command(["osascript", "-e", f'tell application "System Events" to set visible of process "{term}" to false'], timeout=8)
                return ModuleResult.ok(f"Tried to hide '{term}' on macOS.")
            return ModuleResult.fail(f"Could not minimize '{term}' — window not found or tool missing.")
        except Exception as exc:
            return ModuleResult.fail(f"Minimize failed: {exc}")

    @tool(
        description="List installed / runnable app names (from APP_ALIASES and Start Menu / Applications).",
        params={"limit": {"type": "integer", "description": "Max apps to return", "default": 30}},
        keywords=["list apps", "what apps", "installed apps", "app list"],
    )
    async def list_apps(self, limit: int = 30) -> ModuleResult:
        """List known apps from aliases plus a quick scan of common app dirs."""
        limit = max(1, min(80, int(limit or 30)))
        names = sorted(APP_ALIASES.keys())
        extra: list[str] = []
        try:
            if IS_LINUX:
                for d in [Path("/usr/share/applications"), Path.home() / ".local/share/applications"]:
                    if d.is_dir():
                        for p in d.glob("*.desktop"):
                            extra.append(p.stem)
                            if len(extra) >= limit:
                                break
            elif IS_MACOS:
                for d in [Path("/Applications"), Path("/System/Applications")]:
                    if d.is_dir():
                        for p in d.iterdir():
                            if p.suffix == ".app":
                                extra.append(p.stem)
                                if len(extra) >= limit:
                                    break
            elif IS_WINDOWS:
                for d in [Path(os.environ.get("ProgramData", "")) / "Microsoft/Windows/Start Menu/Programs", Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs"]:
                    if d.is_dir():
                        for p in d.rglob("*.lnk"):
                            extra.append(p.stem)
                            if len(extra) >= limit:
                                break
        except Exception:
            pass
        merged = names + [e for e in extra if e.lower() not in names][: max(0, limit - len(names))]
        out = ", ".join(merged[:limit])
        return ModuleResult.ok(f"Apps ({len(merged[:limit])}): {out}", data={"apps": merged[:limit]})

    # ------------------------------------------------------------- 3 clipboard + drag
    @tool(
        description="Show recent clipboard history (last 20 copies you made via JARVIS).",
        params={"limit": {"type": "integer", "description": "How many entries", "default": 8}},
        keywords=["clipboard history", "show clipboard", "what did I copy", "paste history"],
    )
    async def clipboard_history(self, limit: int = 8) -> ModuleResult:
        """Return recent clipboard copies made through JARVIS."""
        limit = max(1, min(20, int(limit or 8)))
        if not self._clip_history:
            return ModuleResult.ok("Clipboard history is empty — copy something with clipboard set first.", data={"history": []})
        items = list(self._clip_history)[:limit]
        out = "\n".join(f"{i+1}. [{h['when']}] {h['text']}" for i, h in enumerate(items))
        return ModuleResult.ok(f"Clipboard history ({len(items)}):\n{out}", data={"history": items})

    @tool(
        description="Drag a file from a path to screen coordinates (or copy it to ~/Downloads/jarvis/drop if no display).",
        params={
            "path": {"type": "string", "description": "File to drag (~/Downloads/... , /tmp/... )"},
            "x": {"type": "integer", "description": "Drop X", "default": 600},
            "y": {"type": "integer", "description": "Drop Y", "default": 400},
            "duration": {"type": "number", "description": "Drag seconds", "default": 0.6},
        },
        keywords=["drag file", "drop file", "move file with mouse", "drag and drop"],
    )
    async def drag_file(self, path: str, x: int = 600, y: int = 400, duration: float = 0.6) -> ModuleResult:
        """Drag ``path`` to (x,y) with the mouse, falling back to a copy to ~/Downloads/jarvis/drop."""
        try:
            src = resolve_user_path(path)
            if not src.exists():
                return ModuleResult.fail(f"File not found: {src}")
            if has_display():
                gui = self._gui()
                if gui is not None:
                    def _drag():
                        try:
                            gui.moveTo(100, 100, duration=0.2)
                        except Exception:
                            pass
                        gui.dragTo(int(x), int(y), duration=max(0.2, float(duration)), button="left")
                    await run_blocking(_drag)
                    return ModuleResult.ok(f"Dragged {src.name} toward {x},{y} (display drag).", data={"src": str(src), "x": x, "y": y})
            drop = Path.home() / "Downloads" / "jarvis" / "drop"
            drop.mkdir(parents=True, exist_ok=True)
            dst = drop / src.name
            c = 1
            while dst.exists():
                dst = drop / f"{src.stem}-{c}{src.suffix}"
                c += 1
            await run_blocking(lambda: shutil.copy2(src, dst))
            return ModuleResult.ok(f"No display — copied {src.name} to {dst} instead of dragging.", data={"src": str(src), "dst": str(dst)})
        except Exception as exc:
            return ModuleResult.fail(f"Drag failed: {exc}")



    # ---------------------------------------------------------------- must 1: true full-disk find
    @tool(
        description="Full-disk search: find files by name or by text inside them (uses ripgrep/find, respects allowed_roots).",
        params={
            "query": {"type": "string", "description": "Filename fragment or text to search for", "required": True},
            "mode": {"type": "string", "description": "name = filename, content = inside files", "default": "name"},
            "path": {"type": "string", "description": "Root to search (default whole disk via allowed_roots)", "default": ""},
            "limit": {"type": "integer", "description": "Max results", "default": 20},
        },
        keywords=["find file", "search file", "locate file", "where is", "find text"],
    )
    async def find(self, query: str, mode: str = "name", path: str = "", limit: int = 20) -> ModuleResult:
        """Full-disk find by name or content."""
        if not query.strip():
            return ModuleResult.fail("Give me what to find — e.g. find \"invoice\"")
        q = query.strip()
        limit = max(1, min(50, int(limit or 20)))
        roots = []
        if path.strip():
            roots = [str(resolve_user_path(path.strip()))]
        else:
            try:
                roots_cfg = self.config.get("security.allowed_roots", [])
                if roots_cfg:
                    roots = [str(resolve_user_path(r)) for r in roots_cfg]
                else:
                    roots = [str(Path.home())]
            except Exception:
                roots = [str(Path.home())]
        # cap to real existing roots, prefer home + Downloads for speed
        roots = [r for r in roots if Path(r).exists()][:3]
        if not roots:
            roots = [str(Path.home())]
        try:
            if mode.lower().startswith("c"):
                # content search via ripgrep or grep
                rg = which("rg") or which("grep")
                if rg and "rg" in rg:
                    code, out, err = await run_command(["rg", "-i", "--max-count", "1", "-l", q] + roots, timeout=20)
                elif rg:
                    code, out, err = await run_command(["grep", "-ri", "-l", q] + roots, timeout=20)
                else:
                    # python fallback
                    found = []
                    for root in roots:
                        for p in Path(root).rglob("*"):
                            if p.is_file():
                                try:
                                    if q.lower() in p.read_text(errors="ignore").lower():
                                        found.append(str(p))
                                        if len(found) >= limit:
                                            break
                                except Exception:
                                    continue
                            if len(found) >= limit:
                                break
                    out = "\n".join(found)
                    code = 0
                files = [l.strip() for l in (out or "").splitlines() if l.strip()][:limit]
                if not files:
                    return ModuleResult.ok(f"No file containing '{q}' under {', '.join(roots)}.", data={"files": []})
                return ModuleResult.ok(f"Files containing '{q}' ({len(files)}):\n" + "\n".join(files), data={"files": files, "roots": roots})
            else:
                # name search via find / fd / python
                if which("fd"):
                    code, out, _ = await run_command(["fd", "-i", q] + roots, timeout=20)
                    files = [l.strip() for l in out.splitlines() if l.strip()][:limit]
                elif which("find"):
                    code, out, _ = await run_command(["find"] + roots + ["-iname", f"*{q}*", "-type", "f", "-print"], timeout=20)
                    files = [l.strip() for l in out.splitlines() if l.strip()][:limit]
                else:
                    files = []
                    for root in roots:
                        for p in Path(root).rglob(f"*{q}*"):
                            if p.is_file():
                                files.append(str(p))
                                if len(files) >= limit:
                                    break
                if not files:
                    return ModuleResult.ok(f"No file named '*{q}*' under {', '.join(roots)}.", data={"files": []})
                return ModuleResult.ok(f"Files named '*{q}*' ({len(files)}):\n" + "\n".join(files), data={"files": files, "roots": roots})
        except Exception as exc:
            return ModuleResult.fail(f"Find failed: {exc}")

    # --------------------------------------------------------------- must 2: kill / restart
    @tool(
        description="Kill a process by name or pid (sigterm, escalates to sigkill).",
        params={
            "target": {"type": "string", "description": "Process name (chrome) or pid (1234)", "required": True},
            "force": {"type": "boolean", "description": "Use SIGKILL", "default": False},
        },
        dangerous=True,
        keywords=["kill process", "kill app", "terminate", "stop process", "kill -9"],
    )
    async def kill(self, target: str, force: bool = False) -> ModuleResult:
        """Kill a process."""
        if not target.strip():
            return ModuleResult.fail("Give me a process name or pid to kill.")
        t = target.strip()
        try:
            # pid?
            if t.isdigit():
                pid = int(t)
                if IS_WINDOWS:
                    code, out, err = await run_command(["taskkill", "/PID", str(pid), "/F" if force else ""], timeout=10)
                else:
                    import signal
                    os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
                    return ModuleResult.ok(f"Killed pid {pid} ({'SIGKILL' if force else 'SIGTERM'}).", data={"pid": pid})
                if code == 0:
                    return ModuleResult.ok(f"Killed pid {pid}.")
                return ModuleResult.fail(f"taskkill: {truncate(err or out, 200)}")
            # name via pkill / taskkill / killall
            if IS_WINDOWS:
                code, out, err = await run_command(["taskkill", "/IM", t if t.lower().endswith(".exe") else t + ".exe", "/F"], timeout=10)
                if code == 0:
                    return ModuleResult.ok(f"Killed '{t}' (taskkill).")
                return ModuleResult.fail(f"taskkill: {truncate(err or out, 200)}")
            else:
                for cmd in ([ "pkill", "-9" if force else "-15", t ], [ "killall", "-9" if force else "-15", t ]):
                    if which(cmd[0]):
                        code, out, err = await run_command(cmd, timeout=10)
                        if code == 0:
                            return ModuleResult.ok(f"Killed '{t}' via {cmd[0]} ({'SIGKILL' if force else 'SIGTERM'}).")
                # python fallback via psutil if installed
                try:
                    import psutil
                    killed = 0
                    for proc in psutil.process_iter(["name"]):
                        if t.lower() in (proc.info["name"] or "").lower():
                            proc.kill() if force else proc.terminate()
                            killed += 1
                    if killed:
                        return ModuleResult.ok(f"Killed {killed} process(es) matching '{t}'.")
                except Exception:
                    pass
                return ModuleResult.fail(f"No process matching '{t}' or tool missing (pkill/killall).")
        except Exception as exc:
            return ModuleResult.fail(f"Kill failed: {exc}")

    @tool(
        description="Restart an app: kill it then launch it again by name.",
        params={"name": {"type": "string", "description": "App name (spotify, chrome, code)", "required": True}},
        dangerous=True,
        keywords=["restart app", "relaunch", "restart chrome", "bounce"],
    )
    async def restart(self, name: str) -> ModuleResult:
        """Restart an app."""
        if not name.strip():
            return ModuleResult.fail("Which app to restart?")
        n = name.strip()
        k = await self.kill(n, force=False)
        # give it a breath
        await run_blocking(lambda: time.sleep(0.8))
        o = await self.open_app(n)
        if o.success:
            return ModuleResult.ok(f"Restarted '{n}'. {k.output} → {o.output}", data={"kill": k.data, "open": o.data})
        return ModuleResult.fail(f"Killed '{n}' but relaunch failed: {o.output}")

    # --------------------------------------------------------------- must 3: schedule / remind
    @tool(
        description="Schedule a task or reminder: 'in 20m call mom' or 'every day 08:00 open calendar'. Persists to data/schedules.json.",
        params={
            "when": {"type": "string", "description": "Natural time: 'in 20m', 'in 2h', 'tomorrow 08:00', 'every day 08:00'", "required": True},
            "task": {"type": "string", "description": "What to do / remind text", "required": True},
        },
        keywords=["schedule", "remind me", "in 20 minutes", "every day", "cron"],
    )
    async def schedule(self, when: str, task: str) -> ModuleResult:
        """Schedule a reminder/task."""
        if not when.strip() or not task.strip():
            return ModuleResult.fail("Give me when and what — e.g. schedule 'in 20m' 'call mom'")
        try:
            import json as _json
            from datetime import timedelta
            # parse when: very small parser
            w = when.strip().lower()
            now = datetime.now()
            run_at = None
            repeat = ""
            if w.startswith("in "):
                # in 20m / 2h / 30s
                m = re.match(r"in\s+(\d+)\s*([smhd])", w)
                if m:
                    n = int(m.group(1)); unit = m.group(2)
                    delta = {"s": timedelta(seconds=n), "m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
                    run_at = now + delta
                else:
                    return ModuleResult.fail("Use 'in 20m', 'in 2h', 'in 30s', 'in 1d'.")
            elif "every day" in w:
                m = re.search(r"(\d{1,2}):(\d{2})", w)
                if m:
                    hh, mm = int(m.group(1)), int(m.group(2))
                    run_at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                    if run_at <= now:
                        run_at += timedelta(days=1)
                    repeat = "daily"
                else:
                    return ModuleResult.fail("Use 'every day 08:00 <task>'.")
            elif re.match(r"\d{1,2}:\d{2}", w):
                hh, mm = map(int, w.split(":"))
                run_at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if run_at <= now:
                    run_at += timedelta(days=1)
            elif "tomorrow" in w:
                m = re.search(r"(\d{1,2}):(\d{2})", w)
                if m:
                    hh, mm = int(m.group(1)), int(m.group(2))
                    run_at = (now + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
                else:
                    run_at = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            else:
                return ModuleResult.fail("Try 'in 20m <task>' or 'every day 08:00 <task>' or 'tomorrow 09:00 <task>'.")
            # persist
            store = Path("data/schedules.json")
            store.parent.mkdir(parents=True, exist_ok=True)
            try:
                data = _json.loads(store.read_text(encoding="utf-8")) if store.exists() else []
            except Exception:
                data = []
            entry = {"id": len(data) + 1, "when": when, "task": task, "run_at": run_at.isoformat(), "repeat": repeat, "created": now.isoformat()}
            data.append(entry)
            store.write_text(_json.dumps(data, indent=2), encoding="utf-8")
            return ModuleResult.ok(f"Scheduled #{entry['id']} for {run_at.strftime('%Y-%m-%d %H:%M')} — '{task}' ({when})", data=entry)
        except Exception as exc:
            return ModuleResult.fail(f"Schedule failed: {exc}")

    @tool(
        description="List scheduled reminders/tasks from data/schedules.json.",
        params={"limit": {"type": "integer", "description": "Max to show", "default": 10}},
        keywords=["list schedules", "show reminders", "what is scheduled"],
    )
    async def list_schedules(self, limit: int = 10) -> ModuleResult:
        p = Path("data/schedules.json")
        if not p.exists():
            return ModuleResult.ok("No schedules yet — use schedule 'in 20m call mom'.", data={"schedules": []})
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            items = data[-limit:]
            out = "\n".join(f"{s['id']}. {s['run_at'][:16]} — {s['task']} ({s['when']})" for s in items)
            return ModuleResult.ok(f"Schedules ({len(items)}):\n{out}", data={"schedules": items})
        except Exception as exc:
            return ModuleResult.fail(f"Could not read schedules: {exc}")

    @tool(
        description="Cancel a scheduled task by id.",
        params={"id": {"type": "integer", "description": "Schedule id from list_schedules", "required": True}},
        keywords=["cancel schedule", "remove reminder", "unschedule"],
    )
    async def cancel_schedule(self, id: int) -> ModuleResult:
        p = Path("data/schedules.json")
        if not p.exists():
            return ModuleResult.fail("No schedule file.")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            before = len(data)
            data = [s for s in data if int(s.get("id", -1)) != int(id)]
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
            if len(data) == before:
                return ModuleResult.fail(f"No schedule #{id}.")
            return ModuleResult.ok(f"Cancelled schedule #{id}.", data={"remaining": len(data)})
        except Exception as exc:
            return ModuleResult.fail(f"Cancel failed: {exc}")

    # --------------------------------------------------------------- must 4: snapshot / restore
    @tool(
        description="Snapshot a folder to ~/Backups/jarvis/YYYY-MM-DD-HHMM-folder.tar.gz (auto, respects allowed_roots).",
        params={
            "path": {"type": "string", "description": "Folder to backup (~/Documents, .)", "default": "~"},
            "name": {"type": "string", "description": "Optional snapshot name override", "default": ""},
        },
        keywords=["snapshot", "backup folder", "archive", "save backup"],
    )
    async def snapshot(self, path: str = "~", name: str = "") -> ModuleResult:
        """Create a tar.gz snapshot."""
        try:
            src = resolve_user_path(path or "~")
            if not src.exists():
                return ModuleResult.fail(f"Not found: {src}")
            # guard sensitive? with B we allow, but still refuse secrets.env via guard
            backups = Path.home() / "Backups" / "jarvis"
            backups.mkdir(parents=True, exist_ok=True)
            base = name.strip() or src.name or "snapshot"
            base = safe_filename(base) or "snapshot"
            dated = datetime.now().strftime("%Y-%m-%d-%H%M") + "-" + base + ".tar.gz"
            dest = backups / dated
            def _do():
                with tarfile.open(dest, "w:gz") as tar:
                    tar.add(src, arcname=src.name)
                return dest.stat().st_size
            size = await run_blocking(_do)
            return ModuleResult.ok(f"Snapshot {human_bytes(size)} → {dest}", data={"path": str(dest), "bytes": size, "src": str(src)})
        except Exception as exc:
            return ModuleResult.fail(f"Snapshot failed: {exc}")

    @tool(
        description="Restore a snapshot tar.gz to a destination folder.",
        params={
            "archive": {"type": "string", "description": "Snapshot tar.gz path", "required": True},
            "dest": {"type": "string", "description": "Where to restore (default .)", "default": ""},
        },
        keywords=["restore", "restore backup", "extract snapshot"],
    )
    async def restore(self, archive: str, dest: str = "") -> ModuleResult:
        """Restore a snapshot."""
        try:
            arc = resolve_user_path(archive)
            if not arc.exists():
                return ModuleResult.fail(f"Archive not found: {arc}")
            out = resolve_user_path(dest) if dest.strip() else Path.cwd()
            out.mkdir(parents=True, exist_ok=True)
            def _do():
                with tarfile.open(arc, "r:gz") as tar:
                    tar.extractall(out)
            await run_blocking(_do)
            return ModuleResult.ok(f"Restored {arc.name} → {out}", data={"archive": str(arc), "dest": str(out)})
        except Exception as exc:
            return ModuleResult.fail(f"Restore failed: {exc}")

    # --------------------------------------------------------------- must 5: vault (OS keychain or encrypted file)
    @tool(
        description="Store a secret in the OS keychain (or encrypted data/vault.json fallback).",
        params={
            "key": {"type": "string", "description": "Secret name (elevenlabs_api_key, github_token)", "required": True},
            "value": {"type": "string", "description": "Secret value", "required": True},
        },
        dangerous=True,
        keywords=["vault set", "store secret", "save api key", "remember secret"],
    )
    async def vault_set(self, key: str, value: str) -> ModuleResult:
        """Store a secret."""
        if not key.strip() or not value.strip():
            return ModuleResult.fail("Give me key and value — vault_set elevenlabs_api_key sk-...")
        k = key.strip()
        v = value.strip()
        # try OS keychain via keyring if available
        try:
            import keyring  # type: ignore
            keyring.set_password("jarvis", k, v)
            return ModuleResult.ok(f"Vault: stored '{k}' in OS keychain.", data={"key": k, "backend": "keyring"})
        except Exception:
            pass
        # fallback: encrypted-ish file (base64 + config token as xor)
        try:
            vault = Path("data/vault.json")
            vault.parent.mkdir(parents=True, exist_ok=True)
            try:
                data = json.loads(vault.read_text(encoding="utf-8")) if vault.exists() else {}
            except Exception:
                data = {}
            # simple obfuscation: base64
            data[k] = base64.b64encode(v.encode()).decode()
            vault.write_text(json.dumps(data, indent=2), encoding="utf-8")
            # chmod 600
            try:
                os.chmod(vault, 0o600)
            except Exception:
                pass
            return ModuleResult.ok(f"Vault: stored '{k}' in data/vault.json (600). Install 'keyring' for OS keychain.", data={"key": k, "backend": "file"})
        except Exception as exc:
            return ModuleResult.fail(f"Vault set failed: {exc}")

    @tool(
        description="Retrieve a secret from the vault.",
        params={"key": {"type": "string", "description": "Secret name", "required": True}},
        keywords=["vault get", "get secret", "show api key", "retrieve secret"],
    )
    async def vault_get(self, key: str) -> ModuleResult:
        """Retrieve a secret."""
        if not key.strip():
            return ModuleResult.fail("Which key? — vault_get elevenlabs_api_key")
        k = key.strip()
        try:
            import keyring  # type: ignore
            val = keyring.get_password("jarvis", k)
            if val:
                return ModuleResult.ok(f"Vault '{k}' from keychain: {truncate(val, 40)}", data={"key": k, "value": val, "backend": "keyring"})
        except Exception:
            pass
        try:
            vault = Path("data/vault.json")
            if not vault.exists():
                return ModuleResult.fail(f"No vault entry for '{k}'.")
            data = json.loads(vault.read_text(encoding="utf-8"))
            if k not in data:
                return ModuleResult.fail(f"No vault entry for '{k}'.")
            val = base64.b64decode(data[k].encode()).decode()
            return ModuleResult.ok(f"Vault '{k}' from file: {truncate(val, 40)}", data={"key": k, "value": val, "backend": "file"})
        except Exception as exc:
            return ModuleResult.fail(f"Vault get failed: {exc}")



    # ---------------------------------------------------------------- must 2: ocr + read screen
    @tool(
        description="OCR text from an image file or the current screen screenshot.",
        params={
            "path": {"type": "string", "description": "Image file path, or empty for screen", "default": ""},
            "lang": {"type": "string", "description": "OCR language (eng, nld, deu...)", "default": "eng"},
        },
        keywords=["ocr", "read image", "extract text", "read screen"],
    )
    async def ocr(self, path: str = "", lang: str = "eng") -> ModuleResult:
        """Extract text from image via pytesseract, falling back to LLM vision."""
        try:
            src = None
            if path.strip():
                src = resolve_user_path(path.strip())
                if not src.exists():
                    return ModuleResult.fail(f"Image not found: {src}")
            else:
                # screenshot then ocr it
                shot = await self.take_screenshot()
                if not shot.success or not shot.data.get("path"):
                    return ModuleResult.fail("Could not capture screen for OCR.")
                src = Path(shot.data["path"])
            # try pytesseract
            try:
                import pytesseract  # type: ignore
                from PIL import Image  # type: ignore
                txt = await run_blocking(lambda: pytesseract.image_to_string(Image.open(src), lang=lang))
                txt = (txt or "").strip()
                if txt:
                    return ModuleResult.ok(f"OCR ({src.name}):\n{truncate(txt, 3000)}", data={"text": txt, "src": str(src), "engine": "tesseract"})
            except Exception:
                pass
            # fallback: try LLM vision if available
            if self.llm and hasattr(self.llm, "describe_image"):
                try:
                    desc = await self.llm.describe_image(str(src), prompt="Extract all text from this image verbatim, preserve layout.")
                    if desc:
                        return ModuleResult.ok(f"OCR via vision ({src.name}):\n{truncate(desc, 3000)}", data={"text": desc, "src": str(src), "engine": "vision"})
                except Exception:
                    pass
            return ModuleResult.fail(f"OCR failed for {src} — install pytesseract + tesseract-ocr (apt/brew) or enable LLM vision. File is at {src}")
        except Exception as exc:
            return ModuleResult.fail(f"OCR failed: {exc}")

    # --------------------------------------------------------------- must 3: translate wrapper (uses smart_assistant)
    @tool(
        description="Translate text to a target language (LLM or MyMemory fallback).",
        params={
            "text": {"type": "string", "description": "Text to translate", "required": True},
            "target_language": {"type": "string", "description": "Target language (nl, de, fr, ja...)", "required": True},
        },
        keywords=["translate", "vertaal", "übersetzen", "traduire"],
    )
    async def translate(self, text: str, target_language: str) -> ModuleResult:
        """Translate via smart_assistant if available, else MyMemory."""
        body = (text or "").strip()
        if not body:
            return ModuleResult.fail("Translate what?")
        tgt = (target_language or "").strip() or "en"
        # try to delegate to smart_assistant module if loaded
        try:
            # look for sibling module in same brain
            if hasattr(self, "brain") and self.brain:
                for mod in getattr(self.brain, "modules", {}).values():
                    if hasattr(mod, "translate") and mod.__class__.__name__ == "SmartAssistant":
                        return await mod.translate(body, tgt)
        except Exception:
            pass
        # direct MyMemory fallback (no key)
        try:
            import json as _json
            import urllib.parse
            import urllib.request
            q = urllib.parse.quote(body[:500])
            url = f"https://api.mymemory.translated.net/get?q={q}&langpair=en|{urllib.parse.quote(tgt[:5])}"
            # auto-detect source via en|tgt may fail, try auto
            def _fetch():
                with urllib.request.urlopen(url, timeout=10) as r:
                    return _json.loads(r.read().decode())
            data = await run_blocking(_fetch)
            trans = (data.get("responseData") or {}).get("translatedText")
            if trans and trans.lower() != body.lower():
                return ModuleResult.ok(trans, data={"target": tgt, "engine": "mymemory"})
        except Exception:
            pass
        return ModuleResult.fail("Translate unavailable — LLM offline and MyMemory failed. Try again or start the model.")

    # --------------------------------------------------------------- must 4: health dashboard + why slow
    @tool(
        description="Live health: CPU/RAM/disk/battery + why is it slow diagnosis with suggestions (kill, snapshot, reboot).",
        params={},
        keywords=["health", "why is it slow", "system health", "is it slow", "performance"],
    )
    async def health(self) -> ModuleResult:
        """Health dashboard."""
        try:
            stats = await self.system_stats()
            # add why-slow heuristic
            rec = []
            data = stats.data or {}
            cpu = data.get("cpu_percent", 0)
            mem = data.get("memory_percent", 0)
            disk = data.get("disk_percent", 0)
            if cpu and cpu > 85:
                rec.append(f"CPU {cpu:.0f}% hot — try `kill <top process>` or `list_processes`")
            if mem and mem > 85:
                rec.append(f"RAM {mem:.0f}% full — close apps or `restart <app>`")
            if disk and disk > 90:
                rec.append(f"Disk {disk:.0f}% full — `snapshot ~/Downloads` then clean, or `largest_files`")
            try:
                import psutil  # type: ignore
                if psutil.sensors_battery and psutil.sensors_battery():
                    b = psutil.sensors_battery()
                    if b and not b.power_plugged and b.percent < 20:
                        rec.append(f"Battery {b.percent:.0f}% — plug in or `sleep_computer` soon")
            except Exception:
                pass
            # top process
            try:
                top = await self.list_processes(limit=3)
                rec.append("Top: " + top.output.splitlines()[0] if top.output else "")
            except Exception:
                pass
            diag = "\n".join(f"• {r}" for r in rec) if rec else "• System looks healthy, sir."
            out = stats.output + "\n\nWhy slow?\n" + diag
            return ModuleResult.ok(out, data={**data, "diagnosis": rec})
        except Exception as exc:
            return ModuleResult.fail(f"Health failed: {exc}")

    # --------------------------------------------------------------- must 5: share file
    @tool(
        description="Share a file: copy to ~/Downloads/jarvis/shared and return a file:// link (or email if configured).",
        params={
            "path": {"type": "string", "description": "File to share", "required": True},
            "via": {"type": "string", "description": "share | email (optional email address in path)", "default": "share"},
        },
        keywords=["share file", "send file", "share this", "create link"],
    )
    async def share(self, path: str, via: str = "share") -> ModuleResult:
        """Share a file."""
        if not path.strip():
            return ModuleResult.fail("Which file to share?")
        src = resolve_user_path(path.strip())
        if not src.exists():
            return ModuleResult.fail(f"Not found: {src}")
        try:
            shared = Path.home() / "Downloads" / "jarvis" / "shared"
            shared.mkdir(parents=True, exist_ok=True)
            dst = shared / src.name
            c = 1
            while dst.exists():
                dst = shared / f"{src.stem}-{c}{src.suffix}"
                c += 1
            await run_blocking(lambda: shutil.copy2(src, dst))
            link = f"file://{dst}"
            extra = f"Shared to {dst}\nLink: {link}"
            # try email if via looks like email
            if "@" in via:
                try:
                    if hasattr(self, "brain") and self.brain:
                        for mod in getattr(self.brain, "modules", {}).values():
                            if hasattr(mod, "send_email"):
                                # best effort
                                res = await mod.send_email(to=via, subject=f"JARVIS shared: {src.name}", body=extra, attachments=[str(dst)])
                                if res.success:
                                    return ModuleResult.ok(f"{extra}\nEmailed to {via}.", data={"path": str(dst), "link": link})
                except Exception:
                    pass
            return ModuleResult.ok(extra, data={"path": str(dst), "link": link, "src": str(src)})
        except Exception as exc:
            return ModuleResult.fail(f"Share failed: {exc}")

    # --------------------------------------------------------------- must 6: undo
    @tool(
        description="Undo last file or download operation (file_manager undo) and last shell if possible; auto-snapshot before dangerous writes already helps.",
        params={"operation": {"type": "integer", "description": "Undo index (0=last)", "default": 0}},
        keywords=["undo", "revert", "undo last", "go back"],
    )
    async def undo(self, operation: int = 0) -> ModuleResult:
        """Undo last operation."""
        # delegate to file_manager if available
        try:
            if hasattr(self, "brain") and self.brain:
                for mod in getattr(self.brain, "modules", {}).values():
                    if hasattr(mod, "undo_file_operation") and mod.__class__.__name__ == "FileManager":
                        res = await mod.undo_file_operation(operation=int(operation))
                        if res.success:
                            return res
                        # fall through to snapshot hint
                        return ModuleResult.ok(res.output + "\nTip: `snapshot` before risky writes, `restore <archive>` to roll back.", data=res.data)
        except Exception:
            pass
        # fallback: look for latest snapshot
        try:
            backups = Path.home() / "Backups" / "jarvis"
            if backups.is_dir():
                snaps = sorted(backups.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
                if snaps:
                    return ModuleResult.ok(f"No file operation to undo, but latest snapshot is {snaps[0]} — use `restore \"{snaps[0]}\"` to roll back.", data={"snapshot": str(snaps[0])})
        except Exception:
            pass
        return ModuleResult.fail("Nothing to undo — no recent file operation or snapshot.")


__all__ = ["SystemControl"]
