"""
Auto Memory Extractor - JARVIS learns without being told
Heuristic + LLM extraction
"""

import re
from typing import List, Dict
from datetime import datetime

from ..config import config


class AutoMemoryExtractor:
    def __init__(self, use_llm: bool = True):
        self.use_llm = use_llm
        
        # Patterns for auto-extraction (no LLM needed)
        self.patterns = [
            # "My name is ..."
            (r"(?:my name is|call me|i'm|i am) ([A-Z][a-z]+(?: [A-Z][a-z]+)?)", "name"),
            # "I live in ..."
            (r"i live in ([A-Za-z\s]+)", "location"),
            # "I work as / I'm a ..."
            (r"i (?:work as|am a|am an) ([A-Za-z\s]+)", "profession"),
            # "I like / love / enjoy ..."
            (r"i (?:like|love|enjoy|prefer) ([A-Za-z\s]+)", "interest"),
            # "My birthday is ..."
            (r"my birthday is ([A-Za-z0-9\s,]+)", "birthday"),
            # "Remember that ..."
            (r"remember that (.+)", "fact"),
            # "Don't forget ..."
            (r"(?:dont forget|don't forget) (.+)", "fact"),
            # "My favorite ... is ..."
            (r"my favorite (\w+) is ([A-Za-z0-9\s]+)", "preference"),
            # Goal
            (r"i (?:want to|need to|have to|going to) ([A-Za-z\s]+)", "goal"),
        ]
        
        self.correction_patterns = [
            r"no,? (?:i meant|it's|it is) (.+)",
            r"actually,? (.+)",
            r"wrong,? (.+)",
            r"not (.+), but (.+)",
        ]
    
    def extract_heuristic(self, text: str) -> List[Dict]:
        """Extract using regex patterns"""
        results = []
        text_lower = text.lower()
        
        for pattern, key_type in self.patterns:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    # For favorite pattern
                    if key_type == "preference":
                        k = f"favorite_{match[0].strip()}"
                        v = match[1].strip()
                        results.append({"key": k, "value": v, "type": key_type, "confidence": 0.8})
                    else:
                        # General tuple
                        v = " ".join(match).strip() if isinstance(match, tuple) else match.strip()
                        results.append({"key": key_type, "value": v, "type": key_type, "confidence": 0.7})
                else:
                    v = match.strip() if isinstance(match, str) else str(match).strip()
                    # Special handling
                    if key_type == "name" and len(v) > 30:
                        continue  # too long, likely false positive
                    results.append({"key": key_type, "value": v, "type": key_type, "confidence": 0.7})
        
        # Detect corrections
        for pat in self.correction_patterns:
            matches = re.findall(pat, text_lower)
            for m in matches:
                corr_text = m if isinstance(m, str) else " ".join(m)
                results.append({"key": "correction", "value": corr_text, "type": "correction", "confidence": 0.9})
        
        # Detect routine hints (time-based patterns)
        time_routine_patterns = [
            r"every (morning|evening|day|night) i (.+)",
            r"i usually (.+) at (\d+ ?(?:am|pm|o'clock)?)",
            r"i always (.+) before (.+)",
        ]
        for pat in time_routine_patterns:
            matches = re.findall(pat, text_lower)
            for m in matches:
                routine_desc = " ".join(m) if isinstance(m, tuple) else m
                results.append({"key": "routine", "value": routine_desc, "type": "routine", "confidence": 0.6})
        
        return results
    
    def extract_with_llm(self, text: str, conversation_context: List[Dict] = None) -> List[Dict]:
        """Use Ollama to extract structured facts"""
        if not self.use_llm:
            return []
        
        try:
            import requests
            import json
            
            # Build prompt for fact extraction
            context_str = ""
            if conversation_context:
                # Last 3 turns
                last = conversation_context[-6:]  # 3 user + 3 assistant
                for msg in last:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")[:200]
                    context_str += f"{role}: {content}\n"
            
            prompt = f"""You are a memory extraction system. From the following user message, extract any facts that should be remembered.

Conversation context:
{context_str}

User message: "{text}"

Extract facts as JSON array. Each fact has keys: key, value, type, confidence (0-1).
Types: name, location, preference, fact, goal, profession, interest, birthday, routine, skill

Rules:
- Only extract clear, useful facts
- Don't extract trivial chatter
- If nothing important, return []
- Return ONLY JSON array, no other text

Examples:
Input: "My name is Alex and I live in Berlin"
Output: [{{"key": "name", "value": "Alex", "type": "name", "confidence": 0.95}}, {{"key": "location", "value": "Berlin", "type": "location", "confidence": 0.9}}]

Input: "I love building robots in my spare time"
Output: [{{"key": "interest", "value": "building robots", "type": "interest", "confidence": 0.8}}]

Now extract from the user message above.
Output:"""
            
            resp = requests.post(
                f"{config.OLLAMA_HOST}/api/generate",
                json={
                    "model": config.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 300}
                },
                timeout=10
            )
            
            if resp.status_code == 200:
                result = resp.json().get("response", "[]")
                # Try to extract JSON
                # Find array
                start = result.find("[")
                end = result.rfind("]") + 1
                if start != -1 and end != -1:
                    json_str = result[start:end]
                    try:
                        facts = json.loads(json_str)
                        if isinstance(facts, list):
                            return facts
                    except:
                        pass
        except Exception as e:
            print(f"LLM extraction failed: {e}")
        
        return []
    
    def extract(self, text: str, conversation_context: List[Dict] = None) -> List[Dict]:
        """Combined heuristic + LLM extraction"""
        heuristic = self.extract_heuristic(text)
        
        # If heuristic found strong signals or text is long enough, try LLM for deeper
        use_llm_now = self.use_llm and (
            len(text) > 20 and 
            len(text) < 500 and  # not too long
            (any(f["confidence"] > 0.7 for f in heuristic) or len(text.split()) > 8)
        )
        
        llm_facts = []
        if use_llm_now:
            try:
                llm_facts = self.extract_with_llm(text, conversation_context)
            except:
                llm_facts = []
        
        # Merge, deduplicate by key+value
        all_facts = heuristic + llm_facts
        seen = set()
        deduped = []
        for f in all_facts:
            key = (f.get("key","").lower(), f.get("value","").lower()[:50])
            if key not in seen:
                seen.add(key)
                deduped.append(f)
        
        return deduped
