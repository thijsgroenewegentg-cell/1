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
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.helpers import ensure_dir, human_bytes, resolve_user_path, run_blocking, truncate

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


class Vision(BaseModule):
    """Let JARVIS look at your screen, your webcam frames and your images."""

    name = "vision"
    description = (
        "Visual understanding: describe what is on the user's screen, read text out of "
        "screenshots, and answer questions about image files. Requires a local vision "
        "model such as llava."
    )
    intent_examples = [
        "what's on my screen",
        "describe this image ~/Pictures/chart.png",
        "read the error message on my screen",
        "what does this diagram show",
    ]

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Read vision settings and prepare the screenshot directory."""
        super().__init__(config, llm=llm, security=security)
        section = config.section("vision")
        self.model: str = str(section.get("model", "llava"))
        self.max_pixels: int = int(section.get("max_pixels", 1_600_000))
        self.screenshot_dir: Path = config.resolve(
            section.get("screenshot_dir", "data/screenshots")
        )
        self.keep_screenshots: int = int(section.get("keep_screenshots", 10))
        self.timeout: float = float(section.get("timeout", 180))
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
        if "read" in lowered and "screen" in lowered:
            return "read_screen", {}
        if "screenshot" in lowered and ("take" in lowered or "capture" in lowered):
            return "take_screenshot", {}
        return "describe_screen", {"question": text}

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
        """Return an error message if the vision model isn't usable."""
        if self.llm is None or not getattr(self.llm, "available", False):
            return (
                "Ollama isn't responding, sir. Start it with 'ollama serve' before asking "
                "me to look at anything."
            )
        try:
            if not await self.llm.has_model(self.model):
                return (
                    f"I have no eyes yet — the '{self.model}' model isn't installed. "
                    f"Run: ollama pull {self.model}"
                )
        except Exception:
            return None
        return None

    async def _ask_model(self, image_path: Path, prompt: str) -> str:
        """Send an image plus prompt to the local vision model."""
        prepared = await run_blocking(self._shrink, image_path)
        data = await run_blocking(prepared.read_bytes)
        encoded = base64.b64encode(data).decode("ascii")
        return await self.llm.vision(
            prompt=prompt, images=[encoded], model=self.model, timeout=self.timeout
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
            data={"tools": tools, "pillow": pillow, "model_ready": model_ready},
        )


__all__ = ["Vision"]
