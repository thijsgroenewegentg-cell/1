import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env
load_dotenv()

BASE_DIR = Path(__file__).parent.parent

class Config:
    # Ollama
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "jarvis")
    FALLBACK_MODELS: list = os.getenv("FALLBACK_MODELS", "qwen2.5:7b,llama3.1:8b,mistral-nemo,gemma2:9b").split(",")

    # Voice
    VOICE_ENABLED: bool = os.getenv("VOICE_ENABLED", "false").lower() == "true"
    WAKE_WORD: str = os.getenv("WAKE_WORD", "jarvis")
    TTS_ENGINE: str = os.getenv("TTS_ENGINE", "edge")  # edge, pyttsx3
    TTS_VOICE: str = os.getenv("TTS_VOICE", "en-GB-RyanNeural")  # Jarvis-like British male
    STT_ENGINE: str = os.getenv("STT_ENGINE", "faster-whisper")

    # Memory
    MEMORY_FILE: Path = BASE_DIR / os.getenv("MEMORY_FILE", "data/long_term_memory.json")
    CONVERSATION_FILE: Path = BASE_DIR / os.getenv("CONVERSATION_FILE", "data/conversations.json")
    WORKSPACE_DIR: Path = BASE_DIR / os.getenv("WORKSPACE_DIR", "workspace")

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

config = Config()
config.__post_init__()
