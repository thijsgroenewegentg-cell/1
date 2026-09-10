"""Small, credential-free Spotify/media helper for MARK.

Search and open use Spotify's normal desktop URI/browser. Playback controls use
an available native controller: playerctl on Linux, AppleScript on macOS, and
PyAutoGUI media keys on Windows. No Spotify API credentials are required.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import urllib.parse
import webbrowser


PLUGIN = {
    "name": "media_control",
    "description": (
        "Controls Spotify or the default music player without cloud credentials: "
        "open Spotify, search for music, play a Spotify search, pause/play, skip "
        "tracks, stop playback and show the current track when the operating system "
        "supports it. Use youtube_video for YouTube requests."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "open | search | play | play_pause | next | previous | stop | status | now_playing | volume | volume_up | volume_down | set_volume | mute | shuffle_on | shuffle_off | repeat_off | repeat_track | repeat_context",
            },
            "query": {
                "type": "STRING",
                "description": "Song, artist, album or playlist for search/play",
            },
            "volume": {
                "type": "NUMBER",
                "description": "Target volume from 0 to 100 for set_volume",
            },
        },
        "required": ["action"],
    },
}


def _run_command(args: list[str], timeout: int = 8) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"{args[0]} is not installed."
    except subprocess.TimeoutExpired:
        return 124, "", "The media player took too long to respond."
    except Exception as exc:
        return 1, "", str(exc)


def _open_spotify() -> str:
    system = platform.system()
    try:
        if system == "Windows":
            import os
            os.startfile("spotify:")  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", "-a", "Spotify"])
        else:
            if shutil.which("spotify"):
                subprocess.Popen(["spotify"])
            elif not webbrowser.open("https://open.spotify.com"):
                return "I could not open Spotify."
        return "Spotify opened."
    except Exception:
        try:
            if webbrowser.open("https://open.spotify.com"):
                return "Spotify opened in the browser."
        except Exception:
            pass
        return "Spotify is not installed and could not be opened in a browser."


def _search(query: str) -> str:
    query = query.strip()
    if not query:
        return "Tell me what to search for in Spotify."
    url = "https://open.spotify.com/search/" + urllib.parse.quote(query)
    try:
        if webbrowser.open(url):
            return f"Showing Spotify results for {query}."
    except Exception:
        pass
    return f"I could not open Spotify search for {query}."


def _playerctl(action: str, volume: float | None = None) -> str | None:
    if not shutil.which("playerctl"):
        return None
    mapped = {
        "play_pause": "play-pause",
        "volume_up": "volume 0.05+",
        "volume_down": "volume 0.05-",
        "set_volume": f"volume {max(0.0, min(1.0, float(volume or 0.0) / 100.0)):.3f}",
        "mute": "volume 0",
        "shuffle_on": "shuffle on",
        "shuffle_off": "shuffle off",
        "repeat_off": "loop none",
        "repeat_track": "loop track",
        "repeat_context": "loop playlist",
    }
    if action == "status":
        code, stdout, stderr = _run_command(
            ["playerctl", "status", "--format", "{{status}} | {{artist}} — {{title}}"]
        )
        return stdout if code == 0 and stdout else (stderr or "No media player is active.")
    if action == "now_playing":
        code, stdout, stderr = _run_command(
            ["playerctl", "metadata", "--format", "{{artist}} — {{title}} | {{album}}"]
        )
        return stdout if code == 0 and stdout else (stderr or "Nothing is playing.")
    if action == "volume":
        code, stdout, stderr = _run_command(["playerctl", "volume"])
        if code == 0 and stdout:
            try:
                return f"Volume is {round(float(stdout) * 100)} percent."
            except ValueError:
                return stdout
        return stderr or "The media player did not report a volume."
    command = mapped.get(action, action)
    code, stdout, stderr = _run_command(["playerctl", *command.split()])
    if code == 0:
        return {
            "play_pause": "Playback toggled.",
            "next": "Skipped to the next track.",
            "previous": "Went to the previous track.",
            "stop": "Playback stopped.",
            "volume_up": "Volume increased.",
            "volume_down": "Volume decreased.",
            "set_volume": f"Volume set to {round(float(volume or 0))} percent.",
            "mute": "Media volume muted.",
            "shuffle_on": "Shuffle enabled.",
            "shuffle_off": "Shuffle disabled.",
            "repeat_off": "Repeat disabled.",
            "repeat_track": "Repeating the current track.",
            "repeat_context": "Repeating the current playlist or context.",
        }.get(action, stdout or "Done.")
    return stderr or stdout or "The media player rejected that command."


def _mac_control(action: str, volume: float | None = None) -> str:
    commands = {
        "play_pause": "playpause",
        "next": "next track",
        "previous": "previous track",
        "stop": "stop",
        "shuffle_on": "set shuffling to true",
        "shuffle_off": "set shuffling to false",
        "repeat_off": "set repeating to false",
        "repeat_track": "set repeating to true",
    }
    if action == "status":
        script = 'tell application "Spotify" to (player state as text) & " | " & artist of current track & " — " & name of current track'
    elif action == "now_playing":
        script = 'tell application "Spotify" to artist of current track & " — " & name of current track & " | " & album of current track'
    elif action == "volume":
        script = 'tell application "Spotify" to (sound volume as text)'
    elif action == "set_volume":
        value = max(0, min(100, round(float(volume or 0))))
        script = f'tell application "Spotify" to set sound volume to {value}'
    elif action == "volume_up":
        script = 'tell application "Spotify" to set sound volume to (sound volume + 5)'
    elif action == "volume_down":
        script = 'tell application "Spotify" to set sound volume to (sound volume - 5)'
    elif action == "mute":
        script = 'tell application "Spotify" to set sound volume to 0'
    elif action in commands:
        script = f'tell application "Spotify" to {commands[action]}'
    else:
        return "That media control is not available on macOS."
    code, stdout, stderr = _run_command(["osascript", "-e", script])
    if code == 0:
        if action == "status":
            return stdout or "Spotify is not playing."
        if action == "now_playing":
            return stdout or "Nothing is playing."
        if action == "volume":
            return f"Volume is {stdout} percent." if stdout else "Spotify did not report a volume."
        return {
            "play_pause": "Playback toggled.",
            "next": "Skipped to the next track.",
            "previous": "Went to the previous track.",
            "stop": "Playback stopped.",
            "set_volume": f"Volume set to {round(float(volume or 0))} percent.",
            "volume_up": "Volume increased.",
            "volume_down": "Volume decreased.",
            "mute": "Media volume muted.",
            "shuffle_on": "Shuffle enabled.",
            "shuffle_off": "Shuffle disabled.",
            "repeat_off": "Repeat disabled.",
            "repeat_track": "Repeat enabled.",
        }.get(action, "Done.")
    return stderr or stdout or "Spotify did not accept that command."


def _windows_control(action: str, volume: float | None = None) -> str:
    # PyAutoGUI is already a MARK dependency and sends the same media keys as a
    # physical keyboard. Spotify or another focused media session can handle it.
    if action in {"status", "now_playing", "volume"}:
        return "Detailed media status is not available on Windows without a media API connection."
    if action == "set_volume":
        return "Setting an exact Windows media volume is not available without an optional media API."
    try:
        import pyautogui

        key = {
            "play_pause": "playpause",
            "next": "nexttrack",
            "previous": "prevtrack",
            "stop": "stop",
            "volume_up": "volumeup",
            "volume_down": "volumedown",
            "mute": "volumemute",
        }.get(action)
        if key is None:
            return "Shuffle and repeat controls are not available through Windows media keys."
        pyautogui.press(key)
        return {
            "play_pause": "Playback toggled.",
            "next": "Skipped to the next track.",
            "previous": "Went to the previous track.",
            "stop": "Playback stopped.",
            "volume_up": "Volume increased.",
            "volume_down": "Volume decreased.",
            "mute": "System media volume toggled.",
        }[action]
    except Exception as exc:
        return f"I could not send the media key: {exc}"


def _playback(action: str, volume: float | None = None) -> str:
    system = platform.system()
    if system == "Linux":
        result = _playerctl(action, volume)
        if result is not None:
            return result
        return "Install playerctl to control Linux media players."
    if system == "Darwin":
        return _mac_control(action, volume)
    return _windows_control(action, volume)


def _now_playing() -> str:
    system = platform.system()
    if system == "Linux" and shutil.which("playerctl"):
        code, stdout, stderr = _run_command(
            ["playerctl", "metadata", "--format", "{{artist}} — {{title}}"]
        )
        return stdout if code == 0 and stdout else (stderr or "Nothing is playing.")
    if system == "Darwin":
        code, stdout, stderr = _run_command(
            ["osascript", "-e", "tell application \"Spotify\" to name of current track"]
        )
        return stdout if code == 0 and stdout else (stderr or "Nothing is playing.")
    return "Now-playing lookup is not available on Windows without a Spotify API connection."


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "open")).strip().lower().replace("-", "_")
    query = str(params.get("query", "")).strip()
    try:
        volume = float(params.get("volume")) if params.get("volume") is not None else None
    except (TypeError, ValueError):
        volume = None
    if action == "set_volume" and volume is None:
        return "Tell me the target volume from 0 to 100."
    if volume is not None:
        volume = max(0.0, min(100.0, volume))

    if action == "open":
        result = _open_spotify()
    elif action == "search":
        result = _search(query)
    elif action == "play":
        result = _search(query) if query else _playback("play_pause")
    elif action in {
        "play_pause", "next", "previous", "stop", "status", "volume",
        "volume_up", "volume_down", "set_volume", "mute", "shuffle_on",
        "shuffle_off", "repeat_off", "repeat_track", "repeat_context",
    }:
        result = _playback(action, volume)
    elif action == "now_playing":
        result = _now_playing()
    else:
        return "Unknown media action. Use open, search, play, play_pause, next, previous, stop, status, now_playing, volume, volume_up, volume_down, set_volume, mute, shuffle_on, shuffle_off, repeat_off, repeat_track or repeat_context."

    if player:
        try:
            player.write_log(f"[Media] {action}: {result[:160]}")
        except Exception:
            pass
    return result
