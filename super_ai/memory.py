import json
import time
from pathlib import Path
from typing import List, Dict, Any


class Memory:
    """Persistent and episodic memory for the agent."""

    def __init__(self, storage_path: str = ".agent_memory.json"):
        self.storage_path = Path(storage_path)
        self.episodic: List[Dict[str, Any]] = []
        self.preferences: Dict[str, Any] = {}
        self.load()

    def load(self):
        if self.storage_path.exists():
            try:
                data = json.loads(self.storage_path.read_text())
                self.episodic = data.get("episodic", [])
                self.preferences = data.get("preferences", {})
            except Exception:
                pass

    def save(self):
        self.storage_path.write_text(json.dumps({
            "episodic": self.episodic[-500:],  # cap memory
            "preferences": self.preferences,
        }, indent=2))

    def add(self, event_type: str, content: Any, outcome: str = "unknown"):
        entry = {
            "timestamp": time.time(),
            "type": event_type,
            "content": content,
            "outcome": outcome,
        }
        self.episodic.append(entry)
        self.save()

    def recall(self, event_type: str = None, n: int = 5) -> List[Dict]:
        results = self.episodic
        if event_type:
            results = [r for r in results if r.get("type") == event_type]
        return results[-n:]

    def update_preference(self, key: str, value: Any):
        self.preferences[key] = value
        self.save()

    def get_preference(self, key: str, default=None):
        return self.preferences.get(key, default)
