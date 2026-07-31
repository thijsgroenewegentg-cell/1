"""
JARVIS Tools - All skills JARVIS can use via Ollama function calling
"""
from .system import get_time, get_system_info, control_system, open_application
from .web import search_web, get_weather, open_website
from .files import file_read, file_write, file_list, file_delete
from .code import execute_python, shell_command
from .memory_tools import remember, recall, forget, get_memories
from .timer import set_timer, set_reminder
from .evolution_tools import improve_self, create_new_tool, analyze_performance, get_evolution_history, self_reflect

# Map name -> function for execution
TOOL_MAP = {
    "get_time": get_time,
    "get_system_info": get_system_info,
    "control_system": control_system,
    "open_application": open_application,
    "search_web": search_web,
    "get_weather": get_weather,
    "open_website": open_website,
    "file_read": file_read,
    "file_write": file_write,
    "file_list": file_list,
    "file_delete": file_delete,
    "execute_python": execute_python,
    "shell_command": shell_command,
    "remember": remember,
    "recall": recall,
    "forget": forget,
    "get_memories": get_memories,
    "set_timer": set_timer,
    "set_reminder": set_reminder,
    "improve_self": improve_self,
    "create_new_tool": create_new_tool,
    "analyze_performance": analyze_performance,
    "get_evolution_history": get_evolution_history,
    "self_reflect": self_reflect,
}

# Ollama compatible tool schemas (OpenAI format)
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Get current time, date, day of week. ALWAYS use this for time-related questions.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "Get system information: CPU usage, RAM, disk, OS, battery, uptime",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for current information, news, facts, definitions, anything real-time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Number of results", "default": 5}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather for a city. Use for weather questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name, e.g. London, New York"},
                    "units": {"type": "string", "enum": ["metric", "imperial"], "default": "metric"}
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Save something to long-term memory. Use when user says 'remember', 'note', 'don't forget'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Category or key, e.g. birthday, preference"},
                    "value": {"type": "string", "description": "What to remember"},
                    "importance": {"type": "integer", "description": "1-10 importance", "default": 5}
                },
                "required": ["key", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Recall something from memory. Search memories by query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for in memories"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_memories",
            "description": "Get all saved memories",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": "Delete a memory by key or content",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Key or phrase to delete"}
                },
                "required": ["key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_list",
            "description": "List files in workspace directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path inside workspace, default '.'", "default": "."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read a file from workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write/create a file in workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace"},
                    "content": {"type": "string", "description": "File content"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_delete",
            "description": "Delete a file in workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": "Execute Python code and return output. Use for calculations, coding tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"}
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shell_command",
            "description": "Execute a shell command (ls, pwd, echo, etc). Be careful.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_website",
            "description": "Open a website URL in default browser or return that you'd open it",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to open, e.g. https://youtube.com"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Attempt to open an application by name",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "Application name like chrome, vscode, calculator, notepad"}
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_system",
            "description": "Control system settings like volume",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["volume_up", "volume_down", "mute", "unmute"], "description": "Action"},
                    "value": {"type": "integer", "description": "Optional value percentage"}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": "Set a timer for X seconds/minutes",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration": {"type": "integer", "description": "Duration number"},
                    "unit": {"type": "string", "enum": ["seconds", "minutes", "hours"], "default": "seconds"},
                    "label": {"type": "string", "description": "Label for timer", "default": "Timer"}
                },
                "required": ["duration"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "Save a reminder with message and time",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Reminder message"},
                    "time": {"type": "string", "description": "When, e.g. 'in 10 minutes', 'tomorrow 9am'"}
                },
                "required": ["message", "time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "improve_self",
            "description": "Self-improvement: JARVIS analyzes own performance and evolves - improves prompt, optimizes memory, forges tools. Use when asked to improve yourself, or when performance is low. This is how JARVIS makes himself better.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string", "description": "What to improve, e.g. 'be more concise', 'learn to control spotify', 'improve tool use'", "default": ""}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_new_tool",
            "description": "Create a new tool capability when existing tools insufficient. JARVIS forges new Python tool autonomously. Use when user asks for something you can't do with current tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "description": "Snake_case name for new tool, e.g. spotify_control, gmail_check"},
                    "description": {"type": "string", "description": "Short description of tool"},
                    "purpose": {"type": "string", "description": "Full purpose and what user asked, e.g. User wants to control Spotify playback"}
                },
                "required": ["tool_name", "description", "purpose"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_performance",
            "description": "Analyze own performance - latency, tool success, satisfaction, trend. Identify if self-evolution needed.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_evolution_history",
            "description": "Get history of self-improvements and tool forges",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of recent evolutions to show", "default": 5}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "self_reflect",
            "description": "Self-reflection - JARVIS reflects on recent conversations, learns about user, identifies improvements",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    }
]
