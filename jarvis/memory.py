import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from .config import config

class MemoryManager:
    def __init__(self, memory_file: Path = None):
        self.memory_file = memory_file or config.MEMORY_FILE
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.memory_file.exists():
            self.memory_file.write_text(json.dumps({"memories": []}, indent=2))
    
    def _load(self) -> Dict:
        try:
            data = json.loads(self.memory_file.read_text())
            # Support both old list format and new dict format
            if isinstance(data, list):
                return {"memories": data}
            return data
        except:
            return {"memories": []}
    
    def _save(self, data: Dict):
        self.memory_file.write_text(json.dumps(data, indent=2))
    
    def add_memory(self, key: str, value: str, importance: int = 5):
        data = self._load()
        mem = {
            "key": key.lower(),
            "value": value,
            "importance": importance,
            "timestamp": datetime.now().isoformat(),
            "id": datetime.now().timestamp()
        }
        # Remove existing with same key
        data["memories"] = [m for m in data.get("memories", []) if m.get("key") != key.lower()]
        data["memories"].append(mem)
        self._save(data)
        return mem
    
    def search_memory(self, query: str, limit: int = 10) -> List[Dict]:
        data = self._load()
        query = query.lower()
        results = []
        for mem in data.get("memories", []):
            score = 0
            if query in mem.get("key", "").lower():
                score += 10
            if query in mem.get("value", "").lower():
                score += 5
            # fuzzy
            for word in query.split():
                if word in mem.get("key", "").lower() or word in mem.get("value", "").lower():
                    score += 1
            if score > 0:
                results.append((score, mem))
        
        results.sort(key=lambda x: (x[0], x[1].get("importance", 0)), reverse=True)
        return [r[1] for r in results[:limit]]
    
    def get_all_memories(self) -> List[Dict]:
        data = self._load()
        return data.get("memories", [])
    
    def delete_memory(self, key: str) -> bool:
        data = self._load()
        original_len = len(data.get("memories", []))
        key_lower = key.lower()
        data["memories"] = [
            m for m in data.get("memories", [])
            if key_lower not in m.get("key", "").lower() and key_lower not in m.get("value", "").lower()
        ]
        self._save(data)
        return len(data["memories"]) < original_len


class ConversationManager:
    def __init__(self, convo_file: Path = None):
        self.convo_file = convo_file or config.CONVERSATION_FILE
        self.convo_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.convo_file.exists():
            self.convo_file.write_text(json.dumps([], indent=2))
    
    def load_history(self, limit: int = 20) -> List[Dict]:
        try:
            data = json.loads(self.convo_file.read_text())
            if isinstance(data, dict):
                return data.get("messages", [])[-limit:]
            return data[-limit:]
        except:
            return []
    
    def add_message(self, role: str, content: str):
        try:
            data = json.loads(self.convo_file.read_text())
            if not isinstance(data, list):
                data = data.get("messages", [])
        except:
            data = []
        
        data.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        # Keep last 200 messages
        if len(data) > 200:
            data = data[-200:]
        
        self.convo_file.write_text(json.dumps(data, indent=2))
    
    def clear(self):
        self.convo_file.write_text(json.dumps([], indent=2))
