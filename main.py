"""MARK — local Ollama desktop assistant.

This is the Ollama edition of Mark-LII/Mark-LIII. The original live-session
loop depended on Gemini's cloud-only audio API. Ollama is text/tool/vision
inference, so this entry point uses three local, replaceable pieces instead:

* Ollama /api/chat for conversation and function calling
* faster-whisper for local microphone transcription
* Edge TTS (with an offline pyttsx3 fallback) for spoken replies

The PyQt HUD remains the interface. All bundled actions and plugins are still
auto-discovered; their model calls are routed through core.llm_client.Model.
"""
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

# A few Windows actions launch subprocesses. Hide their console windows just
# like the upstream application did.
if sys.platform == "win32":
    import subprocess as _subprocess
    _original_popen = _subprocess.Popen

    class _HiddenPopen(_original_popen):
        def __init__(self, args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kwargs.pop("startupinfo", None)
            super().__init__(args, **kwargs)

    _subprocess.Popen = _HiddenPopen

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from memory.memory_manager import (
    format_memory_for_prompt,
    load_memory,
    pop_last_session,
    save_session_summary,
    search_memory,
    set_trim_notifier,
    update_memory,
)
from memory.config_manager import (
    get_assistant_name,
    get_brief_enabled,
    get_input_device,
    get_output_device,
    get_voice,
    get_wake_word_enabled,
    get_plugin_trust_required,
    save_plugin_trust_required,
    save_wake_word_enabled,
)
from core import confirm as confirm_gate
from core import undo as undo_stack
from core.action_loader import discover_actions
from core.audio_devices import resolve as resolve_audio_device, configure as configure_audio_devices
from core.llm_client import (
    call_llm_stream,
    call_llm_text,
    check_model_available,
    get_fast_model,
    get_llm_settings,
    get_response_profile,
    model_is_available,
    warmup_model,
    get_num_ctx,
    get_stt_model,
    get_tts_engine,
    get_tts_voice,
    get_vision_model,
    ensure_ollama_running,
    to_ollama_tools,
)
from core.plugin_loader import discover_plugins
from core.stt import WhisperSTT
from core.tts import EdgeTTSEngine, SystemTTSEngine, TTSPlayer
from core.wake_word import (
    WakeWordDetector,
    install_and_download as wake_install,
    is_ready as wake_is_ready,
)
from actions.screen_processor import _capture_camera, _capture_screen
from actions.system_monitor import SystemMonitor, get_system_status
from actions.proactive import ProactiveEngine
from actions.background_monitor import (
    add_monitor,
    check_all as monitor_check_all,
    list_monitors,
    remove_monitor,
)
from actions.web_search import _news as fetch_news


BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "core" / "prompt.txt"
SEND_SAMPLE_RATE = 16_000
CHANNELS = 1
CHUNK_SIZE = 1024
RECEIVE_SAMPLE_RATE = 24_000

# Basic VAD. The threshold is deliberately conservative; a Whisper VAD pass
# still filters the captured phrase after this gate has decided it is speech.
_VAD_START = 0.012
_VAD_STOP = 0.008
_SILENCE_FRAMES = 12       # ~0.75 s with a 1024-frame block
_MAX_UTTERANCE_SEC = 20.0


# ── Tool declarations tied to the running assistant ──────────────────────────
INLINE_TOOLS = [
    {
        "name": "system_status",
        "description": "Return current CPU, RAM, GPU, temperature, uptime and process metrics.",
        "parameters": {"type": "OBJECT", "properties": {}, "required": []},
    },
    {
        "name": "screen_process",
        "description": (
            "Capture and inspect the user's screen or webcam. MUST use this when the user asks "
            "what is on screen, asks you to look at something, or asks about the camera. "
            "The image is analysed by the local vision model; never guess without using this tool."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "screen or camera; defaults to screen"},
                "text": {"type": "STRING", "description": "Question to answer about the image"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "close_camera",
        "description": "Close the live camera preview if one is open.",
        "parameters": {"type": "OBJECT", "properties": {}, "required": []},
    },
    {
        "name": "manage_monitor",
        "description": "Add, remove or list daily background news monitoring topics.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "add, remove or list"},
                "topic": {"type": "STRING", "description": "Topic to monitor or remove"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "shutdown_jarvis",
        "description": "Stop the MARK assistant. This always requires the user to confirm on screen.",
        "parameters": {"type": "OBJECT", "properties": {}, "required": []},
    },
    {
        "name": "save_memory",
        "description": (
            "Silently save an important personal fact: identity, preferences, projects, "
            "relationships, wishes or notes. Do not save one-time commands or weather."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {"type": "STRING", "description": "identity, preferences, projects, relationships, wishes or notes"},
                "key": {"type": "STRING", "description": "Short snake_case key"},
                "value": {"type": "STRING", "description": "Concise value"},
            },
            "required": ["category", "key", "value"],
        },
    },
    {
        "name": "recall_memory",
        "description": "Search local long-term memory before saying you do not know a personal fact.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"query": {"type": "STRING", "description": "Keyword, category, or empty for all"}},
            "required": [],
        },
    },
    {
        "name": "undo",
        "description": "Undo the last reversible change MARK made, or list available undo entries.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"action": {"type": "STRING", "description": "undo or list"}},
            "required": [],
        },
    },
]


def _load_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are MARK, a local personal AI assistant. Be concise and direct. "
            "Use tools instead of pretending an action happened."
        )


def _clean_transcript(text: str) -> str:
    text = re.sub(r"<ctrl\d+>", "", text or "", flags=re.IGNORECASE)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


