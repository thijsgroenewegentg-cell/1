#!/usr/bin/env python3
# /main.py
"""JARVIS — a fully local, completely free personal AI assistant.

Entry point. Boots the brain, then runs one of three modes:

* ``--voice``  always-on wake-word listening (default when audio is available)
* ``--cli``    rich text interface
* ``--say``    one-shot: answer a single request and exit

Usage::

    python main.py                 # auto: voice if possible, else CLI
    python main.py --cli           # force text mode
    python main.py --voice         # force voice mode
    python main.py --say "what's the weather"
    python main.py --test          # component self-test
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
from pathlib import Path
from typing import Any, Optional

# Make sure the project root is importable no matter where we're launched from.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.brain import Brain  # noqa: E402
from core.config import Config  # noqa: E402
from interfaces.cli import CLI  # noqa: E402
from utils.helpers import detect_os  # noqa: E402
from utils.logger import get_logger, setup_logging  # noqa: E402

logger = get_logger("main")


class Jarvis:
    """Application container wiring brain, voice and CLI together."""

    def __init__(self, config_path: str = "config.yaml") -> None:
        """Load the configuration and construct the assistant.

        Args:
            config_path: Path to ``config.yaml`` (created with defaults if absent).
        """
        self.config = Config.load(PROJECT_ROOT / config_path)
        setup_logging(self.config.section("logging"))
        self.brain = Brain(self.config)
        self.voice: Optional[Any] = None
        self.cli: Optional[CLI] = None
        self.web: Optional[Any] = None
        self._shutting_down = False

    # ------------------------------------------------------------------ setup
    async def initialize(self, want_voice: bool = True) -> None:
        """Boot every subsystem.

        Args:
            want_voice: Attempt to initialise the audio pipeline.
        """
        logger.info("Booting JARVIS on %s…", detect_os())
        await self.brain.initialize()

        if want_voice and self.config.get("voice.enabled", True):
            try:
                from interfaces.voice import VoiceInterface

                self.voice = VoiceInterface(self.config)
                await self.voice.initialize()
            except Exception as exc:
                logger.warning("Voice pipeline unavailable: %s", exc)
                self.voice = None

        # Share the loaded voice pipeline with the brain so the web interface can
        # reuse the same Whisper model instead of loading a second copy.
        self.brain.voice = self.voice  # type: ignore[attr-defined]
        self.cli = CLI(self.brain, voice=self.voice)

        # Dangerous actions ask for confirmation through the CLI.
        self.brain.security.set_confirm_hook(self.cli.confirm)

        # Timers and reminders announce themselves through voice + terminal.
        productivity = self.brain.modules.get("productivity")
        if productivity is not None and hasattr(productivity, "set_notifier"):
            productivity.set_notifier(self._notify)

        # Long-running tasks can speak progress updates.
        self.brain.speaker_hook = self._status_update

    async def _notify(self, message: str) -> None:
        """Announce a reminder, timer or scheduled job in every active channel."""
        if self.cli is not None:
            self.cli.notify(message)
        if self.web is not None:
            with contextlib.suppress(Exception):
                await self.web.broadcast(message)
        if self.voice is not None and self.voice.available:
            with contextlib.suppress(Exception):
                await self.voice.speak(message)

    async def _status_update(self, message: str) -> None:
        """Speak a short progress update during slow operations."""
        if self.voice is not None and self.voice.available and self.voice.tts.available:
            with contextlib.suppress(Exception):
                await self.voice.speak(message, interruptible=False)
        elif self.cli is not None:
            self.cli.info(message)

    # ------------------------------------------------------------------ modes
    async def run_voice(self) -> None:
        """Always-on voice loop with a CLI fallback if audio fails."""
        if self.voice is None or not self.voice.available:
            logger.warning("Audio unavailable — starting the text interface instead.")
            await self.run_cli()
            return

        assert self.cli is not None
        self.cli.banner()
        report = await self.voice.self_test()
        self.cli.info(
            f"Voice pipeline — mic: {report['microphone']}, whisper: {report['stt_model']}, "
            f"tts: {report['tts_voice']}, wake: {report['wake_engine']}"
        )

        greeting = await self.brain.greeting()
        self.cli.assistant_panel(greeting)
        await self.voice.speak(greeting)

        wake_word = self.config.get("voice.wake_word", "jarvis")
        self.cli.info(f"Listening. Say '{wake_word}' to wake me. Ctrl+C to exit.")

        async def on_wake() -> None:
            """Show a listening indicator when the wake word fires."""
            assert self.cli is not None
            self.cli.print("[bold cyan]● listening…[/bold cyan]")

        async def on_transcript(text: str) -> None:
            """Echo what was heard into the terminal."""
            assert self.cli is not None
            self.cli.print(f"[green]{self.config.get('user.name', 'You')}[/green] › {text}")

        self.voice.interrupt_hook = self.brain.cancel

        async def handler(text: str, on_token: Any = None) -> str:
            """Route a transcript through the brain and display the reply."""
            reply = await self.brain.process(text, speak_status=True, on_token=on_token)
            assert self.cli is not None
            self.cli.assistant_panel(reply)
            return reply

        await self.voice.run(handler, on_wake=on_wake, on_transcript=on_transcript)

    async def run_cli(self) -> None:
        """Run the rich text interface."""
        assert self.cli is not None
        await self.cli.run()

    async def run_web(self, port: Optional[int] = None, with_cli: bool = False) -> None:
        """Serve the browser/phone interface.

        Args:
            port: Override the configured port.
            with_cli: Also run the terminal REPL in the same process.
        """
        from interfaces.web import WebInterface, local_addresses

        server = WebInterface(self.brain, self.config, port=port)
        self.web = server
        assert self.cli is not None
        self.cli.banner()
        for address in local_addresses(server.port):
            suffix = f"?token={server.token}" if server.token else ""
            self.cli.success(f"Web interface: {address}{suffix}")
        if not server.token:
            self.cli.warn(
                "No web_ui.token set — anyone on your network can talk to JARVIS."
            )
        self.cli.info("Press Ctrl+C to stop the server.")

        serve_task = asyncio.create_task(server.serve())
        try:
            if with_cli:
                await self.cli.run()
                await server.stop()
            else:
                await serve_task
        finally:
            await server.stop()
            serve_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await serve_task

    async def run_once(self, text: str) -> str:
        """Answer a single request (for scripting and cron jobs)."""
        reply = await self.brain.process(text)
        print(reply)
        if self.voice is not None and self.voice.available:
            await self.voice.speak(reply)
        return reply

    async def self_test(self) -> bool:
        """Check every component and print a report.

        Returns:
            True when the core (LLM + memory) is healthy.
        """
        assert self.cli is not None
        self.cli.banner()
        self.cli.rule("Self test")

        report = await self.brain.status_report()
        llm = report["llm"]
        ok = bool(llm["online"])

        (self.cli.success if llm["online"] else self.cli.error)(
            "Ollama: " + (f"online — {llm['model']}" if llm["online"]
                          else f"offline at {llm['host']}")
        )
        if llm.get("last_error"):
            self.cli.warn(f"Last LLM problem: {llm['last_error']}")
        self.cli.success(
            f"Memory: {report['memory']['backend']} "
            f"({report['memory']['long_term']} long-term entries)"
        )
        self.cli.success(
            "Modules: " + ", ".join(f"{n} ({c} tools)" for n, c in report["modules"].items())
        )

        if self.voice is not None:
            voice_report = await self.voice.self_test()
            for component in ("microphone", "stt", "tts"):
                state = voice_report[component]
                (self.cli.success if state else self.cli.warn)(
                    f"{component}: {'ready' if state else 'unavailable'}"
                )
            self.cli.info(f"Wake-word engine: {voice_report['wake_engine']}")
            if voice_report["tts"]:
                await self.voice.speak("All systems nominal, sir.")
        else:
            self.cli.warn("Voice: disabled")

        self.cli.rule()
        probe = await self.brain.process("what time is it")
        self.cli.assistant_panel(probe, subtitle="[dim]end-to-end probe[/dim]")
        return ok

    # --------------------------------------------------------------- shutdown
    async def shutdown(self) -> None:
        """Persist state and release every resource."""
        if self._shutting_down:
            return
        self._shutting_down = True
        logger.info("Shutting down…")
        if self.web is not None:
            with contextlib.suppress(Exception):
                await self.web.stop()
        if self.voice is not None:
            with contextlib.suppress(Exception):
                await self.voice.shutdown()
        with contextlib.suppress(Exception):
            await self.brain.shutdown()


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="JARVIS — a 100% free, fully local personal AI assistant.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--voice", action="store_true", help="force voice mode")
    mode.add_argument("--cli", "--text", dest="cli", action="store_true", help="force text mode")
    mode.add_argument("--say", metavar="TEXT", help="answer one request and exit")
    mode.add_argument("--test", action="store_true", help="run a component self-test")
    mode.add_argument(
        "--web", action="store_true", help="serve the phone/browser interface"
    )
    mode.add_argument(
        "--backup", nargs="?", const="", metavar="PATH",
        help="write a zip of everything JARVIS knows and exit",
    )
    mode.add_argument(
        "--restore", metavar="ARCHIVE.ZIP", help="restore a backup and exit"
    )
    mode.add_argument(
        "--uninstall", action="store_true",
        help="remove JARVIS's data, venv and login service (asks first)",
    )
    parser.add_argument(
        "--port", type=int, default=None, help="port for --web (default web_ui.port)"
    )
    parser.add_argument(
        "--with-cli", action="store_true", help="run the terminal REPL alongside --web"
    )
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--no-voice", action="store_true", help="skip audio initialisation")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    parser.add_argument(
        "--force", action="store_true",
        help="with --restore, overwrite existing files; with --uninstall, skip the prompt",
    )
    parser.add_argument(
        "--keep-data", action="store_true",
        help="with --uninstall, keep the database, memory, notes and plugins",
    )
    return parser.parse_args(argv)


def run_maintenance(args: argparse.Namespace) -> Optional[int]:
    """Handle --backup / --restore / --uninstall without starting JARVIS.

    These have to work when Ollama is missing, the venv is half broken or the
    database is corrupt, so they deliberately avoid touching the brain.

    Args:
        args: Parsed command-line arguments.

    Returns:
        An exit code when a maintenance command ran, otherwise ``None``.
    """
    from utils.backup import (
        create_backup,
        inspect_backup,
        restore_backup,
        uninstall,
        uninstall_plan,
    )
    from utils.helpers import human_bytes

    root = Path(__file__).resolve().parent

    if args.backup is not None:
        destination = Path(args.backup).expanduser() if args.backup else None
        try:
            summary = create_backup(root, destination)
        except Exception as exc:
            print(f"Backup failed: {exc}")
            return 1
        print(f"Backed up {summary['files']} file(s), {human_bytes(summary['bytes'])} "
              f"of data → {summary['path']} "
              f"({human_bytes(summary['archive_bytes'])} compressed)")
        print("Restore it with:  python main.py --restore "
              f"{summary['path']} --force")
        return 0

    if args.restore:
        archive = Path(args.restore).expanduser()
        if not archive.is_file():
            print(f"No such backup: {archive}")
            return 1
        manifest = inspect_backup(archive)
        if not manifest.get("ok"):
            print(f"That is not a JARVIS backup: {manifest.get('error')}")
            return 1
        preview = restore_backup(root, archive, overwrite=args.force, dry_run=True)
        print(f"Backup from {manifest.get('created', 'an unknown date')} — "
              f"{len(manifest.get('files', []))} file(s).")
        if preview.get("rejected"):
            print(f"Ignoring {len(preview['rejected'])} unsafe path(s) in the archive.")
        if preview.get("clashes") and not args.force:
            print(f"{len(preview['clashes'])} file(s) already exist and will be kept. "
                  "Re-run with --force to overwrite them (a safety copy is taken first).")
        summary = restore_backup(root, archive, overwrite=args.force)
        if not summary.get("ok"):
            print(f"Restore failed: {summary.get('error')}")
            return 1
        print(f"Restored {summary['restored']} file(s); {summary['skipped']} left alone.")
        if summary.get("safety"):
            print(f"What was overwritten is saved in {summary['safety']}")
        return 0

    if args.uninstall:
        plan = uninstall_plan(root, keep_data=args.keep_data)
        if not plan:
            print("Nothing to remove — this installation is already clean.")
            return 0
        total = sum(entry["bytes"] for entry in plan)
        print("Uninstalling will delete:")
        for entry in plan:
            print(f"  {human_bytes(entry['bytes']):>10}  {entry['path']}  "
                  f"({entry['label']})")
        print(f"  {human_bytes(total):>10}  in total")
        print("\nThe source code, Ollama and your models are left alone.")
        if not args.keep_data:
            print("Tip: run 'python main.py --backup' first, or use --keep-data.")
        if not args.force:
            try:
                answer = input("\nType 'yes' to go ahead: ").strip().lower()
            except Exception:
                answer = ""
            if answer != "yes":
                print("Cancelled — nothing was removed.")
                return 0
        summary = uninstall(root, keep_data=args.keep_data)
        print(f"Removed {len(summary['removed'])} item(s), "
              f"{human_bytes(summary['bytes'])} freed.")
        for failure in summary["failed"]:
            print(f"  could not remove {failure}")
        return 1 if summary["failed"] else 0

    return None


async def async_main(args: argparse.Namespace) -> int:
    """Async entry point.

    Returns:
        A process exit code.
    """
    jarvis = Jarvis(args.config)
    if args.debug:
        jarvis.config.set("logging.level", "DEBUG")
        setup_logging(jarvis.config.section("logging"))

    want_voice = (
        not args.no_voice
        and not args.cli
        and not args.web
        and jarvis.config.get("voice.enabled", True)
    )
    await jarvis.initialize(want_voice=want_voice)

    # Ctrl+C / SIGTERM shut down cleanly on POSIX.
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is None:
            continue
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signal_value, stop_event.set)

    async def watch_stop() -> None:
        """Trigger shutdown when a termination signal arrives."""
        await stop_event.wait()
        if jarvis.voice is not None:
            jarvis.voice.stop()
        if jarvis.cli is not None:
            jarvis.cli.running = False

    watcher = asyncio.create_task(watch_stop())

    exit_code = 0
    try:
        if args.test:
            exit_code = 0 if await jarvis.self_test() else 1
        elif args.say:
            await jarvis.run_once(args.say)
        elif args.web:
            await jarvis.run_web(port=args.port, with_cli=args.with_cli)
        elif args.cli:
            await jarvis.run_cli()
        elif args.voice or (jarvis.voice is not None and jarvis.voice.available):
            await jarvis.run_voice()
        else:
            await jarvis.run_cli()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.exception("Fatal error")
        print(f"\nJARVIS hit a fatal error: {exc}")
        exit_code = 1
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await watcher
        await jarvis.shutdown()
    return exit_code


def main() -> None:
    """Synchronous wrapper used by the console entry point."""
    args = parse_args()
    maintenance = run_maintenance(args)
    if maintenance is not None:
        raise SystemExit(maintenance)
    try:
        raise SystemExit(asyncio.run(async_main(args)))
    except KeyboardInterrupt:
        print("\nInterrupted. Goodbye, sir.")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
