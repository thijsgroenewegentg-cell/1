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
                "description": "open | search | play | play_pause | next | previous | stop | now_playing",
            },
            "query": {
                "type": "STRING",
                "description": "Song, artist, album or playlist for search/play",
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


def _playerctl(action: str) -> str | None:
    if not shutil.which("playerctl"):
        return None
    mapped = {"play_pause": "play-pause", "previous": "previous"}
    command = mapped.get(action, action)
    code, stdout, stderr = _run_command(["playerctl", command])
    if code == 0:
        return {
            "play_pause": "Playback toggled.",
            "next": "Skipped to the next track.",
            "previous": "Went to the previous track.",
            "stop": "Playback stopped.",
        }.get(action, stdout or "Done.")
    return stderr or stdout or "The media player rejected that command."


def _mac_control(action: str) -> str:
    commands = {
        "play_pause": "playpause",
        "next": "next track",
        "previous": "previous track",
        "stop": "stop",
    }
    command = commands[action]
    code, stdout, stderr = _run_command(
        ["osascript", "-e", f'tell application "Spotify" to {command}']
    )
    if code == 0:
        return {
            "play_pause": "Playback toggled.",
            "next": "Skipped to the next track.",
            "previous": "Went to the previous track.",
            "stop": "Playback stopped.",
        }[action]
    return stderr or stdout or "Spotify did not accept that command."


def _windows_control(action: str) -> str:
    # PyAutoGUI is already a MARK dependency and sends the same media keys as a
    # physical keyboard. Spotify or another focused media session can handle it.
    try:
        import pyautogui

        key = {
            "play_pause": "playpause",
            "next": "nexttrack",
            "previous": "prevtrack",
            "stop": "stop",
        }[action]
        pyautogui.press(key)
        return {
            "play_pause": "Playback toggled.",
            "next": "Skipped to the next track.",
            "previous": "Went to the previous track.",
            "stop": "Playback stopped.",
        }[action]
    except Exception as exc:
        return f"I could not send the media key: {exc}"


def _playback(action: str) -> str:
    system = platform.system()
    if system == "Linux":
        result = _playerctl(action)
        if result is not None:
            return result
        return "Install playerctl to control Linux media players."
    if system == "Darwin":
        return _mac_control(action)
    return _windows_control(action)


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

    if action == "open":
        result = _open_spotify()
    elif action == "search":
        result = _search(query)
    elif action == "play":
        result = _search(query) if query else _playback("play_pause")
    elif action in {"play_pause", "next", "previous", "stop"}:
        result = _playback(action)
    elif action == "now_playing":
        result = _now_playing()
    else:
        return "Unknown media action. Use open, search, play, play_pause, next, previous, stop or now_playing."

    if player:
        try:
            player.write_log(f"[Media] {action}: {result[:160]}")
        except Exception:
            pass
    return result
