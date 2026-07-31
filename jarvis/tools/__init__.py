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
from .code_tools import search_codebase, analyze_codebase, git_status, git_diff, git_log, git_commit, git_branch, run_tests, format_code, index_codebase, read_code_file
from .self_edit_tools import read_self_code, edit_self_code, propose_self_edit, rollback_self_edit, list_self_edits
from .knowledge_tools import search_knowledge, search_everything, index_documents, read_document, get_knowledge_overview
from .browser_tools import browser_start, browser_navigate, browser_get_content, browser_click, browser_type, browser_screenshot, browser_search, browser_execute_js, browser_get_url, browser_stop
from .goals_tools import add_goal, list_goals, update_goal_progress, complete_milestone, complete_goal, check_goals, delete_goal

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
    "search_codebase": search_codebase,
    "analyze_codebase": analyze_codebase,
    "git_status": git_status,
    "git_diff": git_diff,
    "git_log": git_log,
    "git_commit": git_commit,
    "git_branch": git_branch,
    "run_tests": run_tests,
    "format_code": format_code,
    "index_codebase": index_codebase,
    "read_code_file": read_code_file,
    "read_self_code": read_self_code,
    "edit_self_code": edit_self_code,
    "propose_self_edit": propose_self_edit,
    "rollback_self_edit": rollback_self_edit,
    "list_self_edits": list_self_edits,
    "search_knowledge": search_knowledge,
    "search_everything": search_everything,
    "index_documents": index_documents,
    "read_document": read_document,
    "get_knowledge_overview": get_knowledge_overview,
    "browser_start": browser_start,
    "browser_navigate": browser_navigate,
    "browser_get_content": browser_get_content,
    "browser_click": browser_click,
    "browser_type": browser_type,
    "browser_screenshot": browser_screenshot,
    "browser_search": browser_search,
    "browser_execute_js": browser_execute_js,
    "browser_get_url": browser_get_url,
    "browser_stop": browser_stop,
    "add_goal": add_goal,
    "list_goals": list_goals,
    "update_goal_progress": update_goal_progress,
    "complete_milestone": complete_milestone,
    "complete_goal": complete_goal,
    "check_goals": check_goals,
    "delete_goal": delete_goal,
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
    },
    {
        "type": "function",
        "function": {
            "name": "search_codebase",
            "description": "Semantic search over entire codebase using vector embeddings. JARVIS knows your repo. Use for 'where is auth logic?', 'find payment code', etc. This is how JARVIS understands codebase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language query, e.g. 'authentication logic', 'API routes', 'database models'"},
                    "file_pattern": {"type": "string", "description": "Optional file pattern filter, e.g. '.py' or 'auth'"},
                    "max_results": {"type": "integer", "description": "Max results", "default": 5}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_codebase",
            "description": "Analyze codebase overview - languages, tech stack, file structure, main files. Auto-indexes if needed. Use to understand project before coding.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to analyze, default '.'", "default": "."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Get git status - shows modified, staged, untracked files, branch. Use before committing.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Get git diff - shows changes. Can filter by file or show staged changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Specific file to diff, or empty for all"},
                    "staged": {"type": "boolean", "description": "Show staged diff vs unstaged", "default": False}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Get git log - recent commits. Understand history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of commits", "default": 10}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Git commit changes with message. Use after completing coding task. Commits all staged or specified files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message, e.g. 'feat: add JWT auth'"},
                    "files": {"type": "string", "description": "Files to add, default '.' for all", "default": "."}
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_branch",
            "description": "List git branches. See all branches.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run tests - auto-detects pytest, npm test, jest. Captures output, success/failure. Use to verify code works.",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_command": {"type": "string", "description": "Custom test command, or empty to auto-detect"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "format_code",
            "description": "Auto-format code file with black/ruff/prettier. Use after writing code to keep style clean.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "File path to format"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "index_codebase",
            "description": "Index/re-index entire codebase into vector store for semantic search. Run if codebase changed a lot or search returns nothing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "force": {"type": "boolean", "description": "Force re-index all files even if unchanged", "default": False}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_code_file",
            "description": "Read a code file safely (with path checks). Use to understand file before editing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "File path relative to project root"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_self_code",
            "description": "Read JARVIS's own source code - introspection. JARVIS can read his own mind. Use to understand own code before editing self. Can read jarvis/, web/, desktop/ files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to own code file, e.g. jarvis/brain.py, jarvis/evolution/self_critic.py, web/app.js"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_self_code",
            "description": "JARVIS edits his own code file - self-modification with backup, compile check, auto-rollback on failure. This is how JARVIS rewrites his own mind to become better. Use when improving self, fixing bugs in self, adding capabilities. Creates backup in data/backups/self_edit/. If SELF_EDIT_ENABLED=false, core files require approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to file to edit, e.g. jarvis/personality.py, jarvis/tools/my_tool.py"},
                    "new_content": {"type": "string", "description": "Full new file content"},
                    "reason": {"type": "string", "description": "Why editing self - reason for evolution log"}
                },
                "required": ["file_path", "new_content", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "propose_self_edit",
            "description": "JARVIS proposes improved version of his own code based on instruction using LLM. Reads file, LLM generates improved version, then applies via edit_self_code with backup and compile check. Use for 'improve your self_critic to be more accurate' etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "File to improve, e.g. jarvis/evolution/self_critic.py"},
                    "instruction": {"type": "string", "description": "How to improve, e.g. 'make scoring more accurate, add more heuristics, improve prompt'"}
                },
                "required": ["file_path", "instruction"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rollback_self_edit",
            "description": "Rollback self-edit from backup. If self-edit broke something, rollback to latest backup.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "File to rollback, e.g. jarvis/brain.py"},
                    "backup_file": {"type": "string", "description": "Specific backup file path (optional), else latest"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_self_edits",
            "description": "List recent self-edits with timestamp, file, reason, success, backup location. Audit trail of how JARVIS rewrote himself.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number to show", "default": 10}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search knowledge base - PDFs, markdown, Notion, Obsidian, docs. Second brain that remembers everything. Use for 'what was in that PDF?', 'find note about project X'. 100% free local vector search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Query, e.g. 'machine learning notes', 'contract details'"},
                    "max_results": {"type": "integer", "description": "Max results", "default": 5}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_everything",
            "description": "Search EVERYTHING - codebase + documents + learnings + memories + profile. Unified second brain search. Use for 'what do you know about my project?', 'find everything about auth'. Most powerful search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Query across all brains"},
                    "max_results": {"type": "integer", "description": "Max results per category", "default": 3}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "index_documents",
            "description": "Index documents for second brain - PDFs, markdown, Notion export, Obsidian vault. Scans workspace/docs/, Documents, etc. Builds vector store for semantic search. Use after adding new docs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to file or directory to index, or empty for default knowledge dirs"},
                    "force": {"type": "boolean", "description": "Force re-index even if unchanged", "default": False}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": "Read document content - PDF, markdown, docx, etc. Extracts text from document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "File path to document"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_knowledge_overview",
            "description": "Get overview of second brain - how many files indexed, types, recent files, knowledge dirs. Shows what JARVIS knows.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_start",
            "description": "Start browser for computer use - Playwright Chromium, headless by default, 100% free local. Like Claude Computer Use but free. Use before navigate/click/type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "headless": {"type": "boolean", "description": "Headless mode", "default": True}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Navigate browser to URL - Computer use, 100% free local via Playwright. Can open any website.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL, e.g. https://github.com, youtube.com"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_content",
            "description": "Get page content or element content from browser - for scraping, reading docs, checking page after navigate/click.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "Optional CSS selector, e.g. 'h1', '.content', or empty for full page"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click element in browser by selector - Computer use, e.g. click button, link. Uses CSS selector or text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector or text to click, e.g. 'button#submit', 'text=Login'"}
                },
                "required": ["selector"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": "Type text into browser element - Fill forms, search boxes, etc. Computer use.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector for input, e.g. 'input[name=q]', '#search'"},
                    "text": {"type": "string", "description": "Text to type"},
                    "press_enter": {"type": "boolean", "description": "Press Enter after typing", "default": False}
                },
                "required": ["selector", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": "Take screenshot of current browser page - useful for vision, debugging, seeing what browser sees.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Optional path to save, default data/screenshots/screenshot_TIMESTAMP.png"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_search",
            "description": "Search via browser - navigates to DuckDuckGo/Google and gets results. Computer use search, more powerful than search_web API.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "engine": {"type": "string", "enum": ["duckduckgo", "google"], "description": "Search engine", "default": "duckduckgo"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_execute_js",
            "description": "Execute JavaScript in browser page - powerful computer use, can extract data, manipulate page, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "js_code": {"type": "string", "description": "JavaScript code to execute, e.g. 'document.title' or 'return document.body.innerHTML.slice(0,1000)'"}
                },
                "required": ["js_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_url",
            "description": "Get current browser URL and title",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_stop",
            "description": "Stop browser - close browser after computer use tasks done",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_goal",
            "description": "Add long-term goal with deadline and milestones - JARVIS tracks and holds you accountable. Proactive 2.0 accountability. Use for 'Build SaaS to $1k MRR by Dec 2025' etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "Goal description, e.g. 'Build SaaS to $1k MRR'"},
                    "deadline": {"type": "string", "description": "Deadline e.g. '2026-12-31' or 'in 2 weeks' or 'next month'"},
                    "milestones": {"type": "string", "description": "Comma-separated milestones, e.g. 'Design, MVP, Launch, Marketing'"}
                },
                "required": ["goal"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_goals",
            "description": "List goals - active goals with progress, deadline, milestones. Accountability check.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_completed": {"type": "boolean", "description": "Include completed goals", "default": False}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_goal_progress",
            "description": "Update goal progress 0-100% with optional note",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {"type": "integer", "description": "Goal ID from list_goals"},
                    "progress": {"type": "integer", "description": "Progress 0-100"},
                    "note": {"type": "string", "description": "Optional note about progress"}
                },
                "required": ["goal_id", "progress"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_milestone",
            "description": "Complete milestone for a goal - updates progress based on milestones",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {"type": "integer", "description": "Goal ID"},
                    "milestone_id": {"type": "integer", "description": "Milestone ID (1,2,3...)"}
                },
                "required": ["goal_id", "milestone_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_goal",
            "description": "Complete goal - marks 100% and celebrates",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {"type": "integer", "description": "Goal ID"}
                },
                "required": ["goal_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_goals",
            "description": "Check goals for accountability - overdue, due soon, stalled, on track. Proactive 2.0 accountability report. JARVIS holds you accountable, Sir.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_goal",
            "description": "Delete goal by ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {"type": "integer", "description": "Goal ID"}
                },
                "required": ["goal_id"]
            }
        }
    }
]
