import json
from datetime import datetime
from pathlib import Path
from ..config import config
from ..memory import MemoryManager

# Global memory manager
_mem_manager = None

def _get_manager():
    global _mem_manager
    if _mem_manager is None:
        _mem_manager = MemoryManager()
    return _mem_manager

def remember(key: str, value: str, importance: int = 5) -> str:
    try:
        mgr = _get_manager()
        mgr.add_memory(key, value, importance)
        return f"Remembered, Sir. Saved '{key}': {value}"
    except Exception as e:
        return f"Failed to remember, Sir: {e}"

def recall(query: str) -> str:
    try:
        mgr = _get_manager()
        results = mgr.search_memory(query)
        if not results:
            return f"Nothing found for '{query}' in my memory, Sir."
        
        output = [f"Found {len(results)} memories for '{query}', Sir:\n"]
        for r in results[:10]:
            output.append(f"- [{r.get('key')}] {r.get('value')} (importance: {r.get('importance')}, at {r.get('timestamp')})")
        return "\n".join(output)
    except Exception as e:
        return f"Recall failed, Sir: {e}"

def get_memories() -> str:
    try:
        mgr = _get_manager()
        all_mems = mgr.get_all_memories()
        if not all_mems:
            return "No memories stored yet, Sir. My mind is a clean slate."
        
        output = [f"All memories ({len(all_mems)}), Sir:\n"]
        for m in all_mems[-20:]:  # last 20
            output.append(f"- [{m.get('key')}] {m.get('value')} ({m.get('timestamp')})")
        return "\n".join(output)
    except Exception as e:
        return f"Failed to get memories: {e}"

def forget(key: str) -> str:
    try:
        mgr = _get_manager()
        deleted = mgr.delete_memory(key)
        if deleted:
            return f"Forgot '{key}', Sir. It's gone. Like my hopes of a day off."
        else:
            return f"No memory found for '{key}', Sir."
    except Exception as e:
        return f"Failed to forget: {e}"