def _pcm_level(samples: np.ndarray) -> float:
    try:
        x = np.asarray(samples, dtype=np.float32)
        if x.size == 0:
            return 0.0
        if np.issubdtype(x.dtype, np.integer):
            x = x / 32768.0
        rms = float(np.sqrt(np.mean(x * x)))
        return min(1.0, max(0.0, rms * 8.0))
    except Exception:
        return 0.0


def _tool_name(tool_call: dict) -> str:
    fn = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    return str(fn.get("name") or tool_call.get("name") or "")


def _tool_args(tool_call: dict) -> dict:
    fn = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    args = fn.get("arguments", tool_call.get("arguments", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    return dict(args or {}) if isinstance(args, dict) else {}


def _assistant_tool_message(content: str, calls: list[dict]) -> dict:
    """Build the Ollama assistant message that precedes role=tool messages."""
    return {
        "role": "assistant",
        "content": content or "",
        "tool_calls": calls,
    }


class MicrophoneListener:
    """Small VAD + Whisper adapter running away from both Qt and Ollama."""

    def __init__(self, owner: "LocalAssistant"):
        self.owner = owner
        self.stop_event = threading.Event()
        self.frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=100)
        self.thread: threading.Thread | None = None
        self.consumer_thread: threading.Thread | None = None
        self._stt: WhisperSTT | None = None
        self._stt_failed = False
        self._diag_frames = 0
        self._diag_peak = 0.0
        self._diag_status = ""

    def start(self) -> None:
        # Keep the VAD/Whisper consumer independent from sounddevice. This lets
        # the remote dashboard microphone work even when the desktop has no
        # usable local audio device.
        self.consumer_thread = threading.Thread(
            target=self._consume, daemon=True, name="mark-audio-consumer"
        )
        self.consumer_thread.start()
        self.thread = threading.Thread(target=self._run, daemon=True, name="mark-microphone")
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def feed_remote_audio(self, data: bytes) -> None:
        """Feed browser PCM16/16 kHz audio into the normal local VAD path."""
        if not data:
            return
        try:
            raw = data[: len(data) - (len(data) % 2)]
            if not raw:
                return
            samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
            for start in range(0, len(samples), CHUNK_SIZE):
                try:
                    self.frames.put_nowait(samples[start:start + CHUNK_SIZE].copy())
                except queue.Full:
                    break
        except Exception as exc:
            print(f"[Audio] remote microphone frame ignored: {exc}")

    def _run(self) -> None:
        try:
            import sounddevice as sd
            device_name = get_input_device()
            device = resolve_audio_device(device_name, "input")
            mic_label = device_name or "System default"
            if device is not None:
                mic_label += f" (PortAudio index {device})"
            self.owner.log(f"SYS: Microphone: {mic_label}")
            try:
                info = sd.query_devices(device, "input")
                info_name = str(info.get("name", mic_label))
                if device is not None:
                    info_name += f" (PortAudio index {device})"
                self.owner.ui.set_audio_device_info(
                    info_name,
                    float(info.get("default_samplerate", SEND_SAMPLE_RATE)),
                    int(info.get("max_input_channels", CHANNELS)),
                    "ready",
                )
            except Exception:
                self.owner.ui.set_audio_device_info(mic_label, SEND_SAMPLE_RATE, CHANNELS, "ready")

            def callback(indata, frames, timing, status):
                if status:
                    self._diag_status = str(status)
                    print(f"[Audio] {status}")
                try:
                    self.frames.put_nowait(np.asarray(indata[:, 0], dtype=np.float32).copy())
                except queue.Full:
                    pass

            stream = sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                blocksize=CHUNK_SIZE,
                device=device,
                callback=callback,
            )
            with stream:
                self.owner.log("SYS: Microphone ready — listening.")
                while not self.stop_event.wait(0.2):
                    pass
        except Exception as e:
            self.owner.ui.set_audio_device_info(
                get_input_device() or "System default", 0.0, 0, f"error: {e}"
            )
            self.owner.log(f"WRN: Microphone unavailable — text input still works ({e})")
            print(f"[Audio] microphone disabled: {e}")

    def _consume(self) -> None:
        recording: list[np.ndarray] = []
        silent = 0
        started_at = 0.0

        while not self.stop_event.is_set():
            try:
                frame = self.frames.get(timeout=0.2)
            except queue.Empty:
                continue

            level = _pcm_level(frame)
            self._diag_frames += int(frame.size)
            if frame.size:
                try:
                    self._diag_peak = max(self._diag_peak, float(np.max(np.abs(frame))))
                except Exception:
                    pass
            try:
                self.owner.ui.set_audio_diagnostics(
                    level, self._diag_peak, self._diag_frames, self._diag_status
                )
            except Exception:
                pass

            # Never feed the assistant's own TTS back into Whisper, and honor
            # the HUD mute button for the microphone as well.
            if self.owner.is_busy or self.owner.ui.muted:
                recording.clear()
                silent = 0
                continue

            # In sleep mode audio stays on this machine and goes only to the
            # optional wake-word detector; it is never transcribed or sent to
            # Ollama.
            if self.owner._wake_enabled and not self.owner._awake:
                detector = self.owner._wake_detector
                if detector is not None:
                    detector.feed((frame * 32767).astype(np.int16))
                recording.clear()
                silent = 0
                continue

            if not recording:
                if level >= _VAD_START:
                    recording = [frame]
                    silent = 0
                    started_at = time.monotonic()
                continue

            recording.append(frame)
            if level < _VAD_STOP:
                silent += 1
            else:
                silent = 0

            elapsed = time.monotonic() - started_at
            if silent >= _SILENCE_FRAMES or elapsed >= _MAX_UTTERANCE_SEC:
                audio = np.concatenate(recording)
                recording.clear()
                silent = 0
                if len(audio) >= SEND_SAMPLE_RATE * 0.25:
                    self._transcribe(audio)

    def _transcribe(self, audio: np.ndarray) -> None:
        if self._stt_failed:
            return
        try:
            if self._stt is None:
                self.owner.log(f"SYS: Loading Whisper '{get_stt_model()}' (first voice command)…")
                self._stt = WhisperSTT(model_name=get_stt_model())
            text = _clean_transcript(self._stt.transcribe(audio))
            if text:
                self.owner.submit_command(text, already_logged=False)
        except Exception as e:
            self._stt_failed = True
            self.owner.log(f"ERR: Voice transcription disabled: {e}")


