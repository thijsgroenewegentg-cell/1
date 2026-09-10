"""Local text-to-speech for the Ollama build.

Ollama produces text, not audio.  MARK therefore uses free Microsoft Edge
neural voices by default (internet required, no API key) and falls back to the
operating system's pyttsx3 voice when Edge is unavailable.
"""
from __future__ import annotations

import asyncio
import os
import threading
from typing import Callable, Optional

import numpy as np
try:
    import sounddevice as sd
except Exception:  # PortAudio may be absent on a headless install
    sd = None


_EDGE_VOICES = {
    "Guy":   "en-US-GuyNeural",
    "Jenny": "en-US-JennyNeural",
    "Aria":  "en-US-AriaNeural",
    "Sonia": "en-GB-SoniaNeural",
    "Ryan":  "en-GB-RyanNeural",
}


def _play_audio_bytes(audio_bytes: bytes) -> None:
    """Decode MP3 bytes and play them synchronously."""
    import miniaudio
    decoded = miniaudio.decode(
        audio_bytes,
        output_format=miniaudio.SampleFormat.FLOAT32,
        nchannels=1,
    )
    samples = np.asarray(decoded.samples, dtype=np.float32)
    if sd is None:
        raise RuntimeError("PortAudio/sounddevice is unavailable")
    sd.play(samples, decoded.sample_rate)
    sd.wait()


class EdgeTTSEngine:
    """Microsoft Edge TTS — free and natural, but requires internet."""

    def __init__(self, voice: str = "Guy"):
        self.voice = _EDGE_VOICES.get(voice, voice if "-" in voice else "en-US-GuyNeural")

    def speak(self, text: str) -> None:
        async def _run() -> bytes:
            import edge_tts
            communicator = edge_tts.Communicate(text, self.voice)
            buf = bytearray()
            async for chunk in communicator.stream():
                if chunk.get("type") == "audio":
                    buf.extend(chunk.get("data", b""))
            return bytes(buf)

        loop = asyncio.new_event_loop()
        try:
            audio = loop.run_until_complete(_run())
        finally:
            loop.close()
        if audio:
            _play_audio_bytes(audio)


class SystemTTSEngine:
    """Offline fallback through pyttsx3."""

    def speak(self, text: str) -> None:
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        engine.stop()


class TTSPlayer:
    """Thread-safe blocking player; call speak from a worker thread."""

    def __init__(self, engine):
        self._engine = engine
        self._playing = False
        self._lock = threading.Lock()

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._playing

    def replace_engine(self, engine) -> None:
        with self._lock:
            self._engine = engine

    def speak(self, text: str, on_start: Optional[Callable] = None,
              on_done: Optional[Callable] = None) -> None:
        if not text or not text.strip():
            return
        try:
            with self._lock:
                self._playing = True
                engine = self._engine
            if on_start:
                on_start()
            try:
                engine.speak(text)
            except Exception as first:
                # Edge can fail due to a temporary network problem. Do not make
                # the assistant silent: try the local voice once.
                print(f"[TTS] Primary engine failed: {first} — using offline fallback")
                try:
                    SystemTTSEngine().speak(text)
                except Exception as fallback:
                    print(f"[TTS] Offline fallback failed: {fallback}")
        finally:
            with self._lock:
                self._playing = False
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass

    def stop(self) -> None:
        try:
            if sd is not None:
                sd.stop()
        finally:
            with self._lock:
                self._playing = False


def create_tts_player(config: dict | None = None) -> TTSPlayer:
    config = config or {}
    engine_name = str(config.get("tts_engine", "edgetts")).lower()
    voice = str(config.get("tts_voice", "Guy"))
    if engine_name in {"system", "pyttsx3", "offline"}:
        engine = SystemTTSEngine()
    else:
        engine = EdgeTTSEngine(voice)
    return TTSPlayer(engine)
