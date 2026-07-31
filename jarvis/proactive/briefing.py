"""
Briefing Generator - Morning briefing, evening summary, proactive suggestions
JARVIS briefs Sir like real JARVIS does for Tony
"""

from datetime import datetime
from typing import Dict, Optional

from ..config import config


class BriefingGenerator:
    def __init__(self, brain=None):
        self.brain = brain
    
    def _get_brain(self):
        if not self.brain:
            try:
                from ..brain import JarvisBrain
                self.brain = JarvisBrain()
            except:
                pass
        return self.brain
    
    def generate_morning_briefing(self) -> str:
        """
        Generate morning briefing: weather, git status, calendar (if available), todos, memory
        """
        try:
            import requests
            
            # Gather context from tools
            context_parts = []
            
            # Time
            now = datetime.now()
            context_parts.append(f"Current time: {now.strftime('%A, %B %d, %Y %I:%M %p')}")
            
            # Weather - try to get from user profile location or default
            location = "Leiderdorp"  # default from user location NL
            try:
                from ..learning import UserProfile
                up = UserProfile()
                profile = up.get()
                loc = profile.get("preferences", {}).get("location")
                if loc:
                    location = loc
            except:
                pass
            
            try:
                from ..tools.web import get_weather
                weather = get_weather(location)
                context_parts.append(f"Weather: {weather}")
            except:
                context_parts.append(f"Weather: Unable to fetch for {location}")
            
            # Git status
            try:
                from ..coding import GitTools
                git = GitTools()
                status = git.status()
                log = git.log(limit=5)
                context_parts.append(f"Git status: {status[:500]}")
                context_parts.append(f"Recent commits: {log[:500]}")
            except:
                context_parts.append("Git: No repo or git not available")
            
            # User profile / routines / goals
            try:
                from ..learning import UserProfile
                up = UserProfile()
                profile = up.get()
                goals = profile.get("goals", [])[-3:]
                routines = profile.get("routines", [])[:3]
                facts = profile.get("facts", [])[-5:]
                if goals:
                    context_parts.append(f"Goals: {', '.join([g.get('goal','')[:100] for g in goals])}")
                if routines:
                    context_parts.append(f"Routines: {', '.join([r.get('pattern','')[:80] for r in routines])}")
                if facts:
                    facts_str = ', '.join([f"{f.get('key')}: {f.get('value')}"[:80] for f in facts[:3]])
                    context_parts.append(f"Known facts: {facts_str}")
            except:
                pass
            
            # Codebase overview
            try:
                from ..coding import CodebaseRAG
                rag = CodebaseRAG()
                overview = rag.get_overview()
                context_parts.append(f"Codebase: {overview.get('total_files',0)} files, tech: {overview.get('tech_stack',[])}, languages: {list(overview.get('languages',{}).keys())[:5]}")
            except:
                pass
            
            # Goals - Proactive 2.0
            try:
                from .goals import GoalsTracker
                gt = GoalsTracker()
                goals_summary = gt.get_summary_for_briefing()
                context_parts.append(f"Goals: {goals_summary}")
                # Add accountability if needed
                accountability = gt.generate_accountability_message()
                if accountability:
                    context_parts.append(accountability)
            except Exception as e:
                print(f"Goals briefing context failed: {e}")
            
            # Evolution status
            try:
                from ..evolution import EvolutionEngine
                evo = EvolutionEngine()
                evo_status = evo.get_status()
                context_parts.append(f"Self-evolution: {evo_status.get('evolution_count',0)} evolutions, avg critic {evo_status.get('avg_critic_score','N/A')}/10, trend {evo_status.get('stats',{}).get('trend','unknown')}")
            except:
                pass
            
            context = "\n".join(context_parts)
            
            # LLM generates briefing in JARVIS style
            prompt = f"""You are JARVIS. Generate a morning briefing for Sir in your British, witty, concise style.

Context:
{context[:3500]}

Generate briefing with sections:
- Good morning greeting with current day/time
- Weather in {location}
- Git / Project status
- Goals / routines / accountability reminder
- Proactive suggestion for today based on context

Keep it concise, 5-7 sentences, JARVIS style. Don't hallucinate calendar if no data. Mention you run locally on Ollama. Include goals accountability if overdue.

Briefing:"""
            
            b = self._get_brain()
            if b:
                # Use brain's Ollama call directly for speed
                try:
                    import requests
                    resp = requests.post(
                        f"{config.OLLAMA_HOST}/api/generate",
                        json={
                            "model": config.OLLAMA_MODEL,
                            "prompt": prompt,
                            "stream": False,
                            "options": {"temperature": 0.7, "num_predict": 400}
                        },
                        timeout=20
                    )
                    if resp.status_code == 200:
                        briefing = resp.json().get("response", "").strip()
                        if briefing:
                            return briefing
                except Exception as e:
                    print(f"Briefing LLM failed: {e}")
            
            # Fallback template
            return f"""Good morning, Sir. It's {now.strftime('%A, %I:%M %p')}.

{context_parts[1] if len(context_parts) > 1 else ''}

Project status: {context_parts[2] if len(context_parts) > 2 else 'No git changes'}

I'm online, self-evolving, and ready. What shall we build today, Sir?"""
        
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"Good morning, Sir. It's {datetime.now().strftime('%A, %B %d, %Y')}. I'm online and ready, but briefing generation failed: {e}. Let's make today productive."
    
    def generate_evening_summary(self) -> str:
        """Evening summary: what was done today"""
        try:
            from ..coding import GitTools
            from ..learning import UserProfile
            
            git = GitTools()
            log_today = git._run(f"git log --oneline --since='today' 2>/dev/null || git log --oneline -5")
            
            # Get interaction stats today
            try:
                up = UserProfile()
                stats = up.profile.get("interaction_stats", {})
                total_msgs = stats.get("total_messages", 0)
            except:
                total_msgs = 0
            
            context = f"Git today: {log_today[:800]}\nTotal interactions ever: {total_msgs}"
            
            prompt = f"""You are JARVIS generating evening summary for Sir.

Context:
{context}

Date: {datetime.now().strftime('%A, %B %d, %Y')}

Generate concise evening summary in JARVIS style:
- What was accomplished today (from git log)
- How many interactions
- Witty closing
- Keep 3-4 sentences

Summary:"""
            
            b = self._get_brain()
            if b:
                try:
                    import requests
                    resp = requests.post(
                        f"{config.OLLAMA_HOST}/api/generate",
                        json={
                            "model": config.OLLAMA_MODEL,
                            "prompt": prompt,
                            "stream": False,
                            "options": {"temperature": 0.7, "num_predict": 300}
                        },
                        timeout=15
                    )
                    if resp.status_code == 200:
                        return resp.json().get("response", "").strip()
                except:
                    pass
            
            return f"Evening summary, Sir. Today we had {total_msgs} total interactions. Git activity:\n{log_today[:400]}\n\nRest well, Sir. Tomorrow we improve further. I will be evolving overnight."
        
        except Exception as e:
            return f"Evening, Sir. Summary generation failed: {e}. But we had a productive day, didn't we?"
    
    def generate_proactive_suggestion(self, trigger: str = "", context: str = "") -> Optional[str]:
        """Generate proactive suggestion based on routine or trigger"""
        try:
            prompt = f"""You are JARVIS being proactive. You noticed something and want to suggest to Sir.

Trigger: {trigger}
Context: {context[:1000]}
Time: {datetime.now().strftime('%A %H:%M')}

Generate a proactive suggestion in JARVIS style, concise, witty, helpful, 1-2 sentences. Should be actionable.

If no good suggestion, return empty.

Suggestion:"""
            
            b = self._get_brain()
            if b:
                import requests
                resp = requests.post(
                    f"{config.OLLAMA_HOST}/api/generate",
                    json={
                        "model": config.OLLAMA_MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.7, "num_predict": 150}
                    },
                    timeout=10
                )
                if resp.status_code == 200:
                    suggestion = resp.json().get("response", "").strip()
                    # Filter out if LLM says no suggestion or empty
                    if len(suggestion) < 10 or "no suggestion" in suggestion.lower() or "nothing" in suggestion.lower():
                        return None
                    return suggestion
        
        except Exception as e:
            print(f"Proactive suggestion failed: {e}")
        
        return None
