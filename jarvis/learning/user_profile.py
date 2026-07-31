"""
User Profile - JARVIS learns who you are
Self-updating JSON that builds over time
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

from ..config import config


DEFAULT_PROFILE = {
    "name": "Sir",
    "preferred_name": None,
    "created_at": None,
    "last_updated": None,
    "preferences": {
        "communication_style": "concise",  # concise, detailed, casual
        "humor_level": "medium",
        "formality": "balanced",
        "topics_of_interest": [],
        "disliked_topics": [],
        "language": "en",
        "timezone": None,
        "location": None
    },
    "facts": [],  # list of {key, value, confidence, timestamp}
    "routines": [],  # list of {pattern, time, frequency, last_seen}
    "goals": [],
    "skills": [],  # learned skills
    "corrections": [],  # user corrections to remember
    "interaction_stats": {
        "total_messages": 0,
        "avg_message_length": 0,
        "common_hours": {},  # hour -> count
        "common_topics": {},
        "satisfaction_score": 0.5  # 0-1 based on feedback
    },
    "adaptive_prompt": ""  # generated prompt addition
}


class UserProfile:
    def __init__(self, profile_path: Path = None):
        self.profile_path = profile_path or config.MEMORY_FILE.parent / "user_profile.json"
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile = self._load()
    
    def _load(self) -> Dict:
        if self.profile_path.exists():
            try:
                data = json.loads(self.profile_path.read_text())
                # Merge with defaults
                merged = DEFAULT_PROFILE.copy()
                for k,v in data.items():
                    if isinstance(v, dict) and isinstance(merged.get(k), dict):
                        merged[k] = {**merged[k], **v}
                    else:
                        merged[k] = v
                return merged
            except:
                pass
        # New profile
        p = DEFAULT_PROFILE.copy()
        p["created_at"] = datetime.now().isoformat()
        p["last_updated"] = datetime.now().isoformat()
        p["facts"] = []
        p["routines"] = []
        p["goals"] = []
        p["skills"] = []
        p["corrections"] = []
        return p
    
    def _save(self):
        self.profile["last_updated"] = datetime.now().isoformat()
        try:
            self.profile_path.write_text(json.dumps(self.profile, indent=2))
        except Exception as e:
            print(f"Profile save failed: {e}")
    
    def get(self) -> Dict:
        return self.profile
    
    def get_summary_for_prompt(self) -> str:
        """Generate a concise summary to inject into system prompt"""
        p = self.profile
        parts = []
        
        if p.get("preferred_name"):
            parts.append(f"User prefers to be called {p['preferred_name']}")
        elif p.get("name") and p["name"] != "Sir":
            parts.append(f"User name is {p['name']}")
        
        prefs = p.get("preferences", {})
        if prefs.get("communication_style"):
            parts.append(f"Communication style: {prefs['communication_style']}")
        if prefs.get("topics_of_interest"):
            parts.append(f"Interests: {', '.join(prefs['topics_of_interest'][:5])}")
        if prefs.get("location"):
            parts.append(f"Location: {prefs['location']}")
        
        # Top facts
        facts = p.get("facts", [])[-10:]  # last 10
        for f in facts:
            if f.get("value"):
                parts.append(f"{f.get('key')}: {f.get('value')}")
        
        # Recent corrections
        corrections = p.get("corrections", [])[-3:]
        for c in corrections:
            parts.append(f"Correction to remember: {c.get('text')}")
        
        # Routines
        routines = p.get("routines", [])[:3]
        for r in routines:
            if r.get("frequency",0) > 2:
                parts.append(f"Routine: {r.get('pattern')} around {r.get('time')}")
        
        if not parts:
            return ""
        
        return "User context (learned):\n" + "\n".join([f"- {x}" for x in parts])
    
    def update_interaction(self, user_message: str, hour: int = None):
        if hour is None:
            hour = datetime.now().hour
        
        stats = self.profile["interaction_stats"]
        stats["total_messages"] += 1
        # hour stats
        hour_key = str(hour)
        stats["common_hours"][hour_key] = stats["common_hours"].get(hour_key, 0) + 1
        
        # Topic detection (simple keywords)
        topics = ["code", "weather", "time", "music", "movie", "work", "study", "game", "food", "travel", "ai", "project"]
        msg_lower = user_message.lower()
        for topic in topics:
            if topic in msg_lower:
                stats["common_topics"][topic] = stats["common_topics"].get(topic, 0) + 1
        
        # Avg length
        total = stats["total_messages"]
        old_avg = stats["avg_message_length"]
        stats["avg_message_length"] = (old_avg * (total-1) + len(user_message)) / total
        
        self._save()
    
    def add_fact(self, key: str, value: str, confidence: float = 0.8, source: str = "auto"):
        # Deduplicate
        existing = [f for f in self.profile["facts"] if f.get("key")==key.lower()]
        if existing:
            # Update
            for f in self.profile["facts"]:
                if f.get("key")==key.lower():
                    f["value"] = value
                    f["confidence"] = max(f["confidence"], confidence)
                    f["timestamp"] = datetime.now().isoformat()
        else:
            self.profile["facts"].append({
                "key": key.lower(),
                "value": value,
                "confidence": confidence,
                "source": source,
                "timestamp": datetime.now().isoformat()
            })
        self._save()
    
    def add_preference(self, key: str, value: Any):
        self.profile["preferences"][key] = value
        self._save()
    
    def add_routine(self, pattern: str, time_hint: str = None):
        # Check if similar routine exists
        for r in self.profile["routines"]:
            if r["pattern"] == pattern:
                r["frequency"] += 1
                r["last_seen"] = datetime.now().isoformat()
                if time_hint:
                    r["time"] = time_hint
                self._save()
                return
        
        self.profile["routines"].append({
            "pattern": pattern,
            "time": time_hint or datetime.now().strftime("%H:%M"),
            "frequency": 1,
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat()
        })
        self._save()
    
    def add_correction(self, original: str, correction: str):
        self.profile["corrections"].append({
            "original": original,
            "text": correction,
            "timestamp": datetime.now().isoformat()
        })
        # Keep last 20
        if len(self.profile["corrections"]) > 20:
            self.profile["corrections"] = self.profile["corrections"][-20:]
        self._save()
    
    def add_goal(self, goal: str):
        self.profile["goals"].append({
            "goal": goal,
            "timestamp": datetime.now().isoformat(),
            "completed": False
        })
        self._save()
    
    def learn_communication_style(self, user_messages: List[str]):
        # Simple heuristic
        avg_len = sum(len(m) for m in user_messages) / max(len(user_messages),1)
        if avg_len < 30:
            style = "concise"
        elif avg_len > 100:
            style = "detailed"
        else:
            style = "balanced"
        
        self.profile["preferences"]["communication_style"] = style
        self._save()
    
    def update_satisfaction(self, feedback: str):
        # feedback: "positive" or "negative" or score 0-1
        stats = self.profile["interaction_stats"]
        current = stats.get("satisfaction_score", 0.5)
        
        if feedback == "positive":
            delta = 0.05
        elif feedback == "negative":
            delta = -0.1
        else:
            try:
                delta = float(feedback) - current
            except:
                delta = 0
        
        new_score = max(0.0, min(1.0, current + delta*0.3))  # smoothing
        stats["satisfaction_score"] = new_score
        self._save()
    
    def get_adaptive_prompt_addition(self) -> str:
        """Generate adaptive system prompt addition based on profile"""
        style = self.profile["preferences"].get("communication_style", "concise")
        satisfaction = self.profile["interaction_stats"].get("satisfaction_score", 0.5)
        
        additions = []
        
        if style == "concise":
            additions.append("User prefers concise, to-the-point answers. Avoid verbosity.")
        elif style == "detailed":
            additions.append("User prefers detailed, thorough explanations. Be comprehensive.")
        
        if satisfaction < 0.4:
            additions.append("User satisfaction has been low recently. Be extra helpful, proactive, and ask clarifying questions.")
        
        # If user has many corrections, be more careful
        if len(self.profile["corrections"]) > 5:
            additions.append("User has corrected you several times. Be careful, confirm before assuming, and note corrections explicitly.")
        
        return "\n".join(additions)

    def clear(self):
        self.profile = DEFAULT_PROFILE.copy()
        self.profile["created_at"] = datetime.now().isoformat()
        self.profile["facts"] = []
        self.profile["routines"] = []
        self._save()
