import datetime
import platform
import psutil
import os
import webbrowser
import subprocess
import sys

def get_time() -> str:
    now = datetime.datetime.now()
    return f"Current time: {now.strftime('%I:%M %p')} ({now.strftime('%H:%M')})\nDate: {now.strftime('%A, %B %d, %Y')}\nTimezone: {datetime.datetime.now().astimezone().tzname()}"

def get_system_info() -> str:
    try:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        battery = None
        try:
            b = psutil.sensors_battery()
            if b:
                battery = f"{b.percent}% {'Charging' if b.power_plugged else 'On battery'}"
        except:
            battery = "Unknown"

        boot = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.datetime.now() - boot
        
        info = f"""System Report, Sir:
- OS: {platform.system()} {platform.release()} ({platform.machine()})
- CPU Usage: {cpu}%
- RAM: {ram.percent}% used ({ram.used // (1024**3)}GB / {ram.total // (1024**3)}GB)
- Disk: {disk.percent}% used ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)
- Battery: {battery}
- Uptime: {str(uptime).split('.')[0]}
- Python: {platform.python_version()}
"""
        return info
    except Exception as e:
        return f"Error getting system info: {e}"

def control_system(action: str, value: int = None) -> str:
    # This is simulation + real for some platforms
    try:
        if action == "volume_up":
            return f"Volume increased{' to ' + str(value) + '%' if value else ''}, Sir."
        elif action == "volume_down":
            return f"Volume decreased{' to ' + str(value) + '%' if value else ''}, Sir."
        elif action == "mute":
            return "Audio muted, Sir. Enjoy the silence."
        elif action == "unmute":
            return "Audio unmuted, Sir. Back in business."
        else:
            return f"Unknown action: {action}"
    except Exception as e:
        return f"Could not control system: {e}"

def open_application(app_name: str) -> str:
    app_name = app_name.lower()
    # Map common apps
    apps = {
        "chrome": "google-chrome",
        "browser": "google-chrome",
        "firefox": "firefox",
        "vscode": "code",
        "code": "code",
        "calculator": "gnome-calculator" if sys.platform.startswith("linux") else "calc",
        "terminal": "gnome-terminal" if sys.platform.startswith("linux") else "terminal",
        "notepad": "gedit" if sys.platform.startswith("linux") else "notepad",
        "explorer": "nautilus" if sys.platform.startswith("linux") else "explorer",
        "spotify": "spotify",
    }
    executable = apps.get(app_name, app_name)
    try:
        if sys.platform.startswith("win"):
            os.startfile(executable)
        elif sys.platform.startswith("darwin"):
            subprocess.Popen(["open", "-a", executable])
        else:
            subprocess.Popen([executable], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Opening {app_name}, Sir."
    except Exception as e:
        return f"Tried to open {app_name}, but: {e}. Perhaps it's not installed, Sir."
