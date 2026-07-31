"""
Performance Tracker - JARVIS measures himself
Tracks latency, tool success, satisfaction, self-critique scores
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from collections import defaultdict

from ..config import config


class PerformanceTracker:
    def __init__(self, track_path: Path = None):
        self.track_path = track_path or config.MEMORY_FILE.parent / "evolution" / "performance.json"
        self.track_path.parent.mkdir(parents=True, exist_ok=True)
        self.history: List[Dict] = self._load()
    
    def _load(self) -> List[Dict]:
        if self.track_path.exists():
            try:
                return json.loads(self.track_path.read_text())
            except:
                return []
        return []
    
    def _save(self):
        try:
            self.track_path.write_text(json.dumps(self.history[-500:], indent=2))  # keep last 500
        except Exception as e:
            print(f"Performance save failed: {e}")
    
    def record(self, 
               user_input: str,
               response: str,
               latency_ms: int,
               tool_calls: List[Dict] = None,
               tool_success: float = 1.0,
               satisfaction: float = None,
               critic_score: float = None):
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "input_length": len(user_input),
            "response_length": len(response),
            "latency_ms": latency_ms,
            "tool_calls_count": len(tool_calls) if tool_calls else 0,
            "tool_calls": [tc.get("function", {}).get("name") if isinstance(tc, dict) else str(tc) for tc in (tool_calls or [])][:5],
            "tool_success": tool_success,
            "satisfaction": satisfaction,
            "critic_score": critic_score,
            "input_preview": user_input[:100]
        }
        self.history.append(entry)
        self._save()
    
    def get_stats(self, last_n: int = 50) -> Dict:
        recent = self.history[-last_n:] if self.history else []
        if not recent:
            return {"avg_latency": 0, "success_rate": 1.0, "avg_satisfaction": 0.5, "tool_usage": {}}
        
        avg_latency = sum(h["latency_ms"] for h in recent) / len(recent)
        success_rate = sum(h["tool_success"] for h in recent) / len(recent)
        satis_scores = [h["satisfaction"] for h in recent if h.get("satisfaction") is not None]
        avg_satisfaction = sum(satis_scores)/len(satis_scores) if satis_scores else 0.5
        
        critic_scores = [h["critic_score"] for h in recent if h.get("critic_score") is not None]
        avg_critic = sum(critic_scores)/len(critic_scores) if critic_scores else None
        
        # Tool usage
        tool_counts = defaultdict(int)
        for h in recent:
            for tc in h.get("tool_calls", []):
                tool_counts[tc] += 1
        
        # Trend (is latency improving? satisfaction?)
        if len(recent) >= 10:
            first_half = recent[:len(recent)//2]
            second_half = recent[len(recent)//2:]
            first_satis = sum(h.get("satisfaction", 0.5) or 0.5 for h in first_half)/len(first_half)
            second_satis = sum(h.get("satisfaction", 0.5) or 0.5 for h in second_half)/len(second_half)
            trend = "improving" if second_satis > first_satis + 0.05 else "declining" if second_satis < first_satis - 0.05 else "stable"
        else:
            trend = "unknown"
        
        return {
            "total_interactions": len(self.history),
            "recent_count": len(recent),
            "avg_latency": round(avg_latency, 1),
            "success_rate": round(success_rate, 3),
            "avg_satisfaction": round(avg_satisfaction, 3),
            "avg_critic_score": round(avg_critic, 3) if avg_critic else None,
            "tool_usage": dict(tool_counts),
            "trend": trend,
            "last_interaction": self.history[-1]["timestamp"] if self.history else None
        }
    
    def get_failing_tools(self, threshold: float = 0.7) -> List[str]:
        """Get tools that fail often"""
        # Simplified - would need more detailed tracking
        tool_failures = defaultdict(list)
        for h in self.history[-50:]:
            if h["tool_success"] < threshold:
                for tc in h.get("tool_calls", []):
                    tool_failures[tc].append(h["tool_success"])
        
        failing = []
        for tool, successes in tool_failures.items():
            avg = sum(successes)/len(successes)
            if avg < threshold and len(successes) >= 2:
                failing.append(tool)
        return failing
    
    def should_evolve(self) -> Dict:
        """Decide if JARVIS should try to improve himself now"""
        stats = self.get_stats(last_n=20)
        
        reasons = []
        should = False
        
        if stats["avg_satisfaction"] < 0.5:
            reasons.append(f"Low satisfaction {stats['avg_satisfaction']} - needs improvement")
            should = True
        
        if stats["success_rate"] < 0.8:
            reasons.append(f"Low tool success {stats['success_rate']} - tools need fixing")
            should = True
        
        if stats["trend"] == "declining":
            reasons.append("Performance declining - should evolve")
            should = True
        
        if stats["avg_critic_score"] is not None and stats["avg_critic_score"] < 6.0:
            reasons.append(f"Low self-critique {stats['avg_critic_score']}/10 - should improve")
            should = True
        
        # Occasionally evolve even if doing well (every 50 interactions)
        if stats["total_interactions"] > 0 and stats["total_interactions"] % 50 == 0:
            reasons.append("50 interactions milestone - periodic evolution")
            should = True
        
        return {"should_evolve": should, "reasons": reasons, "stats": stats}
