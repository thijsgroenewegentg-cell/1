# /interfaces/voice.py
"""Complete local voice pipeline for JARVIS.

* **Wake word** — Porcupine (free tier) when an access key is configured,
  otherwise a keyless Whisper-based detector so nothing ever costs money.
* **STT** — faster-whisper, running locally on CPU or GPU.
* **TTS** — edge-tts (Microsoft's free voices), played through whichever audio
  backend the machine has.
* **VAD** — energy-based endpointing with optional webrtcvad refinement.
* **Barge-in** — speaking stops the moment the user starts talking.

Every dependency is imported lazily, so JARVIS still starts (in text mode) on a
machine with no microphone or no audio libraries at all.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib.util
import inspect
import math
import shlex
import struct
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, List, Optional

from utils.helpers import (
    IS_MACOS,
    IS_WINDOWS,
    ensure_dir,
    run_blocking,
    strip_markdown,
    truncate,
    which,
)
from utils.logger import get_logger

logger = get_logger("interfaces.voice")

# A handler is any coroutine turning a transcript into a reply. Handlers that
# also accept an ``on_token`` keyword get their replies streamed into speech.
CommandHandler = Callable[..., Awaitable[str]]


# ---------------------------------------------------------------------------
# Text to speech
# ---------------------------------------------------------------------------


class TextToSpeech:
    """Free neural speech with interruptible playback.

    Two engines, both free:

    * **piper** — fully offline neural TTS. Nothing leaves the machine, so this
      is the default when a Piper voice model is present.
    * **edge-tts** — Microsoft's public neural voices. Better prosody, but it
      is a network call, which breaks the "everything is local" promise.

    ``voice.tts.engine`` picks between them: ``auto`` (Piper when available,
    otherwise edge-tts), ``piper``, or ``edge``.
    """

    def __init__(self, config: Any) -> None:
        """Args:
        config: The global configuration object.
        """
        self.config = config
        self.engine: str = str(config.get("voice.tts.engine", "auto")).lower().strip()
        self.piper_voice: str = str(config.get("voice.tts.piper_voice", "")).strip()
        self.piper_speed: float = float(config.get("voice.tts.piper_speed", 1.0) or 1.0)
        self.active_engine: str = ""
        self._piper_binary: Optional[str] = None
        self._piper_model: Optional[Path] = None
        self.voice: str = str(config.get("voice.tts.voice", "en-GB-RyanNeural"))
        self.rate: str = str(config.get("voice.tts.rate", "+8%"))
        self.volume: str = str(config.get("voice.tts.volume", "+0%"))
        self.pitch: str = str(config.get("voice.tts.pitch", "+0Hz"))
        self.cache_enabled: bool = bool(config.get("voice.tts.cache", True))
        self.cache_dir: Path = config.path_for("tts_cache")
        ensure_dir(self.cache_dir)
        self._process: Optional[subprocess.Popen] = None
        self._player: Optional[List[str]] = None
        self.available: bool = False
        self.speaking: bool = False

    # -- setup --------------------------------------------------------------
    async def initialize(self) -> bool:
        """Pick a speech engine and an audio player.

        Returns:
            True when JARVIS can speak.
        """
        engines: List[str] = []
        if self.engine in ("auto", "piper") and self._find_piper():
            engines.append("piper")
        if self.engine in ("auto", "edge") and importlib.util.find_spec("edge_tts"):
            engines.append("edge")

        if not engines:
            if self.engine == "piper":
                logger.warning(
                    "Piper is not installed — pip install piper-tts and download a voice "
                    "from https://huggingface.co/rhasspy/piper-voices (free)."
                )
            else:
                logger.warning("No speech engine available (edge-tts / piper) — "
                               "speech output disabled.")
            return False

        self._player = self._find_player()
        if self._player is None:
            logger.warning(
                "No audio player found. Install ffmpeg (ffplay) or mpv, "
                "or on Linux: sudo apt install ffmpeg"
            )
            return False

        self.active_engine = engines[0]
        self.available = True
        detail = (
            f"piper model={self._piper_model.name if self._piper_model else '?'}"
            if self.active_engine == "piper"
            else f"edge voice={self.voice}"
        )
        logger.info("TTS ready — engine=%s %s player=%s",
                    self.active_engine, detail, self._player[0])
        return True

    def _find_piper(self) -> bool:
        """Locate the Piper binary (or module) and a voice model.

        Piper voices are ``.onnx`` files paired with ``.onnx.json`` config.
        JARVIS looks at ``voice.tts.piper_voice`` first, then in
        ``data/piper``, ``~/.local/share/piper-voices`` and ``/usr/share/piper``.

        Returns:
            True when both a runner and a voice model were found.
        """
        runner: Optional[str] = which("piper")
        if runner is None and importlib.util.find_spec("piper") is not None:
            runner = f"{sys.executable} -m piper"
        if runner is None:
            return False

        candidates: List[Path] = []
        if self.piper_voice:
            explicit = Path(self.piper_voice).expanduser()
            if explicit.is_file():
                candidates.append(explicit)
            else:
                candidates.extend(
                    sorted(self.config.resolve("data/piper").glob(f"*{self.piper_voice}*.onnx"))
                )
        for folder in (
            self.config.resolve("data/piper"),
            Path.home() / ".local" / "share" / "piper-voices",
            Path("/usr/share/piper-voices"),
            Path("/usr/share/piper"),
        ):
            try:
                candidates.extend(sorted(folder.glob("**/*.onnx")))
            except Exception:
                continue

        for model in candidates:
            if model.is_file() and (model.with_suffix(".onnx.json").exists()
                                    or Path(f"{model}.json").exists()):
                self._piper_binary = runner
                self._piper_model = model
                return True
        return False

    #: Players that can only handle one container, keyed by file suffix.
    _FORMAT_ONLY = {"mpg123": {".mp3"}, "aplay": {".wav"}, "paplay": {".wav"}}

    def _player_for(self, path: Path) -> Optional[List[str]]:
        """Pick a player that can actually decode this file type.

        Args:
            path: The audio file about to be played.

        Returns:
            An argv prefix, or ``None`` when nothing suitable exists.
        """
        suffix = path.suffix.lower()
        if self._player is not None:
            supported = self._FORMAT_ONLY.get(self._player[0])
            if supported is None or suffix in supported:
                return self._player
        for candidate in self._all_players():
            supported = self._FORMAT_ONLY.get(candidate[0])
            if (supported is None or suffix in supported) and which(candidate[0]):
                return candidate
        return self._player

    @staticmethod
    def _all_players() -> List[List[str]]:
        """Every playback command JARVIS knows about, best first."""
        candidates: List[List[str]] = []
        if IS_MACOS:
            candidates.append(["afplay"])
        if IS_WINDOWS:
            candidates.append(["powershell", "-NoProfile", "-Command"])
        candidates += [
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
            ["mpv", "--no-video", "--really-quiet"],
            ["mpg123", "-q"],
            ["cvlc", "--play-and-exit", "--intf", "dummy"],
            ["paplay"],
            ["aplay", "-q"],
        ]
        return candidates

    @classmethod
    def _find_player(cls) -> Optional[List[str]]:
        """Locate a command-line audio player."""
        for candidate in cls._all_players():
            if which(candidate[0]):
                return candidate
        return None

    # -- synthesis ----------------------------------------------------------
    def _cache_path(self, text: str) -> Path:
        """Deterministic cache filename for a phrase."""
        model = self._piper_model.name if self._piper_model else ""
        digest = hashlib.sha1(
            f"{self.active_engine}|{model}|{self.voice}|{self.rate}|{self.pitch}|{text}"
            .encode("utf-8")
        ).hexdigest()[:20]
        suffix = "wav" if self.active_engine == "piper" else "mp3"
        return self.cache_dir / f"{digest}.{suffix}"

    async def synthesize(self, text: str) -> Optional[Path]:
        """Render ``text`` to an MP3 file and return its path."""
        clean = strip_markdown(text)[:3000]
        if not clean.strip():
            return None

        target = self._cache_path(clean)
        if self.cache_enabled and target.exists() and target.stat().st_size > 1024:
            return target

        if self.active_engine == "piper":
            return await self._synthesize_piper(clean, target)

        try:
            import edge_tts

            communicate = edge_tts.Communicate(
                clean, self.voice, rate=self.rate, volume=self.volume, pitch=self.pitch
            )
            temporary = target.with_suffix(".part")
            await communicate.save(str(temporary))
            temporary.replace(target)
            if not self.cache_enabled:
                self._prune_cache(keep=0)
            return target
        except Exception as exc:
            logger.warning("Speech synthesis failed: %s", truncate(str(exc), 160))
            return None

    async def _synthesize_piper(self, text: str, target: Path) -> Optional[Path]:
        """Render speech entirely offline with Piper.

        Args:
            text: Clean text to speak.
            target: Where to write the WAV file.

        Returns:
            The written path, or ``None`` on failure.
        """
        if not self._piper_binary or not self._piper_model:
            return None
        temporary = target.with_suffix(".part")
        command = shlex.split(self._piper_binary) + [
            "--model", str(self._piper_model),
            "--output_file", str(temporary),
        ]
        if self.piper_speed and abs(self.piper_speed - 1.0) > 0.01:
            command += ["--length_scale", f"{1.0 / self.piper_speed:.3f}"]

        def _run() -> bool:
            try:
                finished = subprocess.run(
                    command, input=text.encode("utf-8"),
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120,
                )
                if finished.returncode != 0:
                    logger.warning("Piper failed: %s",
                                   truncate(finished.stderr.decode("utf-8", "ignore"), 160))
                    return False
                return temporary.exists() and temporary.stat().st_size > 1024
            except Exception as exc:
                logger.warning("Piper failed: %s", truncate(str(exc), 160))
                return False

        if not await run_blocking(_run):
            with contextlib.suppress(Exception):
                temporary.unlink(missing_ok=True)
            return None
        temporary.replace(target)
        if not self.cache_enabled:
            self._prune_cache(keep=0)
        return target

    def _prune_cache(self, keep: int = 200) -> None:
        """Keep the TTS cache from growing without bound."""
        try:
            files = sorted(
                [path for pattern in ("*.mp3", "*.wav") for path in self.cache_dir.glob(pattern)],
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for stale in files[keep:]:
                stale.unlink(missing_ok=True)
        except Exception:
            pass

    # -- playback -----------------------------------------------------------
    async def speak(self, text: str, interruptible: bool = True) -> bool:
        """Speak ``text`` aloud.

        Args:
            text: What to say (markdown is stripped first).
            interruptible: Allow the user's voice to cut playback short.

        Returns:
            True when audio was played.
        """
        if not self.available:
            return False
        path = await self.synthesize(text)
        if path is None:
            return False
        return await self.play_file(path, interruptible=interruptible)

    async def play_file(self, path: Path, interruptible: bool = True) -> bool:
        """Play an audio file, optionally stopping on user speech."""
        if self._player is None:
            return False
        command = self._playback_command(path)
        if command is None:
            return False

        self.speaking = True
        try:
            self._process = await run_blocking(
                lambda: subprocess.Popen(
                    command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            )
        except Exception as exc:
            logger.debug("Playback failed to start: %s", exc)
            self.speaking = False
            return False

        try:
            while self._process.poll() is None:
                await asyncio.sleep(0.08)
        except asyncio.CancelledError:
            self.stop()
            raise
        finally:
            self.speaking = False
            self._process = None
        return True

    def _playback_command(self, path: Path) -> Optional[List[str]]:
        """Build the argv for a player that can handle this file."""
        player = self._player_for(path)
        if player is None:
            return None
        if player[0] == "powershell":
            script = (
                "Add-Type -AssemblyName presentationCore; "
                "$p=New-Object System.Windows.Media.MediaPlayer; "
                f"$p.Open([uri]'{path}'); $p.Play(); "
                "Start-Sleep -Milliseconds 300; "
                "while($p.NaturalDuration.HasTimeSpan -eq $false){Start-Sleep -Milliseconds 100}; "
                "Start-Sleep -Seconds $p.NaturalDuration.TimeSpan.TotalSeconds"
            )
            return [*player, script]
        return [*player, str(path)]

    def stop(self) -> None:
        """Immediately stop any speech in progress (barge-in)."""
        process = self._process
        if process is not None and process.poll() is None:
            with contextlib.suppress(Exception):
                process.terminate()
            with contextlib.suppress(Exception):
                process.wait(timeout=1)
            with contextlib.suppress(Exception):
                if process.poll() is None:
                    process.kill()
        self.speaking = False

    async def list_voices(self, language: str = "en") -> List[str]:
        """Return the free Edge voices available for a language."""
        try:
            import edge_tts

            voices = await edge_tts.list_voices()
            return sorted(
                voice["ShortName"]
                for voice in voices
                if voice.get("Locale", "").lower().startswith(language.lower())
            )
        except Exception as exc:
            logger.debug("Voice listing failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Microphone + VAD
# ---------------------------------------------------------------------------


class StreamingSpeaker:
    """Speaks a reply while it is still being generated.

    Tokens are fed in as they arrive; whenever a sentence boundary is reached
    the sentence is queued for synthesis, so the user hears the first sentence
    while the model is still writing the third. This removes most of the
    perceived latency of a local LLM.
    """

    BOUNDARIES = ".!?…\n"

    def __init__(self, tts: "TextToSpeech", min_chars: int = 45,
                 max_chars: int = 320) -> None:
        """Args:
        tts: The text-to-speech engine to play through.
        min_chars: Don't emit a chunk shorter than this (avoids choppy speech).
        max_chars: Force a break once a chunk grows past this.
        """
        self.tts = tts
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.buffer = ""
        self.spoken: List[str] = []
        self.cancelled = False
        self._queue: "asyncio.Queue[Optional[str]]" = asyncio.Queue()
        self._worker: Optional[asyncio.Task] = None
        self._in_code = False

    def start(self) -> None:
        """Begin consuming the sentence queue."""
        if self._worker is None:
            self.cancelled = False
            self._worker = asyncio.create_task(self._drain())

    async def _drain(self) -> None:
        """Play queued sentences strictly in order."""
        while True:
            chunk = await self._queue.get()
            if chunk is None:
                return
            if self.cancelled or not chunk.strip():
                continue
            try:
                await self.tts.speak(chunk, interruptible=True)
            except Exception as exc:  # noqa: BLE001 - speech must never crash a turn
                logger.debug("Streaming speech failed: %s", exc)

    def feed(self, token: str) -> None:
        """Add a generated token, emitting complete sentences as they form."""
        if self.cancelled:
            return
        self.buffer += token
        if "```" in token:
            self._in_code = not self._in_code
        if self._in_code:
            return
        while True:
            chunk = self._next_chunk()
            if chunk is None:
                return
            self.spoken.append(chunk)
            self._queue.put_nowait(chunk)

    def _next_chunk(self) -> Optional[str]:
        """Cut the longest speakable sentence out of the buffer, if any."""
        text = self.buffer
        if len(text) < self.min_chars:
            return None
        cut = -1
        for index, char in enumerate(text):
            if char in self.BOUNDARIES and index + 1 >= self.min_chars:
                following = text[index + 1: index + 2]
                if following in ("", " ", "\n", '"', "'", ")"):
                    cut = index + 1
                    break  # speak the first complete sentence, not the last
        if cut < 0:
            if len(text) < self.max_chars:
                return None
            space = text.rfind(" ", 0, self.max_chars)
            cut = space if space > self.min_chars else self.max_chars
        chunk = text[:cut].strip()
        self.buffer = text[cut:].lstrip()
        return chunk or None

    async def finish(self) -> None:
        """Flush the tail of the buffer and wait for playback to finish."""
        remainder = self.buffer.strip()
        self.buffer = ""
        if remainder and not self.cancelled:
            self.spoken.append(remainder)
            self._queue.put_nowait(remainder)
        self._queue.put_nowait(None)
        if self._worker is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._worker
            self._worker = None

    def cancel(self) -> None:
        """Abandon anything not yet spoken and silence playback."""
        self.cancelled = True
        self.buffer = ""
        while not self._queue.empty():
            with contextlib.suppress(Exception):
                self._queue.get_nowait()
        self._queue.put_nowait(None)
        self.tts.stop()

    @property
    def text(self) -> str:
        """Everything queued for speech so far."""
        return " ".join(self.spoken)


@dataclass
class AudioClip:
    """A mono PCM recording."""

    samples: Any  # numpy.ndarray (float32, -1..1)
    sample_rate: int

    @property
    def duration(self) -> float:
        """Length in seconds."""
        try:
            return float(len(self.samples)) / self.sample_rate
        except Exception:
            return 0.0

    def to_wav(self, path: Path) -> Path:
        """Write the clip to a 16-bit WAV file."""
        import numpy as np

        pcm = np.clip(self.samples, -1.0, 1.0)
        data = (pcm * 32767).astype("<i2").tobytes()
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(self.sample_rate)
            handle.writeframes(data)
        return path


class Microphone:
    """Microphone capture with energy-based voice activity detection."""

    def __init__(self, config: Any) -> None:
        """Read the ``voice.vad`` settings."""
        vad = config.section("voice").get("vad", {})
        self.sample_rate = int(vad.get("sample_rate", 16000))
        self.frame_ms = int(vad.get("frame_ms", 30))
        self.energy_threshold = float(vad.get("energy_threshold", 0.014))
        self.silence_ms = int(vad.get("silence_ms", 900))
        self.min_speech_ms = int(vad.get("min_speech_ms", 250))
        self.max_seconds = float(vad.get("max_command_seconds", 15))
        self.listen_timeout = float(vad.get("listen_timeout", 8))
        self.frame_size = int(self.sample_rate * self.frame_ms / 1000)
        self.available = False
        self._webrtc: Optional[Any] = None

    def initialize(self) -> bool:
        """Verify that an input device exists."""
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            has_input = any(device.get("max_input_channels", 0) > 0 for device in devices)
            if not has_input:
                logger.warning("No microphone detected — voice input disabled.")
                return False
            self.available = True
        except Exception as exc:
            logger.warning("Microphone unavailable (%s) — voice input disabled.", exc)
            return False

        try:
            import webrtcvad

            self._webrtc = webrtcvad.Vad(2)
            logger.debug("webrtcvad enabled.")
        except Exception:
            self._webrtc = None
        return True

    @staticmethod
    def rms(frame: Any) -> float:
        """Root-mean-square amplitude of a float32 frame."""
        try:
            import numpy as np

            if len(frame) == 0:
                return 0.0
            return float(np.sqrt(np.mean(np.square(frame, dtype="float64"))))
        except Exception:
            return 0.0

    def _is_speech(self, frame: Any) -> bool:
        """Classify a frame as speech using webrtcvad or raw energy."""
        energy = self.rms(frame)
        if energy < self.energy_threshold * 0.5:
            return False
        if self._webrtc is not None and self.frame_ms in (10, 20, 30):
            try:
                import numpy as np

                pcm = (np.clip(frame, -1, 1) * 32767).astype("<i2").tobytes()
                return bool(self._webrtc.is_speech(pcm, self.sample_rate))
            except Exception:
                pass
        return energy >= self.energy_threshold

    def record_until_silence(
        self, max_seconds: Optional[float] = None, timeout: Optional[float] = None
    ) -> Optional[AudioClip]:
        """Blocking capture of one utterance.

        Waits (up to ``timeout``) for speech to start, then records until
        ``silence_ms`` of quiet or ``max_seconds`` elapses.

        Returns:
            The recorded :class:`AudioClip`, or ``None`` if nothing was said.
        """
        if not self.available:
            return None
        try:
            import numpy as np
            import sounddevice as sd
        except Exception:
            return None

        max_seconds = float(max_seconds or self.max_seconds)
        timeout = float(timeout or self.listen_timeout)
        collected: List[Any] = []
        pre_roll: List[Any] = []
        speech_started = False
        silence_frames = 0
        speech_frames = 0
        needed_silence = max(1, int(self.silence_ms / self.frame_ms))
        needed_speech = max(1, int(self.min_speech_ms / self.frame_ms))
        started_at = time.time()

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.frame_size,
            ) as stream:
                while True:
                    frame, _ = stream.read(self.frame_size)
                    frame = frame.reshape(-1)
                    voiced = self._is_speech(frame)

                    if not speech_started:
                        pre_roll.append(frame)
                        if len(pre_roll) > 10:
                            pre_roll.pop(0)
                        if voiced:
                            speech_frames += 1
                            if speech_frames >= needed_speech:
                                speech_started = True
                                collected.extend(pre_roll)
                        else:
                            speech_frames = 0
                        if time.time() - started_at > timeout:
                            return None
                        continue

                    collected.append(frame)
                    silence_frames = 0 if voiced else silence_frames + 1
                    if silence_frames >= needed_silence:
                        break
                    if len(collected) * self.frame_ms / 1000 >= max_seconds:
                        break
        except Exception as exc:
            logger.debug("Recording failed: %s", exc)
            return None

        if not collected:
            return None
        return AudioClip(np.concatenate(collected), self.sample_rate)

    def record_seconds(self, seconds: float) -> Optional[AudioClip]:
        """Record a fixed-length clip (used by the Whisper wake-word engine)."""
        if not self.available:
            return None
        try:
            import numpy as np
            import sounddevice as sd

            frames = int(self.sample_rate * seconds)
            data = sd.rec(frames, samplerate=self.sample_rate, channels=1, dtype="float32")
            sd.wait()
            return AudioClip(np.asarray(data).reshape(-1), self.sample_rate)
        except Exception as exc:
            logger.debug("Fixed recording failed: %s", exc)
            return None

    def detect_voice(self, seconds: float = 0.25) -> bool:
        """Return True when speech is heard within a short window (barge-in)."""
        if not self.available:
            return False
        try:
            import sounddevice as sd

            frames = int(self.sample_rate * seconds)
            data = sd.rec(frames, samplerate=self.sample_rate, channels=1, dtype="float32")
            sd.wait()
            return self.rms(data.reshape(-1)) >= self.energy_threshold * 2.2
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Speech to text
# ---------------------------------------------------------------------------


class SpeechToText:
    """Local transcription with faster-whisper."""

    def __init__(self, config: Any) -> None:
        """Read the ``voice.stt`` settings."""
        stt = config.section("voice").get("stt", {})
        self.model_name = str(stt.get("model", "base.en"))
        self.device = str(stt.get("device", "auto"))
        self.compute_type = str(stt.get("compute_type", "auto"))
        self.language = str(stt.get("language", "en"))
        self.beam_size = int(stt.get("beam_size", 1))
        self.vad_filter = bool(stt.get("vad_filter", True))
        self.model: Optional[Any] = None
        self.available = False

    async def initialize(self) -> bool:
        """Load the Whisper model (downloads once, then cached locally)."""

        def _load() -> Optional[Any]:
            try:
                from faster_whisper import WhisperModel

                device = self.device
                compute = self.compute_type
                if device == "auto":
                    device = "cpu"
                    try:
                        import ctranslate2

                        if ctranslate2.get_cuda_device_count() > 0:
                            device = "cuda"
                    except Exception:
                        device = "cpu"
                if compute == "auto":
                    compute = "float16" if device == "cuda" else "int8"
                logger.info(
                    "Loading Whisper '%s' on %s (%s) — first run downloads the model.",
                    self.model_name, device, compute,
                )
                return WhisperModel(self.model_name, device=device, compute_type=compute)
            except Exception as exc:
                logger.warning("faster-whisper unavailable: %s", truncate(str(exc), 200))
                return None

        self.model = await run_blocking(_load)
        self.available = self.model is not None
        if self.available:
            logger.info("Speech-to-text ready (%s).", self.model_name)
        return self.available

    async def transcribe(self, clip: AudioClip) -> str:
        """Transcribe an :class:`AudioClip` to text."""
        if not self.available or clip is None or clip.duration < 0.25:
            return ""

        def _run() -> str:
            try:
                segments, _ = self.model.transcribe(  # type: ignore[union-attr]
                    clip.samples,
                    language=self.language or None,
                    beam_size=self.beam_size,
                    vad_filter=self.vad_filter,
                    condition_on_previous_text=False,
                )
                return " ".join(segment.text.strip() for segment in segments).strip()
            except Exception as exc:
                logger.debug("Transcription failed: %s", exc)
                return ""

        text = await run_blocking(_run)
        return text.strip()


# ---------------------------------------------------------------------------
# Wake word
# ---------------------------------------------------------------------------


class WakeWordDetector:
    """Wake-word detection via Porcupine (free tier) or keyless Whisper."""

    def __init__(self, config: Any, microphone: Microphone, stt: SpeechToText) -> None:
        """Args:
        config: Global configuration.
        microphone: Shared microphone wrapper.
        stt: Shared speech-to-text engine (used by the Whisper engine).
        """
        self.config = config
        self.microphone = microphone
        self.stt = stt
        self.wake_word = str(config.get("voice.wake_word", "jarvis")).lower()
        self.requested_engine = str(config.get("voice.engine", "auto")).lower()
        self.access_key = str(config.get("voice.porcupine_access_key", "") or "").strip()
        self.keyword = str(config.get("voice.porcupine_keyword", "jarvis"))
        self.sensitivity = float(config.get("voice.sensitivity", 0.6))
        self.engine = "none"
        self.pending_command: str = ""
        self._porcupine: Optional[Any] = None
        oww = config.section("voice").get("openwakeword", {}) or {}
        self.oww_model = str(oww.get("model", "hey_jarvis"))
        self.oww_threshold = float(oww.get("threshold", 0.5))
        self.oww_framework = str(oww.get("inference_framework", "onnx"))
        self._oww: Optional[Any] = None

    async def initialize(self) -> str:
        """Pick and prepare the best available wake-word engine.

        Returns:
            The engine in use: ``porcupine``, ``whisper`` or ``none``.
        """
        wants_openwakeword = self.requested_engine in {"openwakeword", "oww", "auto"}
        if wants_openwakeword and await run_blocking(self._init_openwakeword):
            self.engine = "openwakeword"
            logger.info(
                "Wake word: openWakeWord ('%s', threshold %.2f) — free and keyless.",
                self.oww_model, self.oww_threshold,
            )
            return self.engine
        if self.requested_engine in {"openwakeword", "oww"}:
            logger.warning(
                "openWakeWord unavailable (pip install openwakeword) — falling back."
            )

        wants_porcupine = self.requested_engine in {"porcupine", "auto"} and self.access_key

        if wants_porcupine:
            if await run_blocking(self._init_porcupine):
                self.engine = "porcupine"
                logger.info("Wake word: Porcupine ('%s').", self.keyword)
                return self.engine
            logger.warning("Porcupine initialisation failed; falling back to Whisper.")

        if self.requested_engine in {"whisper", "auto"} and self.stt.available:
            self.engine = "whisper"
            logger.info(
                "Wake word: local Whisper listening for '%s' (no API key needed).",
                self.wake_word,
            )
            return self.engine

        self.engine = "none"
        logger.warning("No wake-word engine available; use push-to-talk or the CLI.")
        return self.engine

    def _init_porcupine(self) -> bool:
        """Create the Porcupine handle (blocking)."""
        try:
            import pvporcupine

            keywords = [self.keyword]
            try:
                self._porcupine = pvporcupine.create(
                    access_key=self.access_key,
                    keywords=keywords,
                    sensitivities=[self.sensitivity],
                )
            except Exception:
                # Unknown built-in keyword -> fall back to "jarvis".
                self._porcupine = pvporcupine.create(
                    access_key=self.access_key,
                    keywords=["jarvis"],
                    sensitivities=[self.sensitivity],
                )
            return True
        except Exception as exc:
            logger.debug("Porcupine unavailable: %s", exc)
            self._porcupine = None
            return False

    def _init_openwakeword(self) -> bool:
        """Create an openWakeWord model handle (blocking).

        Returns:
            True when the detector is ready to use.
        """
        try:
            import openwakeword
            from openwakeword.model import Model

            with contextlib.suppress(Exception):
                openwakeword.utils.download_models()
            try:
                self._oww = Model(
                    wakeword_models=[self.oww_model],
                    inference_framework=self.oww_framework,
                )
            except Exception:
                # Unknown model name -> load every bundled model instead.
                self._oww = Model(inference_framework=self.oww_framework)
            return True
        except Exception as exc:
            logger.debug("openWakeWord unavailable: %s", exc)
            self._oww = None
            return False

    async def _wait_openwakeword(self, stop_event: asyncio.Event) -> bool:
        """Stream 16 kHz frames into openWakeWord until a model fires."""
        model = self._oww
        if model is None:
            return False

        def _listen() -> bool:
            try:
                import numpy as np
                import sounddevice as sd

                chunk = 1280  # 80 ms at 16 kHz, openWakeWord's native frame
                with sd.InputStream(
                    samplerate=16000, blocksize=chunk, dtype="int16", channels=1
                ) as stream:
                    while not stop_event.is_set():
                        data, _ = stream.read(chunk)
                        frame = np.frombuffer(bytes(data), dtype=np.int16)
                        scores = model.predict(frame)
                        for name, score in scores.items():
                            if score >= self.oww_threshold:
                                logger.debug("openWakeWord '%s' fired at %.2f", name, score)
                                with contextlib.suppress(Exception):
                                    model.reset()
                                return True
            except Exception as exc:
                logger.debug("openWakeWord listen loop error: %s", exc)
            return False

        return bool(await run_blocking(_listen))

    async def wait(self, stop_event: asyncio.Event) -> bool:
        """Block until the wake word is heard.

        Args:
            stop_event: Set this to abort waiting.

        Returns:
            True when the wake word was detected.
        """
        if self.engine == "openwakeword":
            return await self._wait_openwakeword(stop_event)
        if self.engine == "porcupine":
            return await self._wait_porcupine(stop_event)
        if self.engine == "whisper":
            return await self._wait_whisper(stop_event)
        await asyncio.sleep(0.5)
        return False

    async def _wait_porcupine(self, stop_event: asyncio.Event) -> bool:
        """Stream microphone frames into Porcupine until it triggers."""
        porcupine = self._porcupine
        if porcupine is None:
            return False

        def _listen() -> bool:
            try:
                import sounddevice as sd

                with sd.RawInputStream(
                    samplerate=porcupine.sample_rate,
                    blocksize=porcupine.frame_length,
                    dtype="int16",
                    channels=1,
                ) as stream:
                    while not stop_event.is_set():
                        data, _ = stream.read(porcupine.frame_length)
                        pcm = struct.unpack_from("h" * porcupine.frame_length, data)
                        if porcupine.process(pcm) >= 0:
                            return True
            except Exception as exc:
                logger.debug("Porcupine listen loop error: %s", exc)
            return False

        return bool(await run_blocking(_listen))

    async def _wait_whisper(self, stop_event: asyncio.Event) -> bool:
        """Keyless wake word: transcribe short bursts and look for the word."""
        variants = {self.wake_word}
        if self.wake_word == "jarvis":
            # Whisper frequently mishears the name; accept the usual variants.
            variants |= {
                "jarvis", "jarvas", "jervis", "jarvus", "javis", "yarvis", "charvis",
                "jarvez", "harvis", "darvis", "jarv",
            }
        while not stop_event.is_set():
            clip = await run_blocking(
                self.microphone.record_until_silence, 4.0, 3.0
            )
            if clip is None:
                await asyncio.sleep(0.05)
                continue
            if clip.duration > 5.0:
                continue
            text = (await self.stt.transcribe(clip)).lower()
            if not text:
                continue
            logger.debug("Wake candidate: %r", text)
            normalised = "".join(char for char in text if char.isalnum() or char.isspace())
            if any(variant and variant in normalised for variant in variants):
                # Some people say "Jarvis, do X" in one breath — keep the tail.
                self.pending_command = normalised.split(self.wake_word, 1)[-1].strip()
                return True
        return False

    def close(self) -> None:
        """Release the wake-word engine handles."""
        if self._porcupine is not None:
            with contextlib.suppress(Exception):
                self._porcupine.delete()
            self._porcupine = None
        self._oww = None


# ---------------------------------------------------------------------------
# Voice interface
# ---------------------------------------------------------------------------


class VoiceInterface:
    """Ties wake word, STT, TTS and barge-in into one always-listening loop."""

    def __init__(self, config: Any) -> None:
        """Args:
        config: The global configuration object.
        """
        self.config = config
        self.tts = TextToSpeech(config)
        self.microphone = Microphone(config)
        self.stt = SpeechToText(config)
        self.wake = WakeWordDetector(config, self.microphone, self.stt)
        self.interrupt_enabled = bool(config.get("voice.interrupt", True))
        self.chime_enabled = bool(config.get("voice.chime", True))
        self.stream_speech = bool(config.get("voice.stream_speech", True))
        self.conversation_mode = bool(config.get("voice.conversation_mode", True))
        self.conversation_timeout = float(config.get("voice.conversation_timeout", 12))
        self.available = False
        self.listening = False
        self.interrupt_hook: Optional[Callable[[], None]] = None
        self._stop_event = asyncio.Event()
        self._monitor_task: Optional[asyncio.Task] = None
        self.pending_command: str = ""
        self._speaker: Optional[StreamingSpeaker] = None

    # -- lifecycle ----------------------------------------------------------
    async def initialize(self) -> bool:
        """Bring up every audio component.

        Returns:
            True when both input and output are usable.
        """
        mic_ok = await run_blocking(self.microphone.initialize)
        tts_ok, stt_ok = await asyncio.gather(self.tts.initialize(), self.stt.initialize())
        if mic_ok and stt_ok:
            await self.wake.initialize()
        self.available = bool(mic_ok and stt_ok)
        if not self.available:
            logger.warning(
                "Voice input unavailable (mic=%s, stt=%s). Falling back to text mode.",
                mic_ok, stt_ok,
            )
        return self.available

    async def shutdown(self) -> None:
        """Stop listening and release audio resources."""
        self._stop_event.set()
        self.stop_speaking()
        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(Exception):
                await self._monitor_task
        self.wake.close()

    # -- output -------------------------------------------------------------
    async def speak(self, text: str, interruptible: bool = True) -> None:
        """Speak text aloud, allowing the user to interrupt."""
        if not text or not self.tts.available:
            return
        interruptible = interruptible and self.interrupt_enabled and self.microphone.available

        speak_task = asyncio.create_task(self.tts.speak(text, interruptible=interruptible))
        if not interruptible:
            await speak_task
            return

        monitor = asyncio.create_task(self._watch_for_interrupt(speak_task))
        try:
            await speak_task
        finally:
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await monitor

    async def _watch_for_interrupt(self, speak_task: asyncio.Task) -> None:
        """Cut playback when the user starts talking over JARVIS."""
        await asyncio.sleep(0.8)  # let the first words out before listening
        while not speak_task.done():
            heard = await run_blocking(self.microphone.detect_voice, 0.3)
            if heard and self.tts.speaking:
                logger.debug("Barge-in detected — stopping playback.")
                self.tts.stop()
                self.notify_interrupt()
                return
            await asyncio.sleep(0.05)

    def stop_speaking(self) -> None:
        """Immediately silence any current speech."""
        self.tts.stop()
        if self._speaker is not None:
            self._speaker.cancel()

    def notify_interrupt(self) -> None:
        """Tell the brain to abandon the reply the user just talked over."""
        if self._speaker is not None:
            self._speaker.cancel()
        if self.interrupt_hook is not None:
            with contextlib.suppress(Exception):
                self.interrupt_hook()

    async def speak_stream(self, generate: Callable[[Callable[[str], None]], Awaitable[str]]
                           ) -> str:
        """Speak a reply sentence-by-sentence while it is being generated.

        Args:
            generate: Coroutine function taking an ``on_token`` callback and
                returning the finished reply.

        Returns:
            The complete reply text.
        """
        if not self.tts.available or not self.stream_speech:
            reply = await generate(lambda _token: None)
            await self.speak(reply)
            return reply

        speaker = StreamingSpeaker(self.tts)
        self._speaker = speaker
        speaker.start()
        monitor = None
        if self.interrupt_enabled and self.microphone.available:
            monitor = asyncio.create_task(self._watch_stream(speaker))
        try:
            reply = await generate(speaker.feed)
        finally:
            await speaker.finish()
            if monitor is not None:
                monitor.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await monitor
            self._speaker = None
        return reply

    async def _watch_stream(self, speaker: "StreamingSpeaker") -> None:
        """Watch for barge-in during a streamed reply."""
        await asyncio.sleep(1.0)
        while not speaker.cancelled:
            heard = await run_blocking(self.microphone.detect_voice, 0.3)
            if heard and self.tts.speaking:
                logger.debug("Barge-in during streamed reply.")
                self.notify_interrupt()
                return
            await asyncio.sleep(0.05)

    async def chime(self, kind: str = "wake") -> None:
        """Play a short tone to acknowledge the wake word."""
        if not self.chime_enabled:
            return

        def _beep() -> None:
            try:
                import numpy as np
                import sounddevice as sd

                sample_rate = 44100
                duration = 0.12
                frequency = 880.0 if kind == "wake" else 520.0
                t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
                envelope = np.minimum(1.0, np.linspace(0, 6, t.size)) * np.exp(-4 * t)
                tone = 0.18 * np.sin(2 * math.pi * frequency * t) * envelope
                sd.play(tone.astype("float32"), sample_rate)
                sd.wait()
            except Exception:
                pass

        await run_blocking(_beep)

    # -- input --------------------------------------------------------------
    async def listen(self, timeout: Optional[float] = None) -> str:
        """Record one utterance and transcribe it.

        Args:
            timeout: Seconds to wait for speech to begin.

        Returns:
            The transcript, or ``""`` when nothing was said.
        """
        if not self.available:
            return ""
        self.listening = True
        try:
            clip = await run_blocking(
                self.microphone.record_until_silence, None, timeout
            )
            if clip is None:
                return ""
            text = await self.stt.transcribe(clip)
            if text:
                logger.info("Heard: %s", text)
            return text
        finally:
            self.listening = False

    async def wait_for_wake_word(self) -> bool:
        """Block until the wake word is detected."""
        detected = await self.wake.wait(self._stop_event)
        if detected:
            self.pending_command = getattr(self.wake, "pending_command", "") or ""
        return detected

    # -- loop ---------------------------------------------------------------
    async def run(
        self,
        handler: CommandHandler,
        on_wake: Optional[Callable[[], Awaitable[None]]] = None,
        on_transcript: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        """Always-on loop: wake word → command → response.

        When ``handler`` accepts an ``on_token`` keyword (the brain's
        ``process`` does), replies are spoken sentence-by-sentence as they are
        generated. After each reply the microphone stays open for
        ``voice.conversation_timeout`` seconds so follow-ups need no wake word.

        Args:
            handler: Coroutine turning a transcript into a reply string.
            on_wake: Optional coroutine called when the wake word fires.
            on_transcript: Optional coroutine called with each transcript.
        """
        if not self.available:
            logger.error("Voice loop requested but audio is unavailable.")
            return

        streaming = False
        with contextlib.suppress(Exception):
            streaming = "on_token" in inspect.signature(handler).parameters

        self._stop_event.clear()
        logger.info(
            "Listening for '%s' (engine: %s, streaming speech: %s). Ctrl+C to stop.",
            self.wake.wake_word, self.wake.engine,
            "on" if (streaming and self.stream_speech) else "off",
        )

        in_conversation = False
        while not self._stop_event.is_set():
            try:
                if in_conversation:
                    # Follow-up turn: no wake word, just listen for a while.
                    transcript = await self.listen(timeout=self.conversation_timeout)
                    if not transcript.strip():
                        in_conversation = False
                        logger.debug("Conversation window closed.")
                        continue
                elif self.wake.engine == "none":
                    # No wake engine: behave as push-to-talk on any speech.
                    transcript = await self.listen(timeout=30)
                    if not transcript:
                        continue
                else:
                    if not await self.wait_for_wake_word():
                        continue
                    if on_wake:
                        await on_wake()
                    await self.chime("wake")

                    transcript = self.pending_command
                    self.pending_command = ""
                    if len(transcript.split()) < 2:
                        transcript = await self.listen()

                if not transcript.strip():
                    await self.speak("I'm listening, but I heard nothing useful.")
                    continue

                if on_transcript:
                    await on_transcript(transcript)

                if self._is_stop_command(transcript):
                    self.stop_speaking()
                    self.notify_interrupt()
                    in_conversation = self.conversation_mode
                    continue
                if self._is_sleep_command(transcript):
                    in_conversation = False
                    await self.speak("Going quiet. Say my name when you need me.")
                    continue
                if self._is_shutdown_command(transcript):
                    await self.speak("Shutting down. Do try not to break anything.")
                    self._stop_event.set()
                    break

                if streaming and self.stream_speech:
                    reply = await self.speak_stream(
                        lambda on_token, text=transcript: handler(text, on_token=on_token)
                    )
                else:
                    reply = await handler(transcript)
                    if reply:
                        await self.speak(reply)

                in_conversation = self.conversation_mode
                if in_conversation:
                    await self.chime("listen")

            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - the loop must never die
                logger.exception("Voice loop error")
                with contextlib.suppress(Exception):
                    await self.speak(
                        f"Something went wrong in my audio pipeline: {truncate(str(exc), 120)}"
                    )
                await asyncio.sleep(0.5)

    @staticmethod
    def _is_stop_command(text: str) -> bool:
        """Detect a bare 'stop' — cancel the reply but stay in the conversation."""
        lowered = text.lower().strip(" .!,")
        return lowered in {
            "stop", "stop it", "shut up", "be quiet", "quiet", "enough", "cancel",
            "cancel that", "hold on", "wait",
        }

    @staticmethod
    def _is_sleep_command(text: str) -> bool:
        """Detect 'go to sleep' style commands."""
        lowered = text.lower().strip(" .!")
        return lowered in {
            "go to sleep", "sleep", "stand by", "standby", "never mind", "nevermind",
            "stop listening", "that's all", "thats all", "dismissed",
        }

    @staticmethod
    def _is_shutdown_command(text: str) -> bool:
        """Detect commands that should terminate JARVIS."""
        lowered = text.lower().strip(" .!")
        return lowered in {
            "shut down jarvis", "shutdown jarvis", "goodbye jarvis", "exit", "quit",
            "power down", "terminate yourself",
        }

    def stop(self) -> None:
        """Signal the run loop to exit."""
        self._stop_event.set()
        self.stop_speaking()

    # -- diagnostics --------------------------------------------------------
    async def self_test(self) -> dict:
        """Check each audio component and return a report."""
        report = {
            "microphone": self.microphone.available,
            "stt": self.stt.available,
            "stt_model": self.stt.model_name,
            "tts": self.tts.available,
            "tts_voice": self.tts.voice,
            "player": (self.tts._player or ["none"])[0],  # noqa: SLF001
            "wake_engine": self.wake.engine,
            "stream_speech": self.stream_speech,
            "conversation_mode": self.conversation_mode,
        }
        return report


__all__ = [
    "VoiceInterface",
    "TextToSpeech",
    "SpeechToText",
    "Microphone",
    "WakeWordDetector",
    "StreamingSpeaker",
]
