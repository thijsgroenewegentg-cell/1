"""
Learning Engine - Main orchestrator for self-learning JARVIS
Ties together vector store, profile, auto-memory, reflection
"""

import threading
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

from ..config import config
from .vector_store import VectorStore
from .user_profile import UserProfile
from .auto_memory import AutoMemoryExtractor
from .reflection import ReflectionEngine


class LearningEngine:
    def __init__(self, use_llm_extraction: bool = True):
        self.vector_store = VectorStore()
        self.user_profile = UserProfile()
        self.auto_extractor = AutoMemoryExtractor(use_llm=use_llm_extraction)
        self.reflection_engine = ReflectionEngine()
        
        self.conversation_buffer: List[Dict] = []
        self.message_count = 0
        self.reflection_interval = 10  # reflect every 10 messages
        
        print("🧠 Self-learning engine initialized, Sir.")
    
    def get_context(self, query: str, k: int = 5) -> str:
        """
        Get relevant context for a query:
        - Vector search memories
        - User profile summary
        - Recent routines
        """
        parts = []
        
        # 1. User profile summary
        profile_summary = self.user_profile.get_summary_for_prompt()
        if profile_summary:
            parts.append(profile_summary)
        
        # 2. Adaptive prompt
        adaptive = self.user_profile.get_adaptive_prompt_addition()
        if adaptive:
            parts.append(f"Adaptive behavior:\n{adaptive}")
        
        # 3. Vector search for relevant memories
        try:
            relevant = self.vector_store.search(query, k=k, threshold=0.05)
            if relevant:
                mem_text = "\n".join([f"- {r['text']} (relevance: {r['score']:.2f})" for r in relevant[:k]])
                parts.append(f"Relevant memories (semantic search):\n{mem_text}")
        except Exception as e:
            print(f"Vector search failed: {e}")
        
        # 4. Recent reflection insights
        recent_reflections = self.reflection_engine.get_recent_insights(limit=2)
        if recent_reflections:
            last = recent_reflections[-1]
            insights = last.get("insights", {})
            if isinstance(insights, dict):
                if insights.get("learnings"):
                    learnings = "\n".join([f"- {l.get('key')}: {l.get('value')}" for l in insights["learnings"][:3]])
                    parts.append(f"Recent learnings:\n{learnings}")
        
        if not parts:
            return ""
        
        return "\n\n".join(parts)
    
    def learn_from_interaction(self, user_message: str, assistant_response: str = None, feedback: str = None, conversation: List[Dict] = None):
        """
        Main learning entry - called after each interaction
        Runs in background thread to not block
        """
        def background_learn():
            try:
                # 1. Update interaction stats
                hour = datetime.now().hour
                self.user_profile.update_interaction(user_message, hour)
                
                # 2. Auto-extract memories
                facts = self.auto_extractor.extract(user_message, conversation or self.conversation_buffer)
                
                new_memories = []
                for fact in facts:
                    key = fact.get("key", "fact")
                    value = fact.get("value", "")
                    ftype = fact.get("type", "fact")
                    conf = fact.get("confidence", 0.5)
                    
                    if not value or len(value) < 2:
                        continue
                    
                    if ftype == "correction":
                        self.user_profile.add_correction("", value)
                        # Also add to vector store as important
                        self.vector_store.add(f"Correction: {value}", {"type": "correction", "confidence": conf})
                        new_memories.append(f"Correction learned: {value}")
                    
                    elif ftype == "routine":
                        self.user_profile.add_routine(value, datetime.now().strftime("%H:%M"))
                        new_memories.append(f"Routine detected: {value}")
                    
                    elif ftype in ["name", "location", "profession", "preference", "interest", "birthday", "fact", "goal"]:
                        # Add to profile
                        if ftype in ["name", "location", "profession", "birthday"]:
                            self.user_profile.add_fact(key, value, conf)
                        elif ftype in ["interest", "preference"]:
                            # Add to interests
                            prefs = self.user_profile.profile["preferences"]
                            interests = prefs.get("topics_of_interest", [])
                            if value not in interests and len(value) < 50:
                                interests.append(value[:50])
                                prefs["topics_of_interest"] = interests[-20:]  # keep 20
                                self.user_profile._save()
                        
                        if ftype == "goal":
                            self.user_profile.add_goal(value)
                        
                        # Add to vector store for semantic recall
                        text_for_vector = f"{key}: {value}" if key != value else value
                        self.vector_store.add(text_for_vector, {"type": ftype, "confidence": conf, "source": "auto"})
                        new_memories.append(f"{key}: {value}")
                
                if new_memories:
                    print(f"🧠 Learned {len(new_memories)} new things, Sir: {new_memories[:3]}")
                
                # 3. Update conversation buffer
                self.conversation_buffer.append({"role": "user", "content": user_message})
                if assistant_response:
                    self.conversation_buffer.append({"role": "assistant", "content": assistant_response})
                
                # Keep buffer to last 20
                if len(self.conversation_buffer) > 20:
                    self.conversation_buffer = self.conversation_buffer[-20:]
                
                self.message_count += 1
                
                # 4. Handle feedback
                if feedback:
                    self.user_profile.update_satisfaction(feedback)
                
                # 5. Periodic reflection
                if self.message_count % self.reflection_interval == 0:
                    self.reflect()
                
                # 6. Learn communication style every 20 messages
                if self.message_count % 20 == 0:
                    user_msgs = [m["content"] for m in self.conversation_buffer if m["role"]=="user"]
                    if user_msgs:
                        self.user_profile.learn_communication_style(user_msgs)
                
            except Exception as e:
                print(f"Background learning failed: {e}")
                import traceback
                traceback.print_exc()
        
        # Run in background
        thread = threading.Thread(target=background_learn, daemon=True)
        thread.start()
    
    def reflect(self) -> Dict:
        """Trigger reflection"""
        try:
            insights = self.reflection_engine.reflect(self.conversation_buffer, self.user_profile.get())
            print(f"🪞 Reflection done: mood={insights.get('mood')}, satisfaction={insights.get('satisfaction', 'N/A')}")
            
            # Apply learnings from reflection
            if isinstance(insights, dict):
                for learning in insights.get("learnings", []):
                    k = learning.get("key", "fact")
                    v = learning.get("value", "")
                    if v:
                        self.user_profile.add_fact(k, v, 0.7, "reflection")
                        self.vector_store.add(f"{k}: {v}", {"type": "reflection"})
                
                # Update satisfaction
                if "satisfaction" in insights:
                    # Don't directly set, but it's used for adaptive prompt via reflection history
                
                    pass
                
                # Improvements -> could log or adapt
                for imp in insights.get("improvements", []):
                    print(f"💡 Improvement insight: {imp}")
            
            return insights
        except Exception as e:
            print(f"Reflection failed: {e}")
            return {}
    
    def add_feedback(self, message_id: str = None, feedback: str = "positive", message_text: str = None):
        """User gives thumbs up/down"""
        self.user_profile.update_satisfaction(feedback)
        
        # If feedback is negative and we have message text, try to understand what went wrong
        if feedback == "negative" and message_text:
            # Add as correction context
            self.vector_store.add(f"User disliked response: {message_text[:200]}", {"type": "negative_feedback"})
        
        print(f"Feedback received, Sir: {feedback}")
    
    def get_profile(self) -> Dict:
        return self.user_profile.get()
    
    def get_learnings(self, limit: int = 20) -> List[Dict]:
        return self.vector_store.get_all(limit=limit)
    
    def get_insights(self) -> Dict:
        return {
            "profile": self.user_profile.get(),
            "recent_reflections": self.reflection_engine.get_recent_insights(limit=5),
            "vector_count": len(self.vector_store.vectors),
            "message_count": self.message_count,
            "learning_summary": self.reflection_engine.get_learning_summary()
        }
    
    def clear_all_learnings(self):
        self.vector_store.clear()
        self.user_profile.clear()
        self.reflection_engine.reflections = []
        self.reflection_engine._save()
        print("All learnings cleared, Sir. Fresh start.")
