# /scripts/list_settings.py
"""Generate ``docs/CONFIGURATION.md`` — every setting, default and effect.

Run it after changing ``DEFAULT_CONFIG``::

    python scripts/list_settings.py

The defaults come from :data:`core.config.DEFAULT_CONFIG` itself, so they
cannot drift. The one-line explanations live in :data:`DESCRIPTIONS` below,
and the script fails if a setting has none — a knob nobody can explain is a
knob nobody can use. ``tests/test_config.py`` runs the same check.
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any, Dict, Iterator, List, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.config import DEFAULT_CONFIG, KEY_ALIASES

#: Order the sections appear in, most useful first.
SECTION_ORDER: Tuple[str, ...] = (
    "user", "assistant", "llm", "memory", "voice", "modules", "security",
    "productivity", "knowledge", "vision", "blender", "web", "web_ui",
    "email", "calendar", "self_improve", "paths", "database", "logging",
)

#: What each section is for.
SECTION_BLURBS: Dict[str, str] = {
    "user": "Who you are, so JARVIS addresses you properly and knows where you are.",
    "assistant": "Name, language and manner.",
    "llm": "The local model: which one, where it runs and how it is sampled.",
    "memory": "Short-term conversation window and the long-term vector store.",
    "voice": "Wake word, speech recognition, speech synthesis and voice activity detection.",
    "modules": "Switch whole capabilities off. Nothing else breaks when you do.",
    "security": "What JARVIS may run and where it may write.",
    "productivity": "Reminders, timers and the recurring scheduler.",
    "knowledge": "The private document index used for grounded answers.",
    "vision": "Looking at your screen and at image files.",
    "blender": "Driving Blender's command line for rendering and 3D work.",
    "web": "Web search, scraping and news.",
    "web_ui": "The phone/LAN chat interface.",
    "email": "IMAP/SMTP mail. The password is never stored here.",
    "calendar": "Local .ics files and subscribed calendar URLs.",
    "self_improve": "JARVIS editing its own source, and writing new skills.",
    "paths": "Where everything is stored. Relative paths resolve next to config.yaml.",
    "database": "The SQLite file holding todos, reminders, notes and history.",
    "logging": "Console and file logging.",
}

#: One line per setting: what it does, and what changing it achieves.
DESCRIPTIONS: Dict[str, str] = {
    # -- user ---------------------------------------------------------------
    "user.name": "What JARVIS calls you in conversation.",
    "user.title": "The honorific used in replies — 'sir', 'ma'am', 'boss', or empty for none.",
    "user.location": "Default place for weather and news. 'auto' geolocates by IP.",
    "user.units": "'metric' or 'imperial', used by weather and conversions.",
    # -- assistant ----------------------------------------------------------
    "assistant.name": "The assistant's own name, used in the banner and prompts.",
    "assistant.language": "Reply language (21 supported), e.g. 'en', 'nl', 'fr', 'ja'.",
    "assistant.personality": "Overall manner: 'witty', 'formal', 'concise' or 'friendly'.",
    "assistant.sarcasm": "0.0 for straight-faced, 1.0 for insufferable. Default is dry.",
    "assistant.greet_on_start": "Greet you when JARVIS starts.",
    "assistant.proactive": "Offer a follow-up suggestion when one is obviously useful.",
    # -- llm ----------------------------------------------------------------
    "llm.provider": "Accepted for compatibility; JARVIS only ever talks to Ollama.",
    "llm.host": "Where Ollama is listening. Point it at another machine on your LAN if you like.",
    "llm.model": "The model that answers. llama3.2, mistral, qwen2.5, phi3 …",
    "llm.fallback_models": "Tried in order when the configured model is not installed.",
    "llm.temperature": "Sampling randomness: lower is steadier, higher is more inventive.",
    "llm.top_p": "Nucleus sampling cut-off.",
    "llm.num_ctx": "Context window in tokens. Larger remembers more and costs more memory.",
    "llm.max_tokens": "Longest single reply, in tokens.",
    "llm.timeout": "Seconds to wait for the model before giving up on a request.",
    "llm.keep_alive": "How long Ollama keeps the model in RAM between turns ('10m', '1h', '0').",
    "llm.router_model": (
        "A smaller model used only for intent classification. Blank reuses the main "
        "one."
    ),
    "llm.stream": "Stream the reply token by token, so speech can start before it finishes.",
    "llm.retries": "Retry attempts when a request fails.",
    "llm.retry_backoff": "Seconds multiplied per retry.",
    "llm.warm_up": "Load the model at start-up so the first answer is not slow.",
    # -- memory -------------------------------------------------------------
    "memory.enabled": "Master switch for all memory.",
    "memory.short_term_limit": "Exchanges kept verbatim in RAM for immediate context.",
    "memory.long_term": "Keep durable facts in the vector store for later recall.",
    "memory.path": "Where the ChromaDB (or JSON fallback) vector store lives.",
    "memory.collection": "Collection name inside the vector store.",
    "memory.embedding_model": "Ollama model used to embed memories.",
    "memory.local_embedding_model": (
        "sentence-transformers model to embed with instead of Ollama, "
        "e.g. 'all-MiniLM-L6-v2'. Blank uses Ollama."
    ),
    "memory.top_k": "How many memories to retrieve per turn.",
    "memory.min_relevance": "Similarity floor: below this a memory is not worth injecting.",
    "memory.autosave": "Flush the JSON vector store after each turn, so a crash loses nothing.",
    "memory.auto_extract_facts": "Mine durable facts out of conversation in the background.",
    "memory.summarize": "Compress older turns into a running summary instead of dropping them.",
    "memory.summary_trigger": "Exchanges before summarisation kicks in.",
    "memory.context_char_budget": "Characters of history allowed into a prompt.",
    # -- database -----------------------------------------------------------
    "database.path": "SQLite file for todos, reminders, notes, history and the file journal.",
    # -- productivity -------------------------------------------------------
    "productivity.catch_up_on_start": "Report reminders that came due while JARVIS was off.",
    "productivity.scheduler_interval": "Seconds between checks for due reminders and jobs.",
    "productivity.quiet_hours": (
        "Window when JARVIS stays silent, e.g. '23:00-07:00'. Blank disables."
    ),
    "productivity.use_apscheduler": (
        "Use APScheduler when installed; false forces the built-in loop."
    ),
    # -- voice --------------------------------------------------------------
    "voice.enabled": "Whether the voice pipeline starts at all.",
    "voice.wake_word": (
        "The word that wakes JARVIS; mishearings of 'jarvis' count too. Leave it "
        "blank to need no wake word at all."
    ),
    "voice.engine": (
        "Wake-word engine: 'auto', 'porcupine', 'openwakeword', 'whisper', or "
        "'none' to switch the wake word off and answer anything you say."
    ),
    "voice.porcupine_access_key": "Free Picovoice key for the low-power detector. Optional.",
    "voice.porcupine_keyword": "Which built-in Porcupine keyword to listen for.",
    "voice.sensitivity": "Wake-word sensitivity: higher wakes more eagerly and misfires more.",
    "voice.interrupt": "Let a new utterance cut JARVIS off mid-sentence.",
    "voice.chime": "Play a short sound when the wake word fires.",
    "voice.stream_speech": "Speak sentence by sentence while the answer is still being written.",
    "voice.conversation_mode": "Follow-up questions need no wake word.",
    "voice.conversation_timeout": "Seconds of silence before the wake word is needed again.",
    "voice.openwakeword.model": "openWakeWord model name, e.g. 'hey_jarvis'.",
    "voice.openwakeword.threshold": "Detection threshold for openWakeWord.",
    "voice.openwakeword.inference_framework": "'onnx' or 'tflite'.",
    "voice.stt.model": "Whisper size: tiny, base, small, medium, large — speed against accuracy.",
    "voice.stt.device": "'auto', 'cpu' or 'cuda' for transcription.",
    "voice.stt.compute_type": "Precision, e.g. 'int8' on CPU or 'float16' on a GPU.",
    "voice.stt.language": "Force a transcription language, or 'auto' to detect.",
    "voice.stt.beam_size": "Whisper beam search width. 1 is fastest.",
    "voice.stt.vad_filter": "Let Whisper drop silence before transcribing.",
    "voice.tts.voice": "Edge-TTS voice name. Blank picks one to match the language.",
    "voice.tts.rate": "Speaking rate, e.g. '+8%' or '-10%'.",
    "voice.tts.volume": "Speech volume offset, e.g. '+0%'.",
    "voice.tts.pitch": "Pitch offset, e.g. '+0Hz'.",
    "voice.tts.cache": "Cache synthesised audio so repeated phrases are instant.",
    "voice.vad.sample_rate": "Microphone sample rate in hertz.",
    "voice.vad.frame_ms": "Audio frame size for voice detection.",
    "voice.vad.energy_threshold": (
        "Loudness above which audio counts as speech. Raise it in a noisy room."
    ),
    "voice.vad.silence_ms": "Silence that ends an utterance.",
    "voice.vad.min_speech_ms": "Shorter bursts than this are treated as noise.",
    "voice.vad.max_command_seconds": "Longest single spoken command.",
    "voice.vad.listen_timeout": "Seconds to wait for you to start speaking after the wake word.",
    # -- modules ------------------------------------------------------------
    **{
        f"modules.{name}": f"Load the {name.replace('_', ' ')} module."
        for name in DEFAULT_CONFIG["modules"]
    },
    # -- knowledge ----------------------------------------------------------
    "knowledge.paths": "Folders indexed into the private knowledge base.",
    "knowledge.store_path": "Where the document index is stored.",
    "knowledge.collection": "Collection name for indexed documents.",
    "knowledge.chunk_size": "Characters per indexed chunk.",
    "knowledge.chunk_overlap": "Overlap between chunks, so sentences are not cut in half.",
    "knowledge.max_file_mb": "Skip documents larger than this.",
    "knowledge.max_files": "Ceiling on how many files one indexing run will read.",
    "knowledge.top_k": "Passages retrieved per question.",
    "knowledge.min_relevance": "Similarity floor for a passage to be quoted.",
    "knowledge.auto_index_on_start": "Re-index the configured folders every time JARVIS starts.",
    # -- vision -------------------------------------------------------------
    "vision.model": "Ollama vision model, e.g. 'llava'.",
    "vision.fallback_models": "Tried in order when the configured vision model is missing.",
    "vision.max_tokens": "Longest description of an image.",
    "vision.temperature": "Sampling temperature for image descriptions.",
    "vision.screenshot_dir": "Where screenshots are written. Blank uses paths.screenshots.",
    "vision.keep_screenshots": "How many screenshots to keep before pruning the oldest.",
    "vision.max_pixels": "Images larger than this are shrunk before the model sees them.",
    "vision.timeout": "Seconds to wait for the vision model.",
    # -- blender ------------------------------------------------------------
    "blender.executable": (
        "Full path to the Blender binary. Blank searches PATH and the usual places."
    ),
    "blender.output_dir": "Where renders and exports are written.",
    "blender.engine": (
        "Default render engine: 'cycles', 'eevee', 'workbench', or blank for the "
        "file's own."
    ),
    "blender.samples": "Override the scene's sample count. 0 leaves it alone.",
    "blender.timeout": "Seconds a Blender Python script may run.",
    "blender.render_timeout": "Seconds a render may take before it is stopped.",
    "blender.memory_mb": "Memory ceiling for Blender. 0 means none — renders are memory-hungry.",
    "blender.allow_scripts": "Allow running bpy scripts at all.",
    "blender.allow_bpy_module": (
        "Accept 'pip install bpy' as a runtime when the application is absent."
    ),
    # -- web ----------------------------------------------------------------
    "web.max_results": "Search results fetched per query.",
    "web.timeout": "Seconds before a web request is abandoned.",
    "web.scrape_chars": "Characters kept when reading a page.",
    "web.user_agent": "User-Agent sent when scraping.",
    "web.news_feeds": "RSS feeds used for the news headlines.",
    "web.cache_ttl": "Seconds a web result stays cached.",
    "web.cache_path": "SQLite file holding the web cache.",
    # -- web_ui -------------------------------------------------------------
    "web_ui.enabled": "Start the phone/LAN interface automatically.",
    "web_ui.host": "Interface to bind. '0.0.0.0' makes it reachable from your phone.",
    "web_ui.port": "Port for the web interface.",
    "web_ui.token": "Shared secret. Blank generates one into data/web_token.txt.",
    "web_ui.require_token": "Refuse requests without the token. Leave this on.",
    "web_ui.rate_limit_per_minute": "Requests allowed per client per minute.",
    "web_ui.allow_tts": "Let the browser ask JARVIS to speak a reply aloud.",
    "web_ui.max_audio_mb": "Largest hold-to-talk recording accepted.",
    "web_ui.title": "Title shown in the browser and on the home screen.",
    # -- email --------------------------------------------------------------
    "email.enabled": "Turn the mail features on.",
    "email.imap_host": "IMAP server for reading mail.",
    "email.imap_port": "IMAP port, usually 993.",
    "email.smtp_host": "SMTP server for sending mail.",
    "email.smtp_port": "SMTP port, usually 587.",
    "email.user": "Your mail address.",
    "email.password_env": (
        "Environment variable holding the password. It is never stored in config."
    ),
    "email.mailbox": "Mailbox to read, usually INBOX.",
    "email.fetch_limit": "Messages fetched per check.",
    "email.allow_send": "Permit sending mail, not merely reading it.",
    # -- calendar -----------------------------------------------------------
    "calendar.enabled": "Turn the calendar features on.",
    "calendar.files": "Local .ics files to read.",
    "calendar.urls": "Subscribed calendar URLs (Google/Outlook 'secret address in iCal format').",
    "calendar.local_file": "Where events you create through JARVIS are written.",
    "calendar.look_ahead_days": "Default horizon for 'what's coming up'.",
    # -- self_improve -------------------------------------------------------
    "self_improve.root": "The source tree JARVIS may inspect. Blank means where it is installed.",
    "self_improve.enabled": "Master switch for self-modification.",
    "self_improve.allow_code_edit": "Permit rewriting its own source files.",
    "self_improve.allow_plugin_install": "Permit writing new skills into plugins/.",
    "self_improve.review_plugins": "New skills wait in plugins/pending until you approve them.",
    "self_improve.allow_pip_install": "Permit installing Python packages. Off by default.",
    "self_improve.run_tests_after_edit": "Every self-edit must survive the test suite.",
    "self_improve.test_command": "The suite run after a self-edit.",
    "self_improve.test_timeout": "Seconds that suite may take.",
    "self_improve.git_commit": "Commit each accepted change locally. Never pushes.",
    "self_improve.auto_reload": "Reload a module in place after editing it, without a restart.",
    "self_improve.plugins_dir": "Where plugins live.",
    "self_improve.repos_dir": "Where cloned repositories are kept.",
    "self_improve.backup_dir": "Where pre-edit backups are kept.",
    "self_improve.keep_backups": "How many backups to retain.",
    "self_improve.max_file_bytes": "Largest file JARVIS will rewrite in one go.",
    "self_improve.max_search_results": "GitHub search results per query.",
    "self_improve.github_token_env": "Environment variable holding a GitHub token. Optional.",
    "self_improve.protected": "Files JARVIS refuses to rewrite, whatever it is asked.",
    # -- security -----------------------------------------------------------
    "security.confirm_dangerous": "Ask before anything destructive. Off means it acts unasked.",
    "security.allow_shell": "Permit shell commands at all.",
    "security.shell_timeout": "Seconds a shell command may run.",
    "security.sandbox_memory_mb": "Memory ceiling for sandboxed code (POSIX).",
    "security.sandbox_timeout": "Seconds sandboxed code may run.",
    "security.audit_log": (
        "Where the trail of permitted, refused and confirmed actions is kept. "
        "Blank keeps it in memory only, so it is lost at shutdown."
    ),
    "security.audit_limit": "How many audit entries to hold in memory.",
    "security.blocked_patterns": "Extra regular expressions to refuse outright.",
    "security.shell_blacklist": "Extra commands to refuse, matched as literal text.",
    "security.allowed_roots": "Folders JARVIS may write in. Elsewhere it asks first.",
    # -- paths --------------------------------------------------------------
    "paths.data": "Root for everything JARVIS stores.",
    "paths.logs": "Log directory.",
    "paths.notes": "Where notes are written as Markdown.",
    "paths.code": "Where generated code is saved.",
    "paths.screenshots": "Where screenshots are kept.",
    "paths.tts_cache": "Cached speech audio.",
    "paths.knowledge": "Knowledge-base storage.",
    "paths.backups": "Backup archives.",
    "paths.renders": "Blender output, when set separately.",
    # -- logging ------------------------------------------------------------
    "logging.level": "DEBUG, INFO, WARNING or ERROR.",
    "logging.file": "Log file path. Blank logs only to the console.",
    "logging.max_bytes": "Rotate the log once it reaches this size.",
    "logging.backups": "How many rotated logs to keep.",
    "logging.color": "Colour the console output.",
    "logging.quiet_libraries": "Silence chatty third-party loggers.",
}


def walk(node: Dict[str, Any], prefix: str = "") -> Iterator[Tuple[str, Any]]:
    """Yield every leaf setting as ``(dotted key, default)``.

    Args:
        node: A configuration mapping.
        prefix: Dotted prefix accumulated so far.

    Yields:
        Each leaf setting in declaration order.
    """
    for key, value in node.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and value and all(isinstance(k, str) for k in value):
            yield from walk(value, dotted)
        else:
            yield dotted, value


def undocumented() -> List[str]:
    """Settings with no entry in :data:`DESCRIPTIONS`.

    Returns:
        The dotted keys that need writing up.
    """
    return [key for key, _ in walk(DEFAULT_CONFIG) if key not in DESCRIPTIONS]


def render_default(value: Any) -> str:
    """Format a default for the table.

    Args:
        value: The default value.

    Returns:
        A short, code-formatted representation.
    """
    if value == "":
        return "*(blank)*"
    if isinstance(value, bool):
        return f"`{str(value).lower()}`"
    if isinstance(value, list):
        if not value:
            return "`[]`"

        rendered = ", ".join(json.dumps(item) for item in value[:3])
        return f"`[{rendered}{', …' if len(value) > 3 else ''}]`"
    return f"`{json.dumps(value)}`"


def build() -> str:
    """Render the whole document.

    Returns:
        The Markdown source of ``docs/CONFIGURATION.md``.
    """
    settings = list(walk(DEFAULT_CONFIG))
    sections: Dict[str, List[Tuple[str, Any]]] = {}
    for dotted, default in settings:
        sections.setdefault(dotted.split(".")[0], []).append((dotted, default))
    ordered = [name for name in SECTION_ORDER if name in sections]
    ordered += [name for name in sections if name not in SECTION_ORDER]

    lines: List[str] = [
        "# /docs/CONFIGURATION.md",
        "",
        "# Every setting in JARVIS",
        "",
        f"{len(settings)} settings, all in `config.yaml`, all optional — every one has a",
        "working default. Generated by `python scripts/list_settings.py` straight from",
        "`core.config.DEFAULT_CONFIG`, so the defaults below are the real ones.",
        "",
        "Three ways to change any of them:",
        "",
        "```bash",
        "# 1. edit config.yaml, then restart",
        "# 2. per run, from the environment",
        "JARVIS_LLM__MODEL=mistral python main.py",
        "# 3. ask JARVIS, for the settings it exposes as tools",
        "```",
        "",
        "## Contents",
        "",
    ]
    for name in ordered:
        lines.append(f"- [`{name}`](#{name}) — {SECTION_BLURBS.get(name, '')}")
    lines.append("")

    for name in ordered:
        lines += [f"## {name}", ""]
        blurb = SECTION_BLURBS.get(name)
        if blurb:
            lines += [blurb, ""]
        lines += ["| Setting | Default | What it does |", "|---|---|---|"]
        for dotted, default in sections[name]:
            leaf = dotted[len(name) + 1:]
            description = DESCRIPTIONS.get(dotted, "**(undocumented)**")
            lines.append(f"| `{leaf}` | {render_default(default)} | {description} |")
        lines.append("")

    lines += [
        "## Alternative spellings",
        "",
        "Write it the other way and JARVIS still understands. Where both appear, the",
        "canonical key wins.",
        "",
        "| You write | It means |",
        "|---|---|",
    ]
    for alias, canonical in sorted(KEY_ALIASES.items()):
        if alias != canonical:
            lines.append(f"| `{alias}` | `{canonical}` |")
    lines += [
        "",
        "`quiet_hours:` may also be written as a block with `enabled`, `start` and",
        "`end`, and it is folded into `productivity.quiet_hours`.",
        "",
        "## Environment overrides",
        "",
        "Any setting can be overridden for one run. Both spellings work — the double",
        "underscore is the documented form, and the single underscore is resolved",
        "against the settings that actually exist:",
        "",
        "```bash",
        "JARVIS_LLM__MODEL=mistral python main.py",
        "JARVIS_VOICE__ENABLED=false python main.py --cli",
        "JARVIS_LOGGING__LEVEL=DEBUG python main.py --say 'system stats'",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    """Write the document, refusing to leave a setting unexplained.

    Returns:
        A process exit code.
    """
    missing = undocumented()
    if missing:
        print("These settings have no description in scripts/list_settings.py:")
        for key in missing:
            print("   ", key)
        return 1

    root = pathlib.Path(__file__).resolve().parent.parent
    target = root / "docs" / "CONFIGURATION.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build() + "\n", encoding="utf-8")
    print(f"{target.relative_to(root)}: {len(list(walk(DEFAULT_CONFIG)))} settings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
