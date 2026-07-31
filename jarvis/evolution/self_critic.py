"""
Self-Critic - JARVIS critiques his own responses to get better
Like a human reflecting: Was that good? How to improve?
"""

import json
import re
from typing import Dict, List

from ..config import config


class SelfCritic:
    def __init__(self):
        self.critique_history = []
    
    def critique(self, user_input: str, assistant_response: str, tool_results: List[Dict] = None, latency_ms: int = None) -> Dict:
        """
        Critique the response. Returns score 0-10 and improvements
        Uses LLM + heuristics
        """
        llm_critique = self._llm_critique(user_input, assistant_response, tool_results)
        heuristic_critique = self._heuristic_critique(user_input, assistant_response, tool_results, latency_ms)
        
        # Merge
        score = llm_critique.get("score", 5.0)
        if heuristic_critique.get("score") is not None:
            # Weighted average: 70% LLM, 30% heuristic
            score = score * 0.7 + heuristic_critique["score"] * 0.3
        
        issues = list(set((llm_critique.get("issues", []) + heuristic_critique.get("issues", []))))
        improvements = list(set((llm_critique.get("improvements", []) + heuristic_critique.get("improvements", []))))
        
        result = {
            "score": round(score, 1),
            "issues": issues[:5],
            "improvements": improvements[:5],
            "strengths": llm_critique.get("strengths", []),
            "should_learn": llm_critique.get("should_learn", False),
            "learning": llm_critique.get("learning", ""),
            "tool_efficiency": heuristic_critique.get("tool_efficiency", 1.0)
        }
        
        self.critique_history.append(result)
        if len(self.critique_history) > 100:
            self.critique_history = self.critique_history[-100:]
        
        return result
    
    def _heuristic_critique(self, user_input: str, assistant_response: str, tool_results: List[Dict] = None, latency_ms: int = None) -> Dict:
        issues = []
        improvements = []
        score = 7.0  # start neutral good
        
        # Check for common failures
        if not assistant_response or len(assistant_response.strip()) < 5:
            issues.append("Empty or too short response")
            score -= 3
        
        if "error" in assistant_response.lower() and "sir" not in assistant_response.lower():
            issues.append("Response contains error without graceful handling")
            score -= 1
        
        if "as an ai" in assistant_response.lower() or "as an ai language model" in assistant_response.lower():
            issues.append("Broke character - said 'as an AI'")
            score -= 2
            improvements.append("Stay in character as JARVIS, never say as an AI")
        
        # Check tool usage
        tool_efficiency = 1.0
        if tool_results is not None:
            if len(tool_results) == 0 and any(kw in user_input.lower() for kw in ["time", "weather", "search", "file", "remember"]):
                issues.append("Should have used tools for factual/time query")
                score -= 1
                improvements.append("Use tools for real-time factual info")
                tool_efficiency = 0.5
            # Check for tool errors
            error_count = sum(1 for r in tool_results if "error" in str(r).lower() or "failed" in str(r).lower())
            if error_count > 0:
                issues.append(f"{error_count} tool errors")
                score -= error_count * 0.5
                tool_efficiency = max(0.1, 1.0 - error_count*0.3)
        
        # Length appropriateness
        if len(user_input) < 20 and len(assistant_response) > 500:
            issues.append("Overly verbose for short query")
            score -= 0.5
            improvements.append("User asked short, be concise")
        
        if len(assistant_response) > 2000:
            issues.append("Very long response might be too much")
            score -= 0.3
        
        # Correctness - if user said "wrong" in next message? Can't detect here, but we can check for apology repetition
        if "sorry" in assistant_response.lower() and assistant_response.lower().count("sorry") > 2:
            issues.append("Over-apologizing")
            score -= 0.3
        
        # Latency
        if latency_ms and latency_ms > 10000:
            issues.append(f"Slow response {latency_ms}ms")
            score -= 0.2
        
        # Check if response addresses user query (simple keyword overlap)
        user_words = set(re.findall(r'\w+', user_input.lower()))
        resp_words = set(re.findall(r'\w+', assistant_response.lower()))
        overlap = len(user_words & resp_words) / max(len(user_words), 1)
        if overlap < 0.1 and len(user_words) > 3:
            issues.append("Low relevance to user query")
            score -= 0.5
        
        score = max(0.0, min(10.0, score))
        
        return {
            "score": score,
            "issues": issues,
            "improvements": improvements,
            "tool_efficiency": tool_efficiency
        }
    
    def _llm_critique(self, user_input: str, assistant_response: str, tool_results: List[Dict] = None) -> Dict:
        try:
            import requests
            import json
            
            tool_str = ""
            if tool_results:
                tool_str = f"Tools used: {json.dumps(tool_results)[:500]}"
            
            prompt = f"""You are a self-critic AI evaluating JARVIS's response. Be harsh but fair. Score 0-10.

User: "{user_input[:400]}"
JARVIS response: "{assistant_response[:800]}"
{tool_str}

Evaluate and return JSON with:
- score: 0-10 (10 perfect, 0 terrible)
- issues: array of problems (strings)
- improvements: array of how to improve next time
- strengths: what was good
- should_learn: boolean if user revealed preference or fact that should be learned
- learning: what should be learned if should_learn true

Return ONLY JSON, no other text. Example:
{{"score": 7.5, "issues": ["Too verbose"], "improvements": ["Be more concise"], "strengths": ["Used correct tool", "Friendly tone"], "should_learn": false, "learning": ""}}

JSON:"""
            
            resp = requests.post(
                f"{config.OLLAMA_HOST}/api/generate",
                json={
                    "model": config.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 400}
                },
                timeout=12
            )
            
            if resp.status_code == 200:
                result = resp.json().get("response", "{}")
                start = result.find("{")
                end = result.rfind("}") + 1
                if start != -1 and end != -1:
                    try:
                        data = json.loads(result[start:end])
                        # Validate
                        if "score" in data:
                            return data
                    except:
                        pass
        except Exception as e:
            print(f"LLM critique failed: {e}")
        
        # Fallback
        return {
            "score": 7.0,
            "issues": [],
            "improvements": [],
            "strengths": ["Response generated"],
            "should_learn": False,
            "learning": ""
        }
    
    def get_average_score(self, last_n: int = 20) -> float:
        if not self.critique_history:
            return 7.0
        recent = self.critique_history[-last_n:]
        scores = [c.get("score", 7.0) for c in recent]
        return sum(scores)/len(scores) if scores else 7.0
