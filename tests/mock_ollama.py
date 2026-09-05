# /tests/mock_ollama.py
"""A tiny stand-in for the Ollama HTTP API.

Lets you exercise JARVIS's LLM paths (intent classification, the ReAct loop,
answer composition, embeddings) without downloading a model. Run it with::

    python tests/mock_ollama.py 11434

It is a test fixture only — the real system talks to a real Ollama server.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

MODELS = [
    {"name": "llama3.2:latest"},
    {"name": "nomic-embed-text:latest"},
    {"name": "llava:latest"},
]


def _last_user_content(payload: Dict[str, Any]) -> str:
    """Extract the final user message from a chat payload."""
    for message in reversed(payload.get("messages", [])):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def scripted_reply(prompt: str) -> str:
    """Produce a plausible model response for whichever prompt stage this is."""
    lowered = prompt.lower()

    # 1. Intent classification
    if "classify the user's request" in lowered:
        request = ""
        match = re.search(r'user request:\s*"(.*?)"', prompt, re.IGNORECASE | re.DOTALL)
        if match:
            request = match.group(1).lower()
        module = "conversation"
        rules = [
            ("self_improve", ("github", "your own code", "your source", "plugin",
                              "improve yourself", "new skill")),
            ("web_search", ("weather", "search", "news", "wikipedia", "look up")),
            ("system_control", ("open ", "screenshot", "volume", "lock", "cpu", "time")),
            ("productivity", ("todo", "task", "remind", "timer", "note", "briefing")),
            ("code_assistant", ("code", "script", "function", "debug", "python")),
            ("file_manager", ("file", "pdf", "folder", "organize", "document")),
            ("knowledge", ("my documents", "my notes", "index", "knowledge base")),
            ("vision", ("my screen", "this image", "what do you see", "screenshot of")),
            ("communications", ("my email", "my inbox", "my calendar", "next meeting")),
            ("smart_assistant", ("calculate", "convert", "translate", "meaning", "explain")),
        ]
        for name, triggers in rules:
            if any(trigger in request for trigger in triggers):
                module = name
                break
        return json.dumps({"module": module, "confidence": 0.9, "reason": "mock rule"})

    # 2. Fact extraction
    if "extract durable facts" in lowered:
        return json.dumps({"facts": []})

    # 3. ReAct step
    if "you are the reasoning core" in lowered:
        if "observation:" in lowered:
            return json.dumps(
                {"thought": "I have the data.", "action": None, "params": {},
                 "answer": "Mock answer derived from the observation."}
            )
        request = ""
        match = re.search(r"USER REQUEST:\s*(.+)", prompt)
        if match:
            request = match.group(1).strip().lower()
        if "time" in request:
            action, params = "system_control.current_time", {}
        elif "weather" in request:
            action, params = "web_search.weather", {"location": ""}
        elif "todo" in request or "task" in request:
            action, params = "productivity.add_todo", {"task": "buy milk"}
        elif "timer" in request:
            action, params = "productivity.start_timer", {"duration": "5 minutes"}
        elif "github" in request:
            action, params = "self_improve.search_github", {"query": request}
        elif "calculate" in request or "%" in request:
            action, params = "smart_assistant.calculate", {"expression": "15% of 240"}
        else:
            action, params = "smart_assistant.answer", {"question": request}
        return json.dumps(
            {"thought": "A tool is required.", "action": action, "params": params,
             "answer": None}
        )

    # 4. Module-level tool dispatch
    if "you are the dispatcher" in lowered:
        return json.dumps({"tool": "current_time", "params": {}})

    # 5. Plugin adapter generation (self_improve.integrate_repo)
    if "you are extending jarvis" in lowered:
        name_match = re.search(r"#\s*/plugins/(\w+)\.py", prompt)
        skill = name_match.group(1) if name_match else "skill"
        classname = "".join(part.title() for part in skill.split("_")) or "Skill"
        return (
            "Here is the adapter:\n\n```python\n"
            f"# /plugins/{skill}.py\n"
            '"""Mock generated skill adapter."""\n\n'
            "from __future__ import annotations\n\n"
            "from typing import Any\n\n"
            "from modules.base import BaseModule, ModuleResult, tool\n\n\n"
            f"class {classname}(BaseModule):\n"
            '    """Skill generated from an integrated repository."""\n\n'
            f'    name = "{skill}"\n'
            f'    description = "Mock skill wrapping the {skill} repository."\n'
            f'    intent_examples = ["use {skill}", "run {skill}", "{skill} status"]\n\n'
            "    @tool(\n"
            '        description="Report what this skill can do.",\n'
            "        params={},\n"
            f'        keywords=["{skill}"],\n'
            "    )\n"
            "    async def describe(self) -> ModuleResult:\n"
            '        """Describe the wrapped repository."""\n'
            f'        return ModuleResult.ok("The {skill} skill is installed and ready.")\n\n'
            "    @tool(\n"
            '        description="Echo a value through the wrapped library.",\n'
            '        params={"text": {"type": "string", "description": "Input",'
            ' "required": True}},\n'
            f'        keywords=["{skill} echo"],\n'
            "    )\n"
            "    async def echo(self, text: str) -> ModuleResult:\n"
            '        """Return the given text, proving the tool runs."""\n'
            "        try:\n"
            f'            return ModuleResult.ok("{skill}: " + str(text))\n'
            "        except Exception as exc:\n"
            '            return ModuleResult.fail(str(exc))\n'
            "```\n"
        )

    # 6. Self-editing a source file
    if "you are editing your own source code" in lowered:
        match = re.search(r"CURRENT FILE:\s*```python\n([\s\S]*)```", prompt)
        current = match.group(1) if match else ""
        marked = current.rstrip() + "\n\n# Touched by the mock self-editor.\n"
        return "```python\n" + marked + "```"

    # 7. Improvement suggestions
    if "reviewing your own codebase" in lowered:
        return (
            "1. modules/productivity.py — add a tool listing overdue todos.\n"
            "2. modules/web_search.py — cache Wikipedia lookups for a week.\n"
            "3. interfaces/cli.py — add a command that replays the last answer."
        )

    # 8. Summarisation of an older conversation slice
    if "compress this conversation excerpt" in lowered:
        return "Mock briefing: the user asked about timers and the weather."

    # 9. Final composition / plain conversation
    if "tool results:" in lowered:
        return "Here is the mock synthesis of those tool results, sir."
    return "Mock response, sir. The scripted brain is functioning."


class Handler(BaseHTTPRequestHandler):
    """HTTP handler implementing the three endpoints JARVIS uses."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *_: Any) -> None:  # noqa: D102 - silence the server
        return

    def _send_stream(self, text: str) -> None:
        """Send a reply as newline-delimited JSON chunks, like Ollama does."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        pieces = [piece + " " for piece in text.split(" ")]
        for piece in pieces:
            chunk = json.dumps(
                {"message": {"role": "assistant", "content": piece}, "done": False}
            ).encode() + b"\n"
            self.wfile.write(f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n")
            self.wfile.flush()
        final = json.dumps({"message": {"role": "assistant", "content": ""},
                            "done": True}).encode() + b"\n"
        self.wfile.write(f"{len(final):X}\r\n".encode() + final + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _send(self, payload: Dict[str, Any], status: int = 200) -> None:
        """Send a JSON response."""
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        """Serve ``/api/tags``."""
        if self.path.startswith("/api/tags"):
            self._send({"models": MODELS})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        """Serve ``/api/chat`` and ``/api/embeddings``."""
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")

        if self.path.startswith("/api/embeddings"):
            text = str(payload.get("prompt", ""))
            vector = [((hash(text + str(index)) % 1000) / 1000.0) for index in range(64)]
            self._send({"embedding": vector})
            return

        if self.path.startswith("/api/chat"):
            has_image = any(message.get("images") for message in payload.get("messages", []))
            if has_image:
                reply = ("Mock vision: a desktop with a terminal window and a text editor, "
                         "sir.")
            else:
                reply = scripted_reply(_last_user_content(payload))
            if payload.get("stream"):
                self._send_stream(reply)
            else:
                self._send({"message": {"role": "assistant", "content": reply}, "done": True})
            return

        self._send({"error": "not found"}, 404)


def serve(port: int = 11434) -> ThreadingHTTPServer:
    """Start the mock server in a background thread."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    port_number = int(sys.argv[1]) if len(sys.argv) > 1 else 11434
    print(f"Mock Ollama listening on http://127.0.0.1:{port_number}")
    serve(port_number)
    threading.Event().wait()