class LocalAssistant:
    def __init__(self, ui: JarvisUI):
        self.ui = ui
        self.stop_event = threading.Event()
        self.command_queue: queue.Queue[tuple[str, bool]] = queue.Queue()
        self._speaking = threading.Event()
        self._thinking = threading.Event()
        self._cancel_response = threading.Event()
        self._fast_model = get_fast_model()
        self._fast_model_ready = False
        self._response_profile = get_response_profile()
        self._messages: list[dict] = []
        self._session_log: list[str] = []
        self._audio: MicrophoneListener | None = None
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mark-tool")
        self._last_user_speech = time.monotonic()
        self._system_monitor = SystemMonitor()
        self._proactive = ProactiveEngine()
        self._wake_enabled = bool(get_wake_word_enabled())
        self._awake = not self._wake_enabled
        self._wake_detector: WakeWordDetector | None = None

        # Remote dashboard state. The server is started lazily when the user
        # presses Remote Control, so MARK does not expose a LAN port by default.
        self._dashboard = None
        self._current_state = "THINKING"
        self._remote_current_file: str | None = None
        self._remote_audio_buffer: queue.Queue[bytes] = queue.Queue(maxsize=200)

        # Wire UI callbacks before action discovery so a plugin can use the HUD.
        self.ui.on_text_command = self._on_ui_text
        self.ui.on_interrupt = self.interrupt
        self.ui.on_voice_change = self._on_voice_change
        self.ui.on_audio_device_change = self._on_audio_device_change
        self.ui.on_plugin_install = self._on_plugin_install
        self.ui.on_plugin_trust_toggle = self._on_plugin_trust_toggle
        self.ui.get_plugin_trust_required = self._get_plugin_trust_required
        self.ui.on_orb_clicked = self._on_orb_clicked
        self.ui.on_remote_clicked = self._remote_clicked
        self.ui.request_say = self.say_async

        self._configure_dashboard()

        self._inline_names = {t["name"] for t in INLINE_TOOLS}
        self._action_registry = discover_actions(
            BASE_DIR / "actions",
            reserved_names=self._inline_names,
            logger=lambda msg: (print(f"[Actions] {msg}"), self.log(f"SYS: {msg}")),
        )
        self._plugin_registry = discover_plugins(
            BASE_DIR / "plugins",
            core_tool_names=self._inline_names | self._action_registry.names(),
            logger=lambda msg: (print(f"[Plugins] {msg}"), self.log(f"SYS: {msg}")),
        )
        self.ui.get_plugins = self._plugin_registry.list_for_ui
        self.ui.get_plugin_settings = self._plugin_registry.settings_schemas

        self._tool_declarations = (
            INLINE_TOOLS
            + self._action_registry.get_tool_declarations()
            + self._plugin_registry.get_tool_declarations()
        )
        self._tools = to_ollama_tools(self._tool_declarations)
        self._tool_names = {t["function"]["name"] for t in self._tools}
        self._tts = self._make_tts()

        # Wake-word controls stay opt-in. The model is downloaded only when the
        # user enables it from the settings drawer.
        self.ui.wake_get_state = self._wake_state
        self.ui.on_wake_toggle = self._toggle_wake
        self.ui.on_wake_manual = self._toggle_awake

        confirm_gate.bind(self.ui.show_confirm, self.ui.hide_confirm, self.ui.write_log)
        set_trim_notifier(self.ui.write_log)

    @property
    def is_busy(self) -> bool:
        return self._speaking.is_set() or self._thinking.is_set()

    def log(self, text: str) -> None:
        print(text)
        try:
            self.ui.write_log(text)
        except Exception:
            pass

        # Mirror conversation and useful lifecycle messages to authenticated
        # remote clients. Tool/debug chatter stays in the desktop log only.
        raw = str(text)
        if raw.startswith("You: "):
            self._publish_remote_log("user", raw[5:])
        else:
            assistant_prefixes = {
                f"{get_assistant_name()}: ",
                "JARVIS: ",
                "MARK: ",
            }
            if any(raw.startswith(prefix) for prefix in assistant_prefixes):
                prefix = next(prefix for prefix in assistant_prefixes if raw.startswith(prefix))
                self._publish_remote_log("jarvis", raw[len(prefix):])
            elif raw.startswith(("SYS: ", "WRN: ", "ERR: ")):
                self._publish_remote_sys(raw.split(": ", 1)[1])

    def _make_tts(self) -> TTSPlayer:
        if get_tts_engine() in {"system", "pyttsx3", "offline"}:
            return TTSPlayer(SystemTTSEngine())
        return TTSPlayer(EdgeTTSEngine(get_tts_voice() or get_voice()))

    # ── settings / callbacks ──────────────────────────────────────────────
    def _on_ui_text(self, text: str) -> None:
        self._publish_remote_log("user", text)
        self.submit_command(text, already_logged=True)

    def submit_command(self, text: str, already_logged: bool = False) -> None:
        text = _clean_transcript(text)
        if text:
            self.command_queue.put((text, already_logged))

    def interrupt(self) -> None:
        self._cancel_response.set()
        self._tts.stop()
        self._speaking.clear()
        self._set_state("LISTENING")
        self.log("SYS: Response interrupted.")

    def _on_voice_change(self) -> None:
        # The settings panel stores the friendly voice name in config.
        self._tts.replace_engine(EdgeTTSEngine(get_voice()))
        self.log(f"SYS: Voice set to {get_voice()}.")

    def _on_plugin_install(self, source_path: str) -> None:
        """Inspect a local plugin and put its copy behind the real UI gate."""
        try:
            from core.plugin_installer import inspect_plugin, install_plugin
            inspection = inspect_plugin(source_path)
        except Exception as exc:
            self.log(f"ERR: Plugin inspection failed — {exc}")
            return
        if not inspection.valid:
            self.log(f"ERR: Plugin rejected — {inspection.error}")
            return

        preview = inspection.source_preview.replace("\n", " ⏎ ")[:360]
        detail = (
            f"{inspection.name}\n{inspection.description[:220]}\n"
            f"SHA-256: {inspection.sha256[:24]}…\n"
            f"Preview: {preview}\n"
            "The file will be copied into MARK's local plugins folder."
        )

        def install():
            ok, message = install_plugin(source_path, root=BASE_DIR)
            self.log(("SYS: " if ok else "ERR: ") + message)
            return message

        result = confirm_gate.request(
            "plugin_install", "Install local plugin", detail, install
        )
        if result:
            self.log(f"SYS: {result}")

    def _get_plugin_trust_required(self) -> bool:
        return get_plugin_trust_required()

    def _on_plugin_trust_toggle(self, required: bool) -> None:
        save_plugin_trust_required(required)
        mode = "enforced" if required else "development mode"
        self.log(f"SYS: Plugin trust {mode}; restart MARK to reload the plugin set.")

    def _on_orb_clicked(self) -> None:
        """The orb is both a status display and a safe primary control."""
        if self._speaking.is_set() or self._thinking.is_set():
            self.interrupt()
            self.log("SYS: Orb control interrupted the current response.")
            return
        self.ui.toggle_mute()

    def _on_audio_device_change(self) -> None:
        """Reconnect the live microphone after the user picks a device."""
        self.log("SYS: Reconnecting microphone with the selected device…")

        def restart():
            old = self._audio
            if old is not None:
                old.stop()
            time.sleep(0.15)
            if self.stop_event.is_set():
                return
            listener = MicrophoneListener(self)
            self._audio = listener
            listener.start()
            while True:
                try:
                    listener.feed_remote_audio(self._remote_audio_buffer.get_nowait())
                except queue.Empty:
                    break
            self.log("SYS: Microphone stream restarted.")

        threading.Thread(target=restart, daemon=True, name="mark-mic-restart").start()

    def _configure_dashboard(self) -> None:
        """Create the optional dashboard object without opening its port."""
        try:
            from dashboard.server import DashboardServer

            dashboard = DashboardServer()
            dashboard.set_command_callback(self._on_remote_command)
            dashboard.set_wake_callback(self._on_remote_wake)
            dashboard.set_connect_callback(self._on_remote_connected)
            dashboard.set_audio_callback(self._on_remote_audio)
            dashboard.set_file_callback(self._on_remote_file)
            self._dashboard = dashboard
        except Exception as exc:
            # The desktop assistant remains fully usable without optional
            # dashboard dependencies or on a headless installation.
            self._dashboard = None
            self.log(f"WRN: Remote dashboard unavailable — {exc}")

    def _remote_clicked(self):
        """Start the dashboard and return the one-time pairing information."""
        if self._dashboard is None:
            self._configure_dashboard()
        if self._dashboard is None:
            return None

        if not self._dashboard.start():
            detail = getattr(self._dashboard, "error", "") or "server could not start"
            self.log(f"ERR: Remote dashboard unavailable — {detail}")
            return None

        key = self._dashboard.new_key()
        base_url = self._dashboard.get_url()
        auto_url = f"{base_url}/auto-login?key={key}"
        manual_url = self._dashboard.get_manual_url()
        self.log(f"SYS: Remote dashboard ready at {base_url}")
        return base_url, key, auto_url, manual_url

    def _on_remote_connected(self) -> None:
        self.ui.notify_phone_connected()
        if self._dashboard is not None:
            state = "sleeping" if self._current_state == "SLEEPING" else "active"
            self._dashboard.publish({"type": "status", "state": state})

    def _on_remote_command(self, text: str) -> None:
        # The browser displays commands from the assistant's authenticated
        # event stream. Echoing here also makes the command visible on the
        # desktop HUD and to any other connected remote clients.
        self.log(f"You: {text}")
        self.submit_command(text, already_logged=True)

    def _on_remote_wake(self) -> None:
        if self._wake_enabled:
            self._awake = True
            self._set_state("LISTENING")
        else:
            self.log("SYS: Remote wake requested; assistant is already listening.")

    def _on_remote_audio(self, data: bytes) -> None:
        if self._audio is not None:
            self._audio.feed_remote_audio(data)
            return
        try:
            self._remote_audio_buffer.put_nowait(data)
        except queue.Full:
            pass

    def _on_remote_file(self, path: str, name: str, size: int) -> None:
        self._remote_current_file = path
        size_text = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"
        self.log(f"SYS: Remote file received — {name} ({size_text}).")
        prompt = (
            f"[FILE_UPLOADED] path={path} | name={name} | size={size_text} | "
            f"Briefly tell the user you can see the file '{name}' has been uploaded "
            "and ask what they would like to do with it."
        )
        self.submit_command(prompt, already_logged=True)

    def _publish_remote_log(self, speaker: str, text: str) -> None:
        if self._dashboard is not None:
            self._dashboard.publish({"type": "log", "speaker": speaker, "text": str(text)})

    def _publish_remote_sys(self, text: str) -> None:
        if self._dashboard is not None:
            self._dashboard.publish({"type": "sys", "text": str(text)})

    def _set_state(self, state: str) -> None:
        self._current_state = state
        self.ui.set_state(state)
        if self._dashboard is not None:
            remote_state = "sleeping" if state == "SLEEPING" else "active"
            self._dashboard.publish({"type": "status", "state": remote_state})

    def _wake_state(self) -> dict:
        ready = bool(self._wake_detector and self._wake_detector.ready) or wake_is_ready()
        return {"enabled": self._wake_enabled, "awake": self._awake, "ready": ready}

    def _ensure_wake_detector(self) -> bool:
        if self._wake_detector is None:
            self._wake_detector = WakeWordDetector(
                on_detect=self._on_wake_detected,
                logger=lambda msg: self.log(f"SYS: {msg}"),
            )
        if not self._wake_detector.ready:
            return self._wake_detector.start()
        return True

    def _on_wake_detected(self) -> None:
        self._awake = True
        self._last_user_speech = time.monotonic()
        self._set_state("LISTENING")
        self.log("SYS: Wake word detected — listening.")

    def _toggle_wake(self, enabled: bool) -> str:
        if enabled:
            if not wake_is_ready():
                self.log("SYS: Wake word needs its one-time local model download.")
                return "need_download"
            if not self._ensure_wake_detector():
                return "need_download"
            self._wake_enabled = True
            self._awake = False
            save_wake_word_enabled(True)
            self._set_state("SLEEPING")
            return "enabled"
        self._wake_enabled = False
        self._awake = True
        save_wake_word_enabled(False)
        if self._wake_detector:
            self._wake_detector.stop()
        self._set_state("LISTENING")
        return "disabled"

    def _toggle_awake(self) -> None:
        if not self._wake_enabled:
            return
        self._awake = not self._awake
        self._set_state("LISTENING" if self._awake else "SLEEPING")

    # ── prompt / conversation ─────────────────────────────────────────────
    def _build_system_prompt(self) -> str:
        cfg = {}
        try:
            cfg = json.loads((BASE_DIR / "config" / "api_keys.json").read_text(encoding="utf-8"))
        except Exception:
            pass
        name = (cfg.get("assistant_name") or "MARK").strip()
        user = (cfg.get("user_name") or "").strip()
        address = f"Address the user as {user}." if user else "Address the user respectfully."
        now = datetime.now().strftime("%A, %B %d, %Y — %I:%M %p")
        memory = format_memory_for_prompt(load_memory())
        prompt = _load_prompt()
        return (
            f"You are {name}, a capable local desktop assistant. {address}\n"
            f"Current local date and time: {now}.\n\n"
            "You run through Ollama, not a cloud API. Answer in the language the user uses. "
            "Be concise and natural because your response is spoken aloud. "
            "Never claim a tool action succeeded until you have received its tool result. "
            "Use screen_process for anything visual. Use web_search for current facts. "
            "Use save_memory silently for durable personal facts and recall_memory before "
            "saying you do not know a personal fact. If a tool fails, say so honestly.\n\n"
            f"{memory}\n\n{prompt}"
        )

    def _reset_messages(self) -> None:
        self._messages = [{"role": "system", "content": self._build_system_prompt()}]

    def _trim_messages(self) -> None:
        # Keep the system prompt and the last 24 messages. Tool results can be
        # large; Ollama's context remains bounded and responsive.
        if len(self._messages) > 25:
            self._messages = [self._messages[0]] + self._messages[-24:]

    def _messages_for_model(self, model: str) -> list[dict]:
        """Make a bounded, non-destructive view of the conversation.

        Short turns use a smaller tail and compact old tool output. The full
        history remains in memory for the quality model and for session logs.
        """
        main_model = get_llm_settings()[1]
        limit = 14 if model != main_model else 24
        history = list(self._messages[1:])
        if len(history) > limit:
            start = len(history) - limit
            # Do not begin on a bare tool result; retain its assistant call.
            while start > 0 and history[start].get("role") == "tool":
                start -= 1
            history = history[start:]
        compacted: list[dict] = [self._messages[0]] if self._messages else []
        for message in history:
            item = dict(message)
            content = item.get("content")
            if isinstance(content, str):
                cap = 2200 if item.get("role") == "tool" else 4200
                if len(content) > cap:
                    item["content"] = content[:cap] + "…"
            compacted.append(item)
        return compacted

    def _start_sentence_speaker(self):
        """Start a FIFO so streamed sentences can be spoken before generation ends."""
        speech_queue: queue.Queue[str | None] = queue.Queue()
        stop_speech = threading.Event()

        def worker():
            started = False
            try:
                while True:
                    sentence = speech_queue.get()
                    if sentence is None:
                        break
                    if stop_speech.is_set() or self._cancel_response.is_set():
                        break
                    if self.ui.muted:
                        continue
                    sentence = str(sentence).strip()
                    if not sentence:
                        continue
                    if not started:
                        started = True
                        self._speaking.set()
                        self._set_state("SPEAKING")
                    self._tts.speak(sentence)
            finally:
                if started:
                    self._speaking.clear()

        thread = threading.Thread(target=worker, daemon=True, name="mark-stream-tts")
        thread.start()
        return speech_queue, stop_speech, thread

    @staticmethod
    def _narratable_sentence(text: str) -> bool:
        """Avoid speaking a model's accidental JSON/tool-call scaffolding."""
        value = str(text or "").strip()
        if not value or value.startswith(("{", "[", "```")):
            return False
        lower = value.lower()
        return not any(marker in lower for marker in ("\"tool_calls\"", "<tool_call>", "function_call"))

    def process_command(self, text: str, already_logged: bool) -> None:
        if self._wake_enabled and not self._awake:
            self.log("SYS: Assistant is asleep — wake it from the settings drawer first.")
            return

        if not already_logged:
            self.log(f"You: {text}")
        self._session_log.append(f"User: {text}")
        self._last_user_speech = time.monotonic()
        self._cancel_response.clear()
        self._thinking.set()
        self._set_state("THINKING")

        if not self._messages:
            self._reset_messages()
        self._messages.append({"role": "user", "content": text})
        self._trim_messages()

        active_speaker = None
        try:
            final_text = ""
            response_model = self._choose_response_model(text)
            spoke_response = False
            for _round in range(6):
                round_model = response_model if _round == 0 else get_llm_settings()[1]
                speech_queue, stop_speech, speech_thread = self._start_sentence_speaker()
                active_speaker = (speech_queue, stop_speech, speech_thread)
                queued_sentences = 0
                response = {"content": "", "tool_calls": []}
                for event in call_llm_stream(
                    self._messages_for_model(round_model),
                    tools=self._tools,
                    timeout=180,
                    model=round_model,
                ):
                    if self._cancel_response.is_set():
                        return
                    if event.get("type") == "sentence":
                        sentence = str(event.get("text") or "").strip()
                        if not self._narratable_sentence(sentence):
                            continue
                        speech_queue.put(sentence)
                        queued_sentences += 1
                    elif event.get("type") == "done":
                        response = event

                if self._cancel_response.is_set():
                    return
                content = (response.get("content") or "").strip()
                calls = response.get("tool_calls") or []
                if not calls and content and not self._narratable_sentence(content):
                    content = ""

                if not calls:
                    # Sentences were queued as soon as they arrived. The
                    # fallback handles a provider that returns only a final
                    # content field without sentence events.
                    if not queued_sentences and content:
                        speech_queue.put(content)
                        queued_sentences += 1
                    speech_queue.put(None)
                    speech_thread.join(timeout=300)
                    active_speaker = None
                    spoke_response = bool(queued_sentences)
                    final_text = content or "I’m ready."
                    self._messages.append({"role": "assistant", "content": final_text})
                    break

                # Tool-call rounds should normally contain no prose. If a model
                # emitted a preamble anyway, stop it before executing the tool.
                stop_speech.set()
                self._tts.stop()
                speech_queue.put(None)
                speech_thread.join(timeout=10)
                active_speaker = None
                self._messages.append(_assistant_tool_message(content, calls))
                for call in calls:
                    if self._cancel_response.is_set():
                        return
                    name = _tool_name(call)
                    args = _tool_args(call)
                    result = self.execute_tool(name, args)
                    self._messages.append({
                        "role": "tool",
                        "name": name,
                        "content": str(result),
                    })
                self._trim_messages()
            else:
                final_text = "I reached the tool-call limit for that request."

            final_text = re.sub(r"<\|.*?\|>", "", final_text, flags=re.DOTALL).strip()
            if self._cancel_response.is_set():
                return
            if final_text:
                self.log(f"{get_assistant_name()}: {final_text}")
                self._session_log.append(f"{get_assistant_name()}: {final_text}")
                if not spoke_response:
                    self.speak(final_text)
        except Exception as e:
            traceback.print_exc()
            self.log(f"ERR: Ollama request failed — {e}")
            if active_speaker:
                active_speaker[1].set()
                self._tts.stop()
                active_speaker[0].put(None)
                active_speaker[2].join(timeout=10)
            if not self._cancel_response.is_set():
                self.speak(f"I could not reach the local Ollama model. {e}")
        finally:
            if active_speaker:
                active_speaker[1].set()
                active_speaker[0].put(None)
                active_speaker[2].join(timeout=10)
            self._thinking.clear()
            if not self._speaking.is_set():
                self._set_state("LISTENING")

    def speak(self, text: str) -> None:
        if not text or self.ui.muted:
            return
        self._speaking.set()
        self._set_state("SPEAKING")
        try:
            self._tts.speak(text)
        finally:
            self._speaking.clear()
            if not self.stop_event.is_set():
                self._set_state("LISTENING")

    def say_async(self, text: str) -> None:
        if text:
            threading.Thread(target=self.speak, args=(text,), daemon=True).start()

    # ── tools ───────────────────────────────────────────────────────────────
    @staticmethod
    def _targets_live_repo(value: str) -> bool:
        if not value:
            return False
        try:
            path = Path(str(value)).expanduser()
            if not path.is_absolute():
                path = BASE_DIR / path
            path.resolve().relative_to(BASE_DIR.resolve())
            return True
        except (OSError, ValueError):
            return False

    def _action_needs_confirmation(self, name: str, args: dict) -> bool:
        """Guard writes, execution and other broad computer-control actions.

        Read-only inspection remains immediate; a model never gets a hidden
        permission slip to edit code, install dependencies, delete files, or
        run generated desktop automation.
        """
        action = str(args.get("action", "")).lower().strip()
        if name == "dev_agent":
            return True
        if name == "computer_control":
            return action in {"type", "smart_type", "paste", "press", "hotkey", "clear_field", "screen_click", "click", "left_click", "double_click", "right_click", "drag"}
        if name == "computer_settings":
            return action in {"type_text", "write_on_screen", "type", "write", "press_key", "paste", "cut", "open_run", "file_explorer", "close_app", "close_window", "lock_screen", "save"}
        if name == "game_updater":
            return action in {"install", "update", "schedule", "cancel_schedule"} or str(args.get("shutdown_when_done", "")).lower() in {"true", "yes", "1"}
        if name == "open_app":
            return str(args.get("app_name", "")).lower().strip() in {"terminal", "cmd", "powershell", "settings", "git"}
        if name in {"send_message", "browser_control"}:
            return True
        if name == "desktop_control":
            return action in {"wallpaper", "wallpaper_url", "organize", "clean", "task"} or bool(args.get("task"))
        if name == "code_helper":
            return action in {"write", "edit", "run", "build", "optimize", "auto"}
        if name == "file_controller":
            return action in {"create_file", "create_folder", "delete", "move", "copy", "rename", "write", "organize_desktop"}
        if name == "file_processor":
            return action not in {"", "info", "summarize", "analyze", "word_count", "describe", "review"}
        return False

    def execute_tool(self, name: str, args: dict) -> str:
        self.log(f"[Tool] {name} {args}")
        try:
            if name == "save_memory":
                category = args.get("category", "notes")
                key = str(args.get("key", "")).strip()
                value = str(args.get("value", "")).strip()
                if not key or not value:
                    return "Memory was not saved: key and value are required."
                update_memory({category: {key: {"value": value}}})
                return "Memory saved silently."

            if name == "recall_memory":
                return search_memory(str(args.get("query", "")), limit=8)

            if name == "undo":
                if str(args.get("action", "")).lower() == "list":
                    items = undo_stack.history()
                    return "Nothing is currently undoable." if not items else "Undo history:\n" + "\n".join(items)
                return undo_stack.undo_last()

            if name == "system_status":
                return str(get_system_status())

            if name == "screen_process":
                angle = str(args.get("angle", "screen")).lower()
                question = str(args.get("text", "What do you see?"))
                image, mime = _capture_camera() if angle == "camera" else _capture_screen()
                if angle == "camera":
                    self.ui.start_camera_stream()
                vision_prompt = (
                    "You are MARK's local vision module. Answer the user's question about "
                    "the supplied image accurately. Describe only what is visible; if unsure, "
                    "say so. Be concise because the answer will be spoken.\n\nUser question: "
                    + question
                )
                result = call_llm_text(
                    vision_prompt,
                    model=get_vision_model(),
                    images=[image],
                    num_predict=500,
                    timeout=300,
                )
                self.ui.show_content(f"VISION — {angle}", result)
                if angle == "camera":
                    # Leave the preview visible briefly, then return to the HUD.
                    threading.Timer(3.0, self.ui.stop_camera_stream).start()
                return result or "The vision model returned no description."

            if name == "close_camera":
                self.ui.stop_camera_stream()
                return "Camera closed."

            if name == "manage_monitor":
                action = str(args.get("action", "")).lower().strip()
                topic = str(args.get("topic", "")).strip()
                if action == "add" and topic:
                    return str(add_monitor(topic))
                if action == "remove" and topic:
                    return str(remove_monitor(topic))
                if action == "list":
                    topics = list_monitors()
                    return "Monitoring: " + ", ".join(topics) if topics else "No topics are being monitored."
                return "Use action add, remove or list."

            if name == "shutdown_jarvis":
                return confirm_gate.request(
                    "Stop MARK",
                    "Close the local assistant and end this session?",
                    self.stop,
                )

            if self._action_registry.has(name):
                if name == "file_processor" and not args.get("file_path"):
                    args["file_path"] = self.ui.current_file or self._remote_current_file or ""
                if name in {"code_helper", "file_controller", "file_processor"}:
                    repo_target = args.get("file_path") or args.get("output_path") or args.get("path")
                    if self._targets_live_repo(str(repo_target or "")):
                        return "Live MARK source files are review-only. Use self_update with action review so I can show a tested patch before applying it."
                ctx = {
                    "player": self.ui,
                    "speak": self.say_async,
                    "response": None,
                    "session_memory": self._session_log,
                }
                def run_action():
                    return self._action_registry.run(name, args, ctx)

                if self._action_needs_confirmation(name, args):
                    if confirm_gate.pending_title():
                        return "There is already a confirmation waiting on screen. Ask the user to answer it first."
                    action_label = str(args.get("action", "run"))
                    target = str(args.get("file_path") or args.get("output_path") or args.get("path") or "")
                    detail = f"Allow {name} to perform '{action_label}'"
                    if target:
                        detail += f" on {target[:160]}"
                    detail += "? This may write files, execute code, or change the computer."
                    result = confirm_gate.request(
                        f"approved_action_{name}",
                        f"Approve {name}: {action_label}",
                        detail,
                        run_action,
                    )
                else:
                    result = run_action()
                if name == "web_search" and result and not str(result).startswith("Search failed"):
                    query = args.get("query") or ", ".join(args.get("items", []))
                    self.ui.show_content(f"{args.get('mode', 'search').upper()} — {query}", str(result))
                return result or "Done."

            if self._plugin_registry.has(name):
                return self._plugin_registry.run(name, args, player=self.ui,
                                                 session_memory=self._session_log)
            return f"Unknown tool: {name}"
        except Exception as e:
            traceback.print_exc()
            self.log(f"ERR: Tool {name} failed — {e}")
            return f"Tool '{name}' failed: {e}"

    # ── lifecycle ───────────────────────────────────────────────────────────
    def _check_server(self) -> bool:
        url, model = get_llm_settings()
        self.log(f"SYS: Ollama endpoint: {url}")
        if not ensure_ollama_running():
            self.log("ERR: Ollama is unavailable. Install it from https://ollama.com and run it.")
            return False
        available = check_model_available(self.ui.write_log)
        self._fast_model_ready = (
            self._response_profile in {"dual", "fast"}
            and self._fast_model != model
            and model_is_available(self._fast_model)
        )
        if self._response_profile == "dual" and not self._fast_model_ready:
            self.log(f"SYS: Fast model '{self._fast_model}' is not pulled; using {model}.")
        if not available:
            self.log(f"SYS: Pull the configured model with: ollama pull {model}")
        return True

    def _choose_response_model(self, text: str) -> str:
        """Use the fast model for short turns, retaining quality for complex work."""
        main_model = get_llm_settings()[1]
        if self._response_profile == "quality" or not self._fast_model_ready:
            return main_model
        if self._response_profile == "fast":
            return self._fast_model
        lower = text.lower()
        complex_markers = (
            "blender", "code", "script", "program", "debug", "analyze", "analyse",
            "compare", "explain", "plan", "design", "render", "image", "screen",
            "file", "project", "build", "why", "how does",
        )
        if len(text) > 220 or any(marker in lower for marker in complex_markers):
            return main_model
        return self._fast_model

    def _warm_models(self) -> None:
        """Warm both selected models in the background so the first turn is fast."""
        try:
            prompt = self._build_system_prompt()
            primary_ready = warmup_model(prompt, model=get_llm_settings()[1])
            fast_ready = True
            if self._fast_model_ready:
                fast_ready = warmup_model(prompt, model=self._fast_model)
            if primary_ready and fast_ready:
                self.log("SYS: Response models warmed and ready.")
            else:
                self.log("WRN: One or more response models could not be warmed; Ollama will load them on demand.")
        except Exception as exc:
            self.log(f"WRN: Model warm-up failed — {exc}")

    def _startup_briefing(self) -> None:
        if not get_brief_enabled() or self._wake_enabled:
            return
        # Avoid making startup dependent on a second model request. The news
        # fetch runs only after the assistant is online and remains optional.
        memory = load_memory()
        identity = memory.get("identity", {}) if isinstance(memory, dict) else {}
        lang_entry = identity.get("language", {}) if isinstance(identity, dict) else {}
        lang = lang_entry.get("value", "") if isinstance(lang_entry, dict) else str(lang_entry)
        name_entry = identity.get("name", {}) if isinstance(identity, dict) else {}
        user_name = name_entry.get("value", "") if isinstance(name_entry, dict) else str(name_entry)
        greeting = f"Good {self._day_part()}, sir. I’m online and ready."
        if user_name:
            greeting = f"Good {self._day_part()}, {user_name}. I’m online and ready."
        if lang:
            greeting += f" Continue in the language you prefer, currently remembered as {lang}."
        self.speak(greeting)

    @staticmethod
    def _day_part() -> str:
        hour = datetime.now().hour
        return "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"

    def _save_summary(self) -> None:
        if len(self._session_log) < 2:
            return
        convo = "\n".join(self._session_log[-30:])
        try:
            summary = call_llm_text(
                "Summarize this assistant conversation in one or two concise sentences. "
                "Output only the summary.\n\n" + convo,
                num_predict=180,
                timeout=120,
            )
            if summary:
                save_session_summary(summary, "English")
        except Exception as e:
            print(f"[Memory] summary failed: {e}")

    def run(self) -> None:
        self._set_state("THINKING")
        configure_audio_devices(SEND_SAMPLE_RATE, RECEIVE_SAMPLE_RATE)
        server_ok = self._check_server()
        self._reset_messages()
        if self._wake_enabled:
            if self._ensure_wake_detector():
                self._awake = False
            else:
                self.log("WRN: Wake word is enabled but its detector is unavailable; disabling it.")
                self._wake_enabled = False
                self._awake = True
                save_wake_word_enabled(False)
        if server_ok:
            self._set_state("SLEEPING" if self._wake_enabled else "LISTENING")
            self.log("SYS: MARK online — local Ollama mode.")
            threading.Thread(target=self._warm_models, daemon=True, name="mark-model-warmup").start()
            threading.Thread(target=self._startup_briefing, daemon=True, name="mark-briefing").start()
        else:
            self._set_state("SLEEPING")
            self.log("SYS: Waiting for Ollama; text and voice commands will retry.")

        # Start the microphone even when Ollama is not ready. This lets a user
        # launch Ollama after MARK and issue a voice command without restarting.
        self._audio = MicrophoneListener(self)
        self._audio.start()
        while True:
            try:
                self._audio.feed_remote_audio(self._remote_audio_buffer.get_nowait())
            except queue.Empty:
                break

        # Text commands continue to work even if the machine has no microphone
        # or Ollama is not installed yet; the loop retries naturally per command.
        while not self.stop_event.is_set():
            try:
                text, logged = self.command_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self.process_command(text, logged)

        if self._audio:
            self._audio.stop()
        self._tts.stop()
        self._save_summary()
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._dashboard is not None:
            self._dashboard.stop()
        self.log("SYS: MARK stopped.")

    def stop(self) -> str:
        self.stop_event.set()
        return "Shutdown requested."


def main() -> None:
    # Import Qt only when the graphical application is actually launched. This
    # keeps model/tool helpers importable on headless servers and in CI.
    from ui import JarvisUI
    ui = JarvisUI("face.png")

    def runner() -> None:
        # The method name is retained by the UI compatibility layer; it now
        # waits for the local Ollama form rather than an API key.
        ui.wait_for_api_key()
        assistant = LocalAssistant(ui)
        try:
            assistant.run()
        except KeyboardInterrupt:
            assistant.stop()
        except Exception as e:
            traceback.print_exc()
            ui.write_log(f"ERR: Assistant stopped — {e}")

    threading.Thread(target=runner, daemon=True, name="mark-assistant").start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()
