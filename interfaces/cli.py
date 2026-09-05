# /interfaces/cli.py
"""Rich terminal interface — the always-available fallback to voice.

Provides a colourful REPL with panels, status spinners, slash-style commands
and syntax-highlighted code output. Degrades to plain ``print``/``input`` when
the ``rich`` library is not installed.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, List, Optional

from utils.helpers import extract_code_blocks, human_duration, truncate
from utils.logger import get_logger

logger = get_logger("interfaces.cli")

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.text import Text

    HAS_RICH = True
except Exception:  # pragma: no cover - cosmetic fallback
    HAS_RICH = False
    Console = None  # type: ignore[assignment]


BANNER = r"""
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
"""

HELP_ROWS: List[tuple[str, str]] = [
    ("help", "Show this help"),
    ("status", "LLM, memory, modules and security status"),
    ("tools", "List every tool JARVIS can call"),
    ("memory", "Long-term memory statistics"),
    ("remember <text>", "Store a fact permanently"),
    ("recall <query>", "Search long-term memory"),
    ("forget <text>", "Delete matching memories"),
    ("clear", "Clear the screen and the short-term context"),
    ("voice", "Switch to voice mode (if audio is available)"),
    ("web", "Start the phone/LAN web interface"),
    ("index [path]", "Add documents to the private knowledge base"),
    ("look", "Look at the screen with the local vision model"),
    ("stream on|off", "Toggle live token-by-token replies"),
    ("mute / unmute", "Toggle spoken replies in text mode"),
    ("config", "Show the active configuration"),
    ("exit / quit", "Shut JARVIS down"),
]


class CLI:
    """Interactive terminal front-end for the brain."""

    def __init__(self, brain: Any, voice: Any = None) -> None:
        """Args:
        brain: A :class:`core.brain.Brain` instance.
        voice: Optional :class:`interfaces.voice.VoiceInterface` for spoken replies.
        """
        self.brain = brain
        self.voice = voice
        self.console = Console(highlight=False) if HAS_RICH else None
        self.speak_replies = False
        self.running = False
        self._web_task: Optional[asyncio.Task] = None
        self.user_name = str(brain.config.get("user.name", "Sir"))
        self.assistant_name = str(brain.config.get("assistant.name", "JARVIS"))

    # ------------------------------------------------------------------ print
    def print(self, message: Any = "", style: str = "") -> None:
        """Print through rich when available."""
        if self.console is not None:
            self.console.print(message, style=style or None)
        else:
            print(message)

    def rule(self, title: str = "") -> None:
        """Draw a horizontal rule."""
        if self.console is not None:
            self.console.rule(title)
        else:
            print("-" * 60 + (f" {title}" if title else ""))

    def banner(self) -> None:
        """Show the start-up banner."""
        if self.console is not None:
            self.console.print(Text(BANNER, style="bold cyan"))
            self.console.print(
                Text(
                    "  Just A Rather Very Intelligent System — 100% local, 100% free",
                    style="dim italic",
                )
            )
            self.console.print()
        else:
            print(BANNER)
            print("  Just A Rather Very Intelligent System — 100% local, 100% free\n")

    def assistant_panel(self, text: str, subtitle: str = "") -> None:
        """Render an assistant reply, syntax-highlighting any code blocks."""
        if self.console is None:
            print(f"\n{self.assistant_name}: {text}\n")
            return

        blocks = extract_code_blocks(text)
        if blocks:
            renderables: List[Any] = []
            remainder = text
            for language, code in blocks:
                fence = re.search(
                    r"```[\w+#.-]*\n" + re.escape(code) + r"\s*```", remainder
                )
                if fence:
                    before = remainder[: fence.start()].strip()
                    remainder = remainder[fence.end():]
                    if before:
                        renderables.append(Markdown(before))
                renderables.append(
                    Syntax(code, language or "text", theme="monokai", line_numbers=False,
                           word_wrap=True)
                )
            if remainder.strip():
                renderables.append(Markdown(remainder.strip()))
            body: Any = Group(*renderables)
        else:
            body = Markdown(text)

        self.console.print(
            Panel(
                body,
                title=f"[bold cyan]{self.assistant_name}[/]",
                subtitle=subtitle or None,
                border_style="cyan",
                padding=(0, 1),
            )
        )

    def info(self, message: str) -> None:
        """Print a dim informational line."""
        self.print(f"[dim]{message}[/dim]" if HAS_RICH else message)

    def warn(self, message: str) -> None:
        """Print a warning."""
        self.print(f"[yellow]! {message}[/yellow]" if HAS_RICH else f"! {message}")

    def error(self, message: str) -> None:
        """Print an error."""
        self.print(f"[bold red]✗ {message}[/bold red]" if HAS_RICH else f"x {message}")

    def success(self, message: str) -> None:
        """Print a success line."""
        self.print(f"[green]✓ {message}[/green]" if HAS_RICH else f"v {message}")

    # ------------------------------------------------------------------ input
    async def prompt(self) -> str:
        """Read one line from the user without blocking the event loop."""
        loop = asyncio.get_running_loop()

        def _read() -> str:
            if self.console is not None:
                self.console.print(f"[bold green]{self.user_name}[/] ", end="")
                return input("› ")
            return input(f"{self.user_name} › ")

        try:
            return (await loop.run_in_executor(None, _read)).strip()
        except (EOFError, KeyboardInterrupt):
            return "exit"

    async def confirm(self, message: str) -> bool:
        """Ask the user to approve a dangerous action (security hook)."""
        loop = asyncio.get_running_loop()

        def _ask() -> str:
            if self.console is not None:
                self.console.print(
                    Panel(message, title="[bold yellow]Confirmation required[/]",
                          border_style="yellow")
                )
                return input("Proceed? [y/N] ")
            return input(f"\n[confirm] {message}\nProceed? [y/N] ")

        try:
            answer = await loop.run_in_executor(None, _ask)
        except Exception:
            return False
        approved = answer.strip().lower() in {"y", "yes", "yeah", "yep", "do it", "confirm"}
        if approved:
            self.success("Confirmed.")
        else:
            self.warn("Cancelled.")
        return approved

    def notify(self, message: str) -> None:
        """Display an asynchronous notification (timers, reminders)."""
        if self.console is not None:
            self.console.print(
                Panel(message, title="[bold magenta]Notification[/]", border_style="magenta")
            )
        else:
            print(f"\n*** {message} ***\n")

    # --------------------------------------------------------------- commands
    async def handle_command(self, text: str) -> bool:
        """Handle a built-in CLI command.

        Args:
            text: The raw user input.

        Returns:
            True when the input was consumed as a command.
        """
        command = text.strip().lstrip("/").lower()
        argument = text.strip().split(" ", 1)[1].strip() if " " in text.strip() else ""

        if command in {"exit", "quit", "bye", "goodbye"}:
            self.running = False
            return True

        if command in {"help", "?", "commands"}:
            self.show_help()
            return True

        if command == "status":
            await self.show_status()
            return True

        if command == "tools":
            self.show_tools()
            return True

        if command in {"memory", "mem"}:
            await self.show_memory()
            return True

        if command.startswith("remember "):
            stored = await self.brain.memory.remember(
                argument, category="fact", importance=0.8, source="cli"
            )
            if stored:
                self.success(f"Remembered: {argument}")
            else:
                self.error("Storage failed — long-term memory is unavailable.")
            return True

        if command.startswith("recall "):
            hits = await self.brain.memory.recall(argument, k=8, min_score=0.05)
            if not hits:
                self.info("Nothing relevant in memory.")
            else:
                for hit in hits:
                    self.print(f"  ({hit.category}, {hit.score:.2f}) {hit.text}")
            return True

        if command.startswith("forget "):
            removed = await self.brain.memory.forget(argument)
            self.success(f"Removed {removed} memory entrie(s).")
            return True

        if command in {"clear", "cls"}:
            if self.console is not None:
                self.console.clear()
            await self.brain.memory.clear_short_term()
            self.info("Screen and short-term context cleared.")
            return True

        if command == "config":
            self.show_config()
            return True

        if command in {"mute", "unmute"}:
            self.speak_replies = command == "unmute"
            self.info(f"Spoken replies {'on' if self.speak_replies else 'off'}.")
            return True

        if command in {"voice", "voice mode"}:
            await self.start_voice_mode()
            return True

        if command.startswith("stream"):
            if argument in {"on", "off"}:
                self.brain.streaming_enabled = argument == "on"
            else:
                self.brain.streaming_enabled = not self.brain.streaming_enabled
            self.info(
                f"Streaming replies {'on' if self.brain.streaming_enabled else 'off'}."
            )
            return True

        if command.split(" ")[0] in {"index", "reindex"}:
            await self._run_module("knowledge", "index_documents", {"path": argument})
            return True

        if command in {"look", "screen", "see"}:
            await self._run_module("vision", "describe_screen", {})
            return True

        if command.split(" ")[0] == "web":
            await self.start_web(argument)
            return True

        return False

    async def _run_module(self, module: str, tool_name: str, params: dict) -> None:
        """Run one module tool directly and print the outcome."""
        target = self.brain.modules.get(module)
        if target is None:
            self.error(
                f"The {module} module is disabled — enable modules.{module} in config.yaml."
            )
            return
        if self.console is not None:
            with self.console.status(f"[cyan]{module}…", spinner="dots"):
                result = await target.call_tool(tool_name, params)
        else:
            result = await target.call_tool(tool_name, params)
        if result.success:
            self.assistant_panel(result.output or "Done.")
        else:
            self.error(result.error or result.output or "That did not work.")

    async def start_web(self, argument: str = "") -> None:
        """Start (or report) the web interface in the background."""
        try:
            from interfaces.web import WebInterface
        except Exception as exc:
            self.error(f"Web interface unavailable: {exc}")
            return
        if self._web_task is not None and not self._web_task.done():
            self.info("The web interface is already running.")
            return
        port = int(argument) if argument.isdigit() else None
        server = WebInterface(self.brain, self.brain.config, port=port)
        self._web_task = asyncio.create_task(server.serve())
        await asyncio.sleep(1.0)
        self.success(f"Web interface listening on {server.url}")
        self.info("Open that address on your phone — same Wi-Fi, no cloud involved.")

    def show_help(self) -> None:
        """Print the command reference."""
        if self.console is not None:
            table = Table(title="JARVIS commands", border_style="cyan", show_lines=False)
            table.add_column("Command", style="bold green", no_wrap=True)
            table.add_column("Description", style="white")
            for name, description in HELP_ROWS:
                table.add_row(name, description)
            self.console.print(table)
            self.console.print(
                "[dim]Anything else is treated as a request: "
                '"open chrome", "what\'s the weather", "remind me to stretch in 20 minutes".[/dim]'
            )
        else:
            for name, description in HELP_ROWS:
                print(f"  {name:<20} {description}")

    async def show_status(self) -> None:
        """Show a full system status report."""
        report = await self.brain.status_report()
        llm = report["llm"]
        memory = report["memory"]

        if self.console is None:
            print(report)
            return

        table = Table(title="System status", border_style="cyan")
        table.add_column("Component", style="bold")
        table.add_column("State")
        table.add_row(
            "LLM (Ollama)",
            f"[green]online[/] — {llm['model']}" if llm["online"] else "[red]offline[/]",
        )
        table.add_row("Host", llm["host"])
        table.add_row("Installed models", ", ".join(llm["installed"][:6]) or "none")
        table.add_row("Memory backend", memory["backend"])
        table.add_row(
            "Memory",
            f"{memory['short_term']}/{memory['short_term_limit']} short-term, "
            f"{memory['long_term']} long-term",
        )
        table.add_row(
            "Modules",
            ", ".join(f"{name} ({count})" for name, count in report["modules"].items()) or "none",
        )
        table.add_row("Turns this session", str(report["turns"]))
        table.add_row("Uptime", human_duration(report["uptime_seconds"]))
        table.add_row("Platform", report["os"])
        table.add_row(
            "Safety",
            "confirmation on" if report["security"]["confirm_dangerous"] else "confirmation off",
        )
        if self.voice is not None:
            voice_report = await self.voice.self_test()
            table.add_row(
                "Voice",
                f"mic={voice_report['microphone']}, stt={voice_report['stt']}, "
                f"tts={voice_report['tts']}, wake={voice_report['wake_engine']}",
            )
        self.console.print(table)

    def show_tools(self) -> None:
        """List every tool exposed by every loaded module."""
        if self.console is None:
            for name, module in self.brain.modules.items():
                print(f"\n{name}:")
                for tool_name, spec in module.tools.items():
                    print(f"  {tool_name}: {spec.description}")
            return

        for name, module in self.brain.modules.items():
            table = Table(title=f"{name} — {module.description}", border_style="blue")
            table.add_column("Tool", style="bold green", no_wrap=True)
            table.add_column("Description")
            for tool_name, spec in module.tools.items():
                table.add_row(tool_name, spec.description)
            self.console.print(table)

    async def show_memory(self) -> None:
        """Show memory statistics."""
        stats = await self.brain.memory.stats()
        if self.console is None:
            print(stats)
            return
        table = Table(title="Memory", border_style="magenta")
        table.add_column("Metric", style="bold")
        table.add_column("Value")
        for key, value in stats.items():
            table.add_row(str(key), truncate(str(value), 90))
        self.console.print(table)

    def show_config(self) -> None:
        """Print the effective configuration."""
        data = self.brain.config.as_dict()
        if self.console is None:
            print(data)
            return
        table = Table(title="Configuration", border_style="green")
        table.add_column("Key", style="bold")
        table.add_column("Value")
        for section, values in data.items():
            if isinstance(values, dict):
                for key, value in values.items():
                    table.add_row(f"{section}.{key}", truncate(str(value), 70))
            else:
                table.add_row(section, truncate(str(values), 70))
        self.console.print(table)

    async def start_voice_mode(self) -> None:
        """Hand control over to the voice interface."""
        if self.voice is None or not self.voice.available:
            self.error(
                "Voice mode unavailable — check the microphone, faster-whisper and edge-tts."
            )
            return
        self.info("Voice mode engaged. Say the wake word. Ctrl+C returns to text.")
        try:
            await self.voice.run(self.brain.process)
        except KeyboardInterrupt:
            self.info("Back to text mode.")

    # ------------------------------------------------------------------- loop
    async def run(self) -> None:
        """Run the interactive text REPL until the user exits."""
        self.running = True
        self.banner()

        greeting = await self.brain.greeting()
        self.assistant_panel(greeting)
        if self.speak_replies and self.voice is not None:
            await self.voice.speak(greeting)
        self.info("Type 'help' for commands, 'voice' for voice mode, 'exit' to quit.")

        while self.running:
            try:
                text = await self.prompt()
            except KeyboardInterrupt:
                break
            if not text:
                continue
            if await self.handle_command(text):
                continue

            reply = await self._think(text)
            self.assistant_panel(reply, subtitle=self._subtitle())
            if self.speak_replies and self.voice is not None:
                await self.voice.speak(reply)

        self.info("Goodbye.")

    async def _think(self, text: str) -> str:
        """Process input, streaming the reply live when possible.

        Args:
            text: The user's request.

        Returns:
            The complete reply text.
        """
        streaming = bool(getattr(self.brain, "streaming_enabled", False)) and HAS_RICH
        if self.console is None:
            return await self._guarded(self.brain.process(text))
        if not streaming:
            with self.console.status("[cyan]thinking…", spinner="dots"):
                return await self._guarded(self.brain.process(text))

        buffer: List[str] = []
        with Live(
            Panel(
                Text("thinking…", style="dim"),
                title=f"[bold cyan]{self.assistant_name}[/]",
                border_style="cyan",
                padding=(0, 1),
            ),
            console=self.console,
            refresh_per_second=12,
            transient=True,
        ) as live:

            def on_token(token: str) -> None:
                """Append a token and refresh the live panel."""
                buffer.append(token)
                live.update(
                    Panel(
                        Text("".join(buffer)),
                        title=f"[bold cyan]{self.assistant_name}[/]",
                        border_style="cyan",
                        padding=(0, 1),
                    )
                )

            reply = await self._guarded(self.brain.process(text, on_token=on_token))
        return reply or "".join(buffer)

    async def _guarded(self, coroutine: Any) -> str:
        """Await the brain, converting Ctrl+C into a clean cancellation."""
        task = asyncio.ensure_future(coroutine)
        try:
            return await task
        except KeyboardInterrupt:
            self.brain.cancel()
            self.warn("Cancelled.")
            try:
                return await task
            except Exception:
                return "Stopped."
        except asyncio.CancelledError:
            self.brain.cancel()
            return "Stopped."

    def _subtitle(self) -> str:
        """Small footer showing how the last turn was routed."""
        intent = getattr(self.brain, "last_intent", None)
        if intent is None:
            return ""
        return f"[dim]{intent.module} · {intent.method} · {datetime.now():%H:%M:%S}[/dim]"


__all__ = ["CLI"]
