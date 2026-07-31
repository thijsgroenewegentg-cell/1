"""
Text To Speech for JARVIS - edge-tts for realistic British voice + pyttsx3 offline fallback
"""
import asyncio
import os
import tempfile
import threading
from ..config import config

class TextToSpeech:
    def __init__(self, engine: str = None, voice: str = None):
        self.engine = engine or config.TTS_ENGINE
        self.voice = voice or config.TTS_VOICE
        self.pyaudio_engine = None
        self._init_engine()
    
    def _init_engine(self):
        if self.engine == "pyttsx3":
            try:
                import pyttsx3
                self.pyaudio_engine = pyttsx3.init()
                # Try to set British voice
                voices = self.pyaudio_engine.getProperty('voices')
                for v in voices:
                    if 'british' in v.name.lower() or 'uk' in v.name.lower() or 'english' in v.name.lower():
                        self.pyaudio_engine.setProperty('voice', v.id)
                        break
                # Slow down slightly for Jarvis feel
                rate = self.pyaudio_engine.getProperty('rate')
                self.pyaudio_engine.setProperty('rate', rate - 20)
                print(f"✓ TTS: pyttsx3 ready")
            except Exception as e:
                print(f"pyttsx3 init failed: {e}, trying edge")
                self.engine = "edge"
                self._init_engine()
        elif self.engine == "edge":
            try:
                import edge_tts
                import pygame
                print(f"✓ TTS: edge-tts ready (voice: {self.voice})")
            except ImportError as e:
                print(f"edge-tts/pygame not installed: {e}, falling back to pyttsx3")
                self.engine = "pyttsx3"
                self._init_engine()
    
    def speak(self, text: str, blocking: bool = True):
        """Speak text"""
        if not text or not text.strip():
            return
        
        # Clean text for TTS (remove markdown, tool tags, etc)
        clean_text = self._clean_text(text)
        if not clean_text:
            return
        
        print(f"🔊 JARVIS: {clean_text}")
        
        if self.engine == "pyttsx3" and self.pyaudio_engine:
            try:
                def _speak():
                    self.pyaudio_engine.say(clean_text)
                    self.pyaudio_engine.runAndWait()
                
                if blocking:
                    _speak()
                else:
                    threading.Thread(target=_speak, daemon=True).start()
            except Exception as e:
                print(f"pyttsx3 speak error: {e}")
        
        elif self.engine == "edge":
            try:
                if blocking:
                    asyncio.run(self._edge_speak(clean_text))
                else:
                    threading.Thread(target=lambda: asyncio.run(self._edge_speak(clean_text)), daemon=True).start()
            except Exception as e:
                print(f"edge-tts error: {e}")
                # fallback
                try:
                    import pyttsx3
                    engine = pyttsx3.init()
                    engine.say(clean_text)
                    engine.runAndWait()
                except:
                    pass
    
    async def _edge_speak(self, text: str):
        import edge_tts
        import pygame
        
        # Avoid too long texts - split
        if len(text) > 500:
            # Speak in chunks
            chunks = [text[i:i+500] for i in range(0, len(text), 500)]
            for chunk in chunks:
                await self._edge_speak_chunk(chunk)
            return
        else:
            await self._edge_speak_chunk(text)
    
    async def _edge_speak_chunk(self, text: str):
        import edge_tts
        import pygame
        
        communicate = edge_tts.Communicate(text, self.voice)
        
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_file = f.name
        
        try:
            await communicate.save(temp_file)
            
            pygame.mixer.init()
            pygame.mixer.music.load(temp_file)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)
            pygame.mixer.quit()
        finally:
            try:
                os.unlink(temp_file)
            except:
                pass
    
    def _clean_text(self, text: str) -> str:
        # Remove tool usage indicators
        import re
        # Remove markdown code blocks
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        # Remove [Using tool...] markers
        text = re.sub(r'\[.*?tool.*?\]\n?', '', text, flags=re.IGNORECASE)
        # Remove emojis maybe? Keep but clean
        # Remove excessive newlines
        text = text.replace('*', '').replace('#', '').strip()
        # Keep first 1000 chars for TTS
        if len(text) > 1000:
            text = text[:1000] + " ... and so on, Sir."
        return text.strip()
    
    def list_voices(self):
        if self.engine == "pyttsx3" and self.pyaudio_engine:
            voices = self.pyaudio_engine.getProperty('voices')
            for v in voices:
                print(f"- {v.id}: {v.name}")
        elif self.engine == "edge":
            print("Use: edge-tts --list-voices to see all voices")
            print("Recommended for JARVIS:")
            print("- en-GB-RyanNeural (British Male, perfect JARVIS)")
            print("- en-GB-SoniaNeural (British Female, FRIDAY)")
            print("- en-US-GuyNeural (US Male, deeper)")
            print("- en-US-JennyNeural (US Female)")

# Singleton
_tts_instance = None
def get_tts():
    global _tts_instance
    if _tts_instance is None:
        _tts_instance = TextToSpeech()
    return _tts_instance
