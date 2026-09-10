# /modules/vision.py
"""Local computer vision through Ollama's multimodal models (llava & friends).

Screenshots and image files are base64-encoded and sent to a locally running
vision model — no cloud service, no API key. Screen capture uses whatever the
platform already provides (macOS ``screencapture``, Linux ``gnome-screenshot`` /
``spectacle`` / ``scrot`` / ``grim``, Windows PowerShell + .NET), with an
optional Pillow fallback.
"""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.helpers import (
    ensure_dir,
    has_display,
    human_bytes,
    resolve_user_path,
    run_blocking,
    truncate,
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


class Vision(BaseModule):
    """Let JARVIS look at your screen, your webcam frames and your images."""

    name = "vision"
    description = (
        "Visual understanding: describe what is on the user's screen, watch the screen "
        "for changes, read text out of screenshots, and answer questions about image "
        "files. Requires a local vision model such as llava. A webcam is optional and "
        "never required."
    )
    intent_examples: ClassVar[List[str]] = [
        "what's on my screen",
        "watch my screen",
        "describe this image ~/Pictures/chart.png",
        "read the error message on my screen",
        "what does this diagram show",
    ]

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Read vision settings and prepare the screenshot directory."""
        super().__init__(config, llm=llm, security=security)
        section = config.section("vision")
        self.model: str = str(section.get("model", "llava"))
        #: Tried in order when the configured model is not installed. These
        #: were advertised in config.yaml and read by nobody, so a missing
        #: llava produced a flat refusal instead of trying bakllava.
        self.fallback_models: List[str] = [
            str(name) for name in section.get("fallback_models", []) or []
        ]
        self.max_tokens: int = int(section.get("max_tokens", 400))
        self.temperature: float = float(section.get("temperature", 0.2))
        self.max_pixels: int = int(section.get("max_pixels", 1_600_000))
        self.screenshot_dir: Path = config.resolve(
            # "or", not a .get default: the key exists and is blank by
            # design, and a blank path resolves to the project root.
            section.get("screenshot_dir")
            or config.get("paths.screenshots", "data/screenshots")
        )
        self.keep_screenshots: int = int(section.get("keep_screenshots", 10))
        self.timeout: float = float(section.get("timeout", 180))
        self.watch_interval: int = max(15, min(600, int(section.get("watch_interval", 60) or 60)))
        ensure_dir(self.screenshot_dir)

    # ---------------------------------------------------------- offline route
    def offline_router(self, command: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """Rule-based routing used when no LLM is available."""
        text = strip_command_prefix(command)
        lowered = text.lower()
        if "status" in lowered or "can you see" in lowered or "is llava" in lowered:
            return "vision_status", {}
        if "compare" in lowered:
            paths = [token for token in text.split()
                     if Path(token.strip("'\"`")).suffix.lower() in IMAGE_SUFFIXES]
            if len(paths) >= 2:
                return "compare_images", {"first": paths[0], "second": paths[1]}
        path = self._extract_path(text)
        if path:
            return "describe_image", {"path": str(path), "question": text}
        named = self._mentioned_image(text)
        if named:
            # Describing the screen instead would quietly answer a different
            # question from the one that was asked.
            return "describe_image", {"path": named, "question": text}
        if "read" in lowered and "screen" in lowered:
            return "read_screen", {}
        if "screenshot" in lowered and ("take" in lowered or "capture" in lowered):
            return "take_screenshot", {}
        if any(word in lowered for word in ("webcam", "web cam", "camera")):
            return "look_at_camera", {"question": text}
        screenish = any(word in lowered for word in ("screen", "scherm"))
        if screenish and any(
            phrase in lowered for phrase in (
                "stop watching", "stop looking", "niet meer kijken",
            )
        ):
            return "stop_watching_screen", {}
        if screenish and any(
            phrase in lowered for phrase in (
                "watch", "keep an eye", "in de gaten", "blijf kijken",
            )
        ) and "news" not in lowered:
            return "watch_screen", {"question": text}
        return "describe_screen", {"question": text}

    @staticmethod
    def _mentioned_image(text: str) -> str:
        """Return an image filename the user named, even if it does not exist.

        Args:
            text: The user's utterance.

        Returns:
            The first image-looking token, or an empty string.
        """
        for token in text.replace(",", " ").split():
            cleaned = token.strip("'\"`()<>")
            if cleaned and Path(cleaned).suffix.lower() in IMAGE_SUFFIXES:
                return cleaned
        return ""

    @staticmethod
    def _extract_path(text: str) -> Optional[Path]:
        """Pull an existing image path out of free text, if present."""
        for token in text.replace(",", " ").split():
            cleaned = token.strip("'\"`()<>")
            if not cleaned or Path(cleaned).suffix.lower() not in IMAGE_SUFFIXES:
                continue
            candidate = resolve_user_path(cleaned)
            if candidate.exists():
                return candidate
        return None

    # ------------------------------------------------------------- capturing
    def _capture(self, destination: Path) -> str:
        """Capture the screen to ``destination``; returns the method used.

        Raises:
            RuntimeError: If no capture mechanism is available.
        """
        ensure_dir(destination.parent)
        system = platform.system()

        if system == "Darwin":
            subprocess.run(
                ["screencapture", "-x", str(destination)], check=True, timeout=30
            )
            return "screencapture"

        if system == "Windows":
            script = (
                "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen; "
                "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; "
                "$g=[System.Drawing.Graphics]::FromImage($bmp); "
                "$g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size); "
                f"$bmp.Save('{destination}');"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script], check=True, timeout=60
            )
            return "powershell"

        candidates = [
            (["gnome-screenshot", "-f", str(destination)], "gnome-screenshot"),
            (["spectacle", "-b", "-n", "-o", str(destination)], "spectacle"),
            (["scrot", "-o", str(destination)], "scrot"),
            (["import", "-window", "root", str(destination)], "imagemagick"),
            (["grim", str(destination)], "grim"),
            (["maim", str(destination)], "maim"),
        ]
        for command, label in candidates:
            if shutil.which(command[0]):
                try:
                    subprocess.run(command, check=True, timeout=30,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if destination.exists() and destination.stat().st_size > 0:
                        return label
                except Exception:
                    continue

        try:  # last resort: Pillow's ImageGrab (X11/macOS/Windows)
            from PIL import ImageGrab  # type: ignore

            ImageGrab.grab().save(destination)
            return "pillow"
        except Exception as exc:
            raise RuntimeError(
                "No screenshot tool found. Install one of: gnome-screenshot, spectacle, "
                "scrot, maim, grim (Linux) — macOS and Windows work out of the box."
            ) from exc

    def _shrink(self, path: Path) -> Path:
        """Downscale a large image so the model isn't fed a 4K wall of pixels."""
        try:
            from PIL import Image  # type: ignore
        except Exception:
            return path
        try:
            with Image.open(path) as image:
                width, height = image.size
                if width * height <= self.max_pixels:
                    return path
                ratio = (self.max_pixels / float(width * height)) ** 0.5
                resized = image.convert("RGB").resize(
                    (max(1, int(width * ratio)), max(1, int(height * ratio)))
                )
                target = path.with_name(f"{path.stem}_small.jpg")
                resized.save(target, quality=85)
                return target
        except Exception as exc:
            self.log.debug("Image downscale failed: %s", exc)
            return path

    def _prune(self) -> None:
        """Keep only the newest ``keep_screenshots`` captures."""
        try:
            shots = sorted(
                self.screenshot_dir.glob("screen_*.png"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for stale in shots[self.keep_screenshots:]:
                stale.unlink(missing_ok=True)
                stale.with_name(f"{stale.stem}_small.jpg").unlink(missing_ok=True)
        except Exception:
            pass

    # ------------------------------------------------------------- inference
    async def _ensure_model(self) -> Optional[str]:
        """Check a vision model is usable, falling back where configured.

        Returns:
            An error message when nothing usable is installed, else ``None``.
            When the configured model is missing but a listed fallback is
            present, the fallback is adopted for the rest of the session.
        """
        if self.llm is None or not getattr(self.llm, "available", False):
            return (
                "Ollama isn't responding, sir. Start it with 'ollama serve' before asking "
                "me to look at anything."
            )
        try:
            if await self.llm.has_model(self.model):
                return None
            for candidate in self.fallback_models:
                if candidate != self.model and await self.llm.has_model(candidate):
                    self.log.info(
                        "Vision model '%s' is missing; using '%s' instead.",
                        self.model, candidate,
                    )
                    self.model = candidate
                    return None
            listed = ", ".join([self.model, *self.fallback_models][:4])
            return (
                f"I have no eyes yet — none of these are installed: {listed}. "
                f"Run: ollama pull {self.model}"
            )
        except Exception:
            return None

    async def _ask_model(self, image_path: Path, prompt: str) -> str:
        """Send an image plus prompt to the local vision model."""
        prepared = await run_blocking(self._shrink, image_path)
        data = await run_blocking(prepared.read_bytes)
        encoded = base64.b64encode(data).decode("ascii")
        return await self.llm.vision(
            prompt=prompt, images=[encoded], model=self.model, timeout=self.timeout,
            temperature=self.temperature, max_tokens=self.max_tokens,
        )

    # ----------------------------------------------------------------- tools
    @tool(
        description="Take a screenshot and save it to disk.",
        params={
            "path": {"type": "string", "description": "Where to save (optional)",
                     "default": ""}
        },
        keywords=["take a screenshot", "capture my screen", "screen grab"],
    )
    async def take_screenshot(self, path: str = "") -> ModuleResult:
        """Capture the whole screen to a PNG file."""
        destination = (
            resolve_user_path(path)
            if path
            else self.screenshot_dir / f"screen_{time.strftime('%Y%m%d_%H%M%S')}.png"
        )
        try:
            method = await run_blocking(self._capture, destination)
        except Exception as exc:
            return ModuleResult.fail(str(exc))
        await run_blocking(self._prune)
        size = human_bytes(destination.stat().st_size)
        return ModuleResult(
            success=True,
            output=f"Screenshot saved to {destination} ({size}, via {method}).",
            speak="Screenshot captured.",
            data={"path": str(destination), "method": method},
        ).offering(
            "vision.describe_image",
            {"path": str(destination), "question": "Describe this screenshot."},
            "Shall I describe it?",
        )

    @tool(
        description="Look at the user's screen and describe or answer a question about it.",
        params={
            "question": {
                "type": "string",
                "description": "What to look for on screen",
                "default": "Describe what is on this screen.",
            }
        },
        untrusted=True,
        keywords=["what's on my screen", "whats on my screen", "look at my screen",
                  "see my screen", "what do you see", "check my screen"],
        examples=['describe_screen(question="what error is showing?")'],
    )
    async def describe_screen(
        self, question: str = "Describe what is on this screen."
    ) -> ModuleResult:
        """Capture the screen and hand it to the local vision model."""
        problem = await self._ensure_model()
        if problem:
            return ModuleResult.fail(problem)

        destination = self.screenshot_dir / f"screen_{time.strftime('%Y%m%d_%H%M%S')}.png"
        try:
            await run_blocking(self._capture, destination)
        except Exception as exc:
            return ModuleResult.fail(str(exc))

        prompt = (question or "").strip() or "Describe what is on this screen."
        try:
            answer = await self._ask_model(
                destination,
                f"You are looking at a screenshot of the user's computer. {prompt} "
                "Be specific about visible applications, text and errors. Be concise.",
            )
        except Exception as exc:
            return ModuleResult.fail(f"The vision model refused to cooperate: {exc}")
        finally:
            await run_blocking(self._prune)

        answer = answer.strip() or "The model returned nothing intelligible, sir."
        return ModuleResult(
            success=True,
            output=answer,
            speak=truncate(answer, 400),
            data={"screenshot": str(destination), "model": self.model},
        )

    @tool(
        description="Read and transcribe the text visible on screen.",
        params={},
        untrusted=True,
        keywords=["read my screen", "read the text on screen", "what does the screen say",
                  "transcribe my screen"],
    )
    async def read_screen(self) -> ModuleResult:
        """OCR-style transcription of on-screen text via the vision model."""
        return await self.describe_screen(
            question=(
                "Transcribe all readable text on this screen, preserving structure. "
                "Output only the text."
            )
        )

    @tool(
        description="Describe or answer questions about an image file.",
        params={
            "path": {"type": "string", "description": "Path to the image", "required": True},
            "question": {
                "type": "string",
                "description": "Question about the image",
                "default": "Describe this image in detail.",
            },
        },
        untrusted=True,
        keywords=["describe this image", "what is in this picture", "look at this photo",
                  "analyze the image", "analyse this picture"],
        examples=['describe_image(path="~/Pictures/chart.png", question="what is the trend?")'],
    )
    async def describe_image(
        self, path: str, question: str = "Describe this image in detail."
    ) -> ModuleResult:
        """Answer a question about a local image file."""
        target = resolve_user_path(path)
        if not target.exists():
            return ModuleResult.fail(f"There's no image at {target}, sir.")
        if target.suffix.lower() not in IMAGE_SUFFIXES:
            return ModuleResult.fail(
                f"{target.name} isn't an image I can read "
                f"(supported: {', '.join(sorted(IMAGE_SUFFIXES))})."
            )
        problem = await self._ensure_model()
        if problem:
            return ModuleResult.fail(problem)

        try:
            answer = await self._ask_model(target, (question or "").strip() or
                                           "Describe this image in detail.")
        except Exception as exc:
            return ModuleResult.fail(f"The vision model refused to cooperate: {exc}")

        answer = answer.strip() or "The model had no comment."
        return ModuleResult(
            success=True,
            output=answer,
            speak=truncate(answer, 400),
            data={"path": str(target), "model": self.model},
        )

    @tool(
        description="Compare two images and explain the differences.",
        params={
            "first": {"type": "string", "description": "First image path", "required": True},
            "second": {"type": "string", "description": "Second image path", "required": True},
        },
        keywords=["compare these images", "difference between the images",
                  "what changed in the screenshot"],
    )
    async def compare_images(self, first: str, second: str) -> ModuleResult:
        """Ask the vision model what differs between two images."""
        left, right = resolve_user_path(first), resolve_user_path(second)
        for candidate in (left, right):
            if not candidate.exists():
                return ModuleResult.fail(f"Missing image: {candidate}")
        problem = await self._ensure_model()
        if problem:
            return ModuleResult.fail(problem)

        try:
            encoded: List[str] = []
            for candidate in (left, right):
                prepared = await run_blocking(self._shrink, candidate)
                raw = await run_blocking(prepared.read_bytes)
                encoded.append(base64.b64encode(raw).decode("ascii"))
            answer = await self.llm.vision(
                prompt="These are two images. Describe the meaningful differences "
                "between the first and the second. Be concise and concrete.",
                images=encoded,
                model=self.model,
                timeout=self.timeout,
            )
        except Exception as exc:
            return ModuleResult.fail(f"Comparison failed: {exc}")

        answer = answer.strip() or "The model saw no notable differences."
        return ModuleResult(success=True, output=answer, speak=truncate(answer, 400))

    @tool(
        description="Report whether screen capture and the vision model are available.",
        params={},
        keywords=["can you see", "vision status", "is llava installed"],
    )
    async def vision_status(self) -> ModuleResult:
        """Diagnose the capture backend and model availability."""
        system = platform.system()
        tools = [name for name in
                 ("screencapture", "gnome-screenshot", "spectacle", "scrot", "maim", "grim",
                  "import")
                 if shutil.which(name)]
        pillow = False
        try:
            import importlib.util

            pillow = importlib.util.find_spec("PIL") is not None
        except Exception:
            pillow = False

        model_ready = False
        if self.llm is not None and getattr(self.llm, "available", False):
            try:
                model_ready = await self.llm.has_model(self.model)
            except Exception:
                model_ready = False

        lines = [
            f"Platform: {system} ({sys.platform})",
            f"Capture tools: {', '.join(tools) if tools else 'none found'}"
            + (" · Pillow available" if pillow else ""),
            f"Vision model '{self.model}': " + ("ready" if model_ready else
                                                f"not installed (ollama pull {self.model})"),
            f"Screenshots kept in {self.screenshot_dir} (last {self.keep_screenshots}).",
        ]
        return ModuleResult(
            success=True,
            output="\n".join(lines),
            data={"tools": tools, "pillow": pillow, "model_ready": model_ready,
                  "camera": self._camera_present(), "watching": self._load_watch().get("active")},
        )

    # ---------------------------------------------------------- screen watch
    def _watch_path(self) -> Path:
        """JSON file for the optional screen-watch loop."""
        try:
            return self.config.resolve("data/screen_watch.json")
        except Exception:
            return Path("data/screen_watch.json")

    def _load_watch(self) -> Dict[str, Any]:
        """Read watch state, or an inactive document."""
        path = self._watch_path()
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {"active": False}

    def _save_watch(self, state: Dict[str, Any]) -> None:
        """Persist watch state. Never raises."""
        try:
            path = self._watch_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self.log.debug("Could not write screen watch: %s", exc)

    @staticmethod
    def _camera_present() -> bool:
        """True when a capture device looks plugged in. Never opens it."""
        if Path("/dev/video0").exists() or Path("/dev/video1").exists():
            return True
        return bool(shutil.which("imagesnap"))

    @tool(
        description="Watch the desktop for changes. No webcam required.",
        params={
            "question": {
                "type": "string",
                "description": "What to look for (optional)",
                "default": "",
            },
            "interval": {
                "type": "integer",
                "description": "Seconds between glances (0 = config default)",
                "default": 0,
            },
        },
        keywords=["watch my screen", "keep an eye on the screen", "watch the desktop",
                  "houd mijn scherm in de gaten"],
        examples=['watch_screen(question="tell me if an error pops up")'],
    )
    async def watch_screen(self, question: str = "", interval: int = 0) -> ModuleResult:
        """Start glancing at the screen on a timer. Capture happens on later ticks."""
        seconds = int(interval or 0) or self.watch_interval
        seconds = max(15, min(600, seconds))
        prompt = (question or "").strip()
        state = {
            "active": True,
            "question": prompt,
            "interval": seconds,
            "last_hash": "",
            "last_at": 0.0,
            "started": time.time(),
        }
        self._save_watch(state)
        extra = f" I'll look for: {prompt}." if prompt else ""
        return ModuleResult(
            success=True,
            output=(
                f"Watching the screen every {seconds}s.{extra} "
                "No camera needed — say 'stop watching the screen' to cancel."
            ),
            speak="Watching the screen.",
            data={"interval": seconds, "active": True},
        )

    @tool(
        description="Stop the screen-watch loop.",
        params={},
        keywords=["stop watching the screen", "stop looking at my screen"],
    )
    async def stop_watching_screen(self) -> ModuleResult:
        """Cancel an active screen watch."""
        state = self._load_watch()
        if not state.get("active"):
            return ModuleResult.ok("I wasn't watching the screen.")
        state["active"] = False
        self._save_watch(state)
        return ModuleResult.ok("Stopped watching the screen.")

    @tool(
        description="Grab a webcam frame if a camera exists; otherwise explain how to use the screen.",
        params={
            "question": {
                "type": "string",
                "description": "What to look for",
                "default": "Describe what the camera sees.",
            }
        },
        keywords=["webcam", "look at the camera", "take a photo of me"],
    )
    async def look_at_camera(self, question: str = "") -> ModuleResult:
        """Optional camera. This machine may have none — that is not an error in setup."""
        if not self._camera_present():
            return ModuleResult.fail(
                "No camera on this machine. I can still watch the screen — "
                "say 'watch my screen' or 'what's on my screen'."
            )
        destination = self.screenshot_dir / f"cam_{time.strftime('%Y%m%d_%H%M%S')}.png"
        ensure_dir(destination.parent)
        grabbed = False
        try:
            if shutil.which("ffmpeg") and Path("/dev/video0").exists():
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "v4l2", "-i", "/dev/video0",
                     "-frames:v", "1", str(destination)],
                    check=True, timeout=12,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                grabbed = destination.exists() and destination.stat().st_size > 0
            elif shutil.which("imagesnap"):
                subprocess.run(["imagesnap", "-w", "1", str(destination)],
                               check=True, timeout=12)
                grabbed = destination.exists()
        except Exception as exc:
            return ModuleResult.fail(f"Camera present but capture failed: {exc}")
        if not grabbed:
            return ModuleResult.fail(
                "A camera node is there but I could not grab a frame. "
                "I can watch the screen instead."
            )
        return await self.describe_image(
            str(destination),
            question=(question or "").strip() or "Describe what the camera sees.",
        )

    async def tick_screen_watch(self) -> Optional[str]:
        """One glance if a watch is active and the interval has elapsed.

        Returns a line to announce, or ``None``. Never raises. Headless
        sessions (no display) stay silent so CI is not noisy.
        """
        state = self._load_watch()
        if not state.get("active"):
            return None
        interval = max(15, int(state.get("interval") or self.watch_interval))
        last_at = float(state.get("last_at") or 0)
        if time.time() - last_at < interval:
            return None
        if not has_display():
            state["last_at"] = time.time()
            self._save_watch(state)
            return None
        destination = self.screenshot_dir / "screen_watch.png"
        try:
            await run_blocking(self._capture, destination)
        except Exception as exc:
            self.log.debug("Screen-watch capture failed: %s", exc)
            state["last_at"] = time.time()
            self._save_watch(state)
            return None
        try:
            digest = hashlib.md5(destination.read_bytes()).hexdigest()
        except Exception:
            return None
        previous = str(state.get("last_hash") or "")
        state["last_hash"] = digest
        state["last_at"] = time.time()
        self._save_watch(state)
        if not previous or previous == digest:
            return None
        prompt = str(state.get("question") or "").strip() or (
            "The desktop just changed. In one short sentence, what is different or new?"
        )
        try:
            problem = await self._ensure_model()
            if problem:
                return "The screen changed."
            answer = await self._ask_model(destination, prompt)
            line = (answer or "").strip()
            return truncate(line, 280) if line else "The screen changed."
        except Exception:
            return "The screen changed."


__all__ = ["Vision"]
