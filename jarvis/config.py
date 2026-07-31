import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent

class Config:
    # Ollama
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "jarvis")
    FALLBACK_MODELS: list = os.getenv("FALLBACK_MODELS", "qwen2.5:7b,llama3.1:8b,mistral-nemo,gemma2:9b").split(",")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

    # Voice - MUST BE PIPER - 100% FREE OFFLINE, NO API KEYS
    VOICE_ENABLED: bool = os.getenv("VOICE_ENABLED", "false").lower() == "true"
    WAKE_WORD: str = os.getenv("WAKE_WORD", "jarvis")
    TTS_ENGINE: str = os.getenv("TTS_ENGINE", "piper")  # MUST BE PIPER: 100% free offline, high quality British
    TTS_VOICE: str = os.getenv("TTS_VOICE", "en_GB-alan-medium")  # Piper voice: British male, Manina premium style
    STT_ENGINE: str = os.getenv("STT_ENGINE", "faster-whisper")

    # Memory & Learning
    MEMORY_FILE: Path = BASE_DIR / os.getenv("MEMORY_FILE", "data/long_term_memory.json")
    CONVERSATION_FILE: Path = BASE_DIR / os.getenv("CONVERSATION_FILE", "data/conversations.json")
    WORKSPACE_DIR: Path = BASE_DIR / os.getenv("WORKSPACE_DIR", "workspace")
    LEARNING_ENABLED: bool = os.getenv("LEARNING_ENABLED", "true").lower() == "true"
    AUTO_MEMORY: bool = os.getenv("AUTO_MEMORY", "true").lower() == "true"
    REFLECTION_INTERVAL: int = int(os.getenv("REFLECTION_INTERVAL", "10"))
    VECTOR_STORE: Path = BASE_DIR / os.getenv("VECTOR_STORE", "data/vectors.json")
    USER_PROFILE: Path = BASE_DIR / os.getenv("USER_PROFILE", "data/user_profile.json")
    UI_MODE: str = os.getenv("UI_MODE", "minimal")
    # Evolution - Self-Improvement
    EVOLUTION_ENABLED: bool = os.getenv("EVOLUTION_ENABLED", "true").lower() == "true"
    SELF_EDIT_ENABLED: bool = os.getenv("SELF_EDIT_ENABLED", "true").lower() == "true"
    EVOLUTION_INTERVAL: int = int(os.getenv("EVOLUTION_INTERVAL", "50"))
    # Always-On Wake Word
    ALWAYS_ON_ENABLED: bool = os.getenv("ALWAYS_ON_ENABLED", "false").lower() == "true"
    WAKEWORD_ENGINE: str = os.getenv("WAKEWORD_ENGINE", "auto")  # auto, openwakeword, whisper, google
    WAKEWORD_SENSITIVITY: float = float(os.getenv("WAKEWORD_SENSITIVITY", "0.5"))
    # Proactive Agent
    PROACTIVE_ENABLED: bool = os.getenv("PROACTIVE_ENABLED", "true").lower() == "true"
    MORNING_BRIEF_HOUR: int = int(os.getenv("MORNING_BRIEF_HOUR", "8"))
    MORNING_BRIEF_MINUTE: int = int(os.getenv("MORNING_BRIEF_MINUTE", "30"))
    EVENING_BRIEF_HOUR: int = int(os.getenv("EVENING_BRIEF_HOUR", "18"))
    # Multi-Agent Team
    TEAM_ENABLED: bool = os.getenv("TEAM_ENABLED", "true").lower() == "true"

    # Productivity Hub - 100% FREE local
    CALENDAR_DIRS: str = os.getenv("CALENDAR_DIRS", "workspace/calendar,data/calendar")
    EMAIL_IMAP_HOST: str = os.getenv("EMAIL_IMAP_HOST", "")
    EMAIL_SMTP_HOST: str = os.getenv("EMAIL_SMTP_HOST", "")

    # Media & Entertainment - 100% FREE local
    MUSIC_DIRS: str = os.getenv("MUSIC_DIRS", "workspace/music,~/Music")
    PIPER_MODELS_DIR: Path = BASE_DIR / os.getenv("PIPER_MODELS_DIR", "data/piper_models")

    # Security
    ALLOW_SHELL: bool = os.getenv("ALLOW_SHELL", "true").lower() == "true"
    SAFE_MODE: bool = os.getenv("SAFE_MODE", "false").lower() == "true"

    # Web
    WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
    WEB_PORT: int = int(os.getenv("WEB_PORT", "8000"))

    # User
    USER_NAME: str = os.getenv("USER_NAME", "Sir")
    JARVIS_NAME: str = os.getenv("JARVIS_NAME", "JARVIS")

    def __post_init__(self):
        self.MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.CONVERSATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        self.VECTOR_STORE.parent.mkdir(parents=True, exist_ok=True)
        self.USER_PROFILE.parent.mkdir(parents=True, exist_ok=True)

config = Config()
config.__post_init__()
