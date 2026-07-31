"""
Premium Voice - Manina Labs style + JARVIS cinematic
Supports: edge, elevenlabs, openai, xtts (local clone), piper (local high-quality)

Manina's premium voice model is deep, British, cinematic with subtle reverb and processing.
We emulate that with:
- ElevenLabs (best quality, needs API key) - can clone Paul Bettany
- XTTS v2 local (Coqui) - 100% local voice cloning from sample
- OpenAI TTS - high quality
- Edge + audio processing (bass boost + reverb) - free, offline-ish, Manina-style
"""

import os
import asyncio
import tempfile
from pathlib import Path
from typing import Optional

from ..config import config


# Voice presets - Manina Labs style + other JARVIS voices
VOICE_PRESETS = {
    "manina_premium": {
        "description": "Manina Labs premium - deep British, cinematic, slight reverb, authoritative - like movie JARVIS",
        "edge_voice": "en-GB-RyanNeural",
        "elevenlabs_voice": "deep British male, cinematic",
        "openai_voice": "onyx",
        "effects": {"pitch": -2, "speed": 0.92, "reverb": 0.3, "bass_boost": 6, "eq": "cinematic"},
        "style_prompt": "Deep British male, 35-40, calm, authoritative, slightly processed like Iron Man's JARVIS, premium cinematic quality"
    },
    "jarvis_classic": {
        "description": "Classic Paul Bettany JARVIS - British, calm, witty, sophisticated",
        "edge_voice": "en-GB-RyanNeural",
        "elevenlabs_voice": "Paul Bettany style",
        "openai_voice": "onyx",
        "effects": {"pitch": -1, "speed": 0.95, "reverb": 0.15, "bass_boost": 3},
        "style_prompt": "British male, calm, sophisticated, Paul Bettany as JARVIS"
    },
    "jarvis_deep": {
        "description": "Deeper, more commanding JARVIS - slower, more gravitas",
        "edge_voice": "en-US-GuyNeural",
        "elevenlabs_voice": "deep commanding British",
        "openai_voice": "onyx",
        "effects": {"pitch": -4, "speed": 0.88, "reverb": 0.25, "bass_boost": 8},
        "style_prompt": "Deep British male, commanding, gravitas, slower pace"
    },
    "friday": {
        "description": "FRIDAY - Female Irish, warm, slightly faster, caring",
        "edge_voice": "en-GB-SoniaNeural",
        "elevenlabs_voice": "Irish female, warm",
        "openai_voice": "nova",
        "effects": {"pitch": 1, "speed": 1.02, "reverb": 0.1, "bass_boost": 0},
        "style_prompt": "Irish female, warm, caring, slightly faster than JARVIS"
    },
    "manina_blender": {
        "description": "Manina Blender integration style - clear, technical, energetic for 3D commands",
        "edge_voice": "en-GB-RyanNeural",
        "elevenlabs_voice": "clear British technical",
        "openai_voice": "echo",
        "effects": {"pitch": 0, "speed": 0.98, "reverb": 0.1, "bass_boost": 2},
        "style_prompt": "Clear British male, technical, energetic, for 3D/Blender commands"
    }
}


