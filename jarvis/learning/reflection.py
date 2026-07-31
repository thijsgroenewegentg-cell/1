"""
Reflection Engine - JARVIS reflects on conversations to self-improve
Like human reflection before sleep
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from ..config import config


class ReflectionEngine:
    def __init__(self, reflection_path: Path = None):
        self.reflection_path = reflection_path or config.MEMORY_FILE.parent / "reflections.json"
        self.reflection_path.parent.mkdir(parents=True, exist_ok=True)
        self.reflections = self._load()
    
    def _load(self) -> List[Dict]:
        if self.reflection_path.exists():
            try:
                return json.loads(self.reflection_path.read_text())
            except:
                return []
        return []
    
    def _save(self):
        try:
            self.reflection_path.write_text(json.dumps(self.reflections, indent=2))
        except Exception as e:
            print(f"Reflection save failed: {e}")
    
    def reflect(self, conversation: List[Dict], user_profile: Dict = None) -> Dict:
        """
        Reflect on recent conversation
        Returns insights: what learned, what to improve, etc.
        """
        if len(conversation) < 4:
            return {"insights": [], "learnings": []}
        
        # Build conversation summary
        convo_text = ""
        for msg in conversation[-10:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:500]
            convo_text += f"{role}: {content}\n"
        
        insights = self._reflect_with_llm(convo_text, user_profile)
        
        if insights:
            reflection_entry = {
                "timestamp": datetime.now().isoformat(),
                "conversation_length": len(conversation),
                "insights": insights,
                "raw_conversation": convo_text[:2000]
            }
            self.reflections.append(reflection_entry)
            # Keep last 50 reflections
            if len(self.reflections) > 50:
                self.reflections = self.reflections[-50:]
            self._save()
        
        return insights
    
    def _reflect_with_llm(self, convo_text: str, user_profile: Dict = None) -> Dict:
        try:
            import requests
            import json
            
            profile_str = ""
            if user_profile:
                profile_str = f"User profile: {json.dumps(user_profile.get('facts', [])[-5:], indent=2)}"
            
            prompt = f"""You are JARVIS reflecting on a conversation with Sir. Analyze what you learned and how to improve.

Conversation:
{convo_text}

{profile_str}

Reflect and return JSON with:
- learnings: array of new facts about user ({{key, value}})
- improvements: array of strings about how you can do better
- mood: detected user mood (positive, neutral, negative, focused, etc)
- topics: main topics discussed
- satisfaction: estimated user satisfaction 0-1
- should_remember: boolean if something important should be remembered

Return ONLY JSON, no other text. Example:
{{
  "learnings": [{{"key": "project", "value": "working on AI startup"}}],
  "improvements": ["User prefers shorter answers"],
  "mood": "focused",
  "topics": ["code", "AI"],
  "satisfaction": 0.8,
  "should_remember": true
}}

JSON:"""
            
            resp = requests.post(
                f"{config.OLLAMA_HOST}/api/generate",
                json={
                    "model": config.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 500}
                },
                timeout=15
            )
            
            if resp.status_code == 200:
                result = resp.json().get("response", "{}")
                # Extract JSON
                start = result.find("{")
                end = result.rfind("}") + 1
                if start != -1 and end != -1:
                    try:
                        data = json.loads(result[start:end])
                        return data
                    except:
                        pass
        except Exception as e:
            print(f"Reflection LLM failed: {e}")
        
        # Fallback heuristic reflection
        return self._heuristic_reflection(convo_text)
    
    def _heuristic_reflection(self, convo_text: str) -> Dict:
        text_lower = convo_text.lower()
        
        # Simple mood detection
        positive_words = ["thanks", "great", "awesome", "love", "perfect", "good"]
        negative_words = ["wrong", "bad", "hate", "stupid", "useless", "annoying"]
        
        pos_count = sum(1 for w in positive_words if w in text_lower)
        neg_count = sum(1 for w in negative_words if w in text_lower)
        
        if pos_count > neg_count:
            mood = "positive"
            satisfaction = 0.8
        elif neg_count > pos_count:
            mood = "negative"
            satisfaction = 0.3
        else:
            mood = "neutral"
            satisfaction = 0.6
        
        # Topic detection
        topics = []
        topic_keywords = {
            "code": ["code", "python", "bug", "function", "program"],
            "weather": ["weather", "temperature", "rain"],
            "work": ["work", "job", "meeting", "project"],
            "personal": ["i am", "my", "i like", "i love"]
        }
        for topic, keywords in topic_keywords.items():
            if any(k in text_lower for k in keywords):
                topics.append(topic)
        
        return {
            "learnings": [],
            "improvements": [],
            "mood": mood,
            "topics": topics,
            "satisfaction": satisfaction,
            "should_remember": False
        }
    
    def get_recent_insights(self, limit: int = 5) -> List[Dict]:
        return self.reflections[-limit:]
    
    def get_learning_summary(self) -> str:
        if not self.reflections:
            return "No reflections yet, Sir. I'm still learning."
        
        recent = self.reflections[-5:]
        moods = [r.get("insights", {}).get("mood", "neutral") for r in recent if isinstance(r.get("insights"), dict)]
        avg_satisfaction = 0
        count = 0
        for r in recent:
            insights = r.get("insights", {})
            if isinstance(insights, dict) and "satisfaction" in insights:
                avg_satisfaction += insights["satisfaction"]
                count += 1
        
        avg_satisfaction = avg_satisfaction / count if count else 0.5
        
        return f"Reflections: {len(self.reflections)} sessions, recent mood: {', '.join(moods[-3:])}, satisfaction: {avg_satisfaction:.1f}/1.0"