class PremiumTTS:
    def __init__(self, 
                 engine: str = None, 
                 voice_preset: str = None,
                 voice_id: str = None):
        """
        engine: auto, edge, elevenlabs, openai, xtts, piper, gtts
        voice_preset: manina_premium, jarvis_classic, jarvis_deep, friday, manina_blender
        voice_id: specific voice id for elevenlabs/openai/xtts
        """
        self.engine = engine or os.getenv("TTS_ENGINE", "edge")
        self.voice_preset_name = voice_preset or os.getenv("PREMIUM_VOICE_STYLE", "manina_premium")
        self.preset = VOICE_PRESETS.get(self.voice_preset_name, VOICE_PRESETS["manina_premium"])
        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID") or os.getenv("TTS_VOICE", self.preset["edge_voice"])
        
        self.elevenlabs_key = os.getenv("ELEVENLABS_API_KEY")
        self.openai_key = os.getenv("OPENAI_API_KEY")
        
        # For XTTS local cloning
        self.xtts_model = None
        self.xtts_samples_dir = config.MEMORY_FILE.parent / "voices"
        self.xtts_samples_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"🎙️ Premium TTS: engine={self.engine}, preset={self.voice_preset_name} ({self.preset['description']})")
        
        self._init_engine()
    
    def _init_engine(self):
        # Check availability
        if self.engine == "elevenlabs" and not self.elevenlabs_key:
            print("ElevenLabs key not found, falling back to edge with premium processing")
            self.engine = "edge"
        
        if self.engine == "openai" and not self.openai_key:
            print("OpenAI key not found, falling back to edge")
            self.engine = "edge"
        
        if self.engine == "xtts":
            try:
                # Try to import TTS (coqui)
                from TTS.api import TTS
                print("✓ XTTS available, but will lazy-load model on first use (2GB)")
            except ImportError:
                print("XTTS not installed, pip install TTS, falling back to edge")
                self.engine = "edge"
        
        if self.engine == "piper":
            try:
                import piper
                print("✓ Piper TTS available")
            except ImportError:
                print("Piper not installed, falling back to edge")
                self.engine = "edge"
        
        print(f"✓ Premium TTS ready: {self.engine} + {self.voice_preset_name}")
    
    def _clean_text(self, text: str) -> str:
        import re
        # Remove markdown, tool markers
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        text = re.sub(r'\[.*?tool.*?\]', '', text, flags=re.IGNORECASE)
        text = text.replace('*', '').replace('#', '').strip()
        if len(text) > 1000:
            text = text[:1000] + " ... and so on, Sir."
        return text.strip()
    
    def _apply_premium_effects(self, audio_path: str) -> str:
        """
        Apply Manina-style premium effects: bass boost, reverb, slight pitch shift
        Uses pydub if available, otherwise returns original
        """
        try:
            from pydub import AudioSegment
            from pydub.effects import low_pass_filter
            
            effects = self.preset.get("effects", {})
            bass_boost = effects.get("bass_boost", 0)
            reverb = effects.get("reverb", 0)
            
            if bass_boost == 0 and reverb == 0:
                return audio_path
            
            audio = AudioSegment.from_file(audio_path)
            
            # Bass boost - low shelf filter via low_pass + overlay? Simplified: boost low frequencies by increasing volume of low-passed version
            if bass_boost > 0:
                # Simple bass boost: low pass at 250Hz and boost
                low = low_pass_filter(audio, 250)
                # Boost low frequencies
                audio = audio.overlay(low + bass_boost)
            
            # Reverb: simple echo with delay and decay (cheap reverb)
            if reverb > 0:
                # Create echo
                delay_ms = 80
                decay = 0.2 * reverb
                echo = AudioSegment.silent(duration=delay_ms) + (audio - (20 * (1-decay)))
                # Overlay
                audio = audio.overlay(echo)
            
            # Export to new temp file
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                new_path = f.name
            audio.export(new_path, format="mp3")
            
            try:
                os.unlink(audio_path)
            except:
                pass
            
            return new_path
        
        except ImportError:
            # pydub not available, return original
            return audio_path
        except Exception as e:
            print(f"Premium effects failed: {e}")
            return audio_path
    
    async def _edge_tts(self, text: str) -> str:
        import edge_tts
        
        voice = self.voice_id or self.preset["edge_voice"]
        
        # Edge TTS rate and pitch based on preset
        effects = self.preset.get("effects", {})
        # Convert preset to edge TTS rate: +0% is default, -8% slower etc
        speed = effects.get("speed", 1.0)
        # Edge rate: from -50% to +100%, we map speed 0.9 -> -10%
        rate_percent = int((speed - 1.0) * 100)
        rate_str = f"{rate_percent:+d}%" if rate_percent != 0 else "+0%"
        
        pitch = effects.get("pitch", 0)
        # Pitch: -10Hz to +... approximate
        pitch_str = f"{pitch:+d}Hz" if pitch != 0 else "+0Hz"
        
        communicate = edge_tts.Communicate(text, voice, rate=rate_str, pitch=pitch_str)
        
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_file = f.name
        
        await communicate.save(temp_file)
        
        # Apply premium effects
        premium_path = self._apply_premium_effects(temp_file)
        
        return premium_path
    
    async def _elevenlabs_tts(self, text: str) -> str:
        from elevenlabs import VoiceSettings
        from elevenlabs.client import ElevenLabs
        
        client = ElevenLabs(api_key=self.elevenlabs_key)
        
        # Use voice_id or default
        voice_id = self.voice_id
        if not voice_id or voice_id.startswith("en-"):
            # If we have preset name like en-GB-RyanNeural, use a default elevenlabs voice
            # Best British deep voice IDs (public)
            # Adam - deep male, Antoni - well-rounded, Arnold - deep
            voice_id = "pNInz6obpgDQGcFmaJgB"  # Adam - deep
            if "friday" in self.voice_preset_name:
                voice_id = "EXAVITQu4vr4xnSDxMaL"  # Bella - female
        
        # Voice settings for cinematic JARVIS
        settings = VoiceSettings(
            stability=0.75,
            similarity_boost=0.75,
            style=0.5,
            use_speaker_boost=True
        )
        
        # Adjust for preset
        if "manina_premium" in self.voice_preset_name or "deep" in self.voice_preset_name:
            settings.stability = 0.85
            settings.similarity_boost = 0.8
            settings.style = 0.3
        
        audio = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            voice_settings=settings
        )
        
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_file = f.name
            for chunk in audio:
                f.write(chunk)
        
        premium_path = self._apply_premium_effects(temp_file)
        return premium_path
    
    async def _openai_tts(self, text: str) -> str:
        from openai import OpenAI
        
        client = OpenAI(api_key=self.openai_key)
        
        voice = self.preset["openai_voice"]
        if self.voice_id and self.voice_id in ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]:
            voice = self.voice_id
        
        response = client.audio.speech.create(
            model="tts-1-hd",  # hd for premium quality
            voice=voice,
            input=text,
            speed=self.preset.get("effects", {}).get("speed", 1.0)
        )
        
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_file = f.name
            response.stream_to_file(temp_file)
        
        premium_path = self._apply_premium_effects(temp_file)
        return premium_path
    
    async def _xtts_tts(self, text: str) -> str:
        from TTS.api import TTS
        
        if not self.xtts_model:
            print("Loading XTTS v2 model (2GB, first time)...")
            self.xtts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=False)
        
        # Find sample voice file for cloning
        # Look for jarvis sample in voices dir
        sample_path = None
        # Check preset-specific sample
        for ext in [".wav", ".mp3"]:
            candidate = self.xtts_samples_dir / f"{self.voice_preset_name}{ext}"
            if candidate.exists():
                sample_path = str(candidate)
                break
        
        # Fallback to any sample
        if not sample_path:
            samples = list(self.xtts_samples_dir.glob("*.wav")) + list(self.xtts_samples_dir.glob("*.mp3"))
            if samples:
                sample_path = str(samples[0])
        
        # If no sample, use edge as fallback for sample creation? Or use default
        if not sample_path:
            # Create a placeholder - use edge to generate sample then clone? For now use edge fallback
            print("No XTTS sample found, place a 5-10 sec WAV of target voice in data/voices/ named manina_premium.wav")
            # Fallback to edge
            return await self._edge_tts(text)
        
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_file = f.name
        
        self.xtts_model.tts_to_file(
            text=text,
            file_path=temp_file,
            speaker_wav=sample_path,
            language="en"
        )
        
        # Convert wav to mp3 with effects
        premium_path = self._apply_premium_effects(temp_file)
        return premium_path
    
    async def speak_async(self, text: str) -> str:
        """Generate audio file path, doesn't play"""
        clean = self._clean_text(text)
        if not clean:
            return None
        
        print(f"🔊 Premium TTS ({self.voice_preset_name} via {self.engine}): {clean[:80]}...")
        
        try:
            if self.engine == "elevenlabs":
                return await self._elevenlabs_tts(clean)
            elif self.engine == "openai":
                return await self._openai_tts(clean)
            elif self.engine == "xtts":
                return await self._xtts_tts(clean)
            else:  # edge default with premium effects
                return await self._edge_tts(clean)
        except Exception as e:
            print(f"Premium TTS {self.engine} failed: {e}, falling back to edge")
            import traceback
            traceback.print_exc()
            try:
                return await self._edge_tts(clean)
            except Exception as e2:
                print(f"Edge fallback also failed: {e2}")
                return None
    
    def speak(self, text: str, blocking: bool = True):
        """Speak with premium voice, blocking or non-blocking"""
        import threading
        
        def _play():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                audio_path = loop.run_until_complete(self.speak_async(text))
                loop.close()
                
                if not audio_path:
                    return
                
                # Play
                try:
                    import pygame
                    pygame.mixer.init()
                    pygame.mixer.music.load(audio_path)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        import time
                        time.sleep(0.1)
                    pygame.mixer.quit()
                except Exception as e:
                    print(f"Pygame play failed: {e}, trying ffplay")
                    try:
                        import subprocess
                        subprocess.run(["ffplay", "-nodisp", "-autoexit", audio_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                    except:
                        pass
                
                try:
                    os.unlink(audio_path)
                except:
                    pass
            
            except Exception as e:
                print(f"Premium speak failed: {e}")
        
        if blocking:
            _play()
        else:
            threading.Thread(target=_play, daemon=True).start()
    
    def list_presets(self):
        for name, preset in VOICE_PRESETS.items():
            print(f"- {name}: {preset['description']}")
    
    def set_preset(self, preset_name: str):
        if preset_name in VOICE_PRESETS:
            self.voice_preset_name = preset_name
            self.preset = VOICE_PRESETS[preset_name]
            print(f"✓ Voice preset set to {preset_name}: {self.preset['description']}")
        else:
            print(f"Preset {preset_name} not found. Available: {list(VOICE_PRESETS.keys())}")

    def save_sample_instruction(self):
        return f"""
To use XTTS voice cloning for premium voice:

1. Record or find a 5-10 second clean WAV of target voice (e.g. Paul Bettany as JARVIS)
2. Save as: {self.xtts_samples_dir / 'manina_premium.wav'}
3. Set in .env: TTS_ENGINE=xtts and PREMIUM_VOICE_STYLE=manina_premium
4. Install: pip install TTS --break-system-packages (2GB model download first time)

For ElevenLabs (best quality, Manina style):
1. Get API key from elevenlabs.io
2. .env: ELEVENLABS_API_KEY=your_key, TTS_ENGINE=elevenlabs, PREMIUM_VOICE_STYLE=manina_premium
3. Optional: ELEVENLABS_VOICE_ID to use specific voice

For OpenAI (good quality):
1. OPENAI_API_KEY=your_key, TTS_ENGINE=openai
"""


# Singleton
_premium_instance = None

def get_premium_tts(engine: str = None, preset: str = None) -> PremiumTTS:
    global _premium_instance
    if _premium_instance is None:
        _premium_instance = PremiumTTS(engine=engine, voice_preset=preset)
    else:
        if preset:
            _premium_instance.set_preset(preset)
        if engine:
            _premium_instance.engine = engine
    return _premium_instance


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="JARVIS Premium Voice Test - Manina Labs style")
    parser.add_argument("--text", default="Good evening, Sir. I am JARVIS. Just a rather very intelligent system. Premium voice model online, Sir. At your service.", help="Text to speak")
    parser.add_argument("--engine", default="edge", choices=["edge", "elevenlabs", "openai", "xtts", "piper"], help="TTS engine")
    parser.add_argument("--preset", default="manina_premium", choices=list(VOICE_PRESETS.keys()), help="Voice preset")
    args = parser.parse_args()
    
    tts = PremiumTTS(engine=args.engine, voice_preset=args.preset)
    tts.list_presets()
    print(f"\nSpeaking with {args.preset} via {args.engine}: {args.text}\n")
    tts.speak(args.text, blocking=True)
