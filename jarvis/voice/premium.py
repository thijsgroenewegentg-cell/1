"""
Premium Voice - Piper FREE Offline by default, YOUR ElevenLabs CwhRBWXzGAHq8TQ4Fs17 for premium JARVIS
100% FREE possible, but supports your premium voice CwhRBWXzGAHq8TQ4Fs17 if API key provided

Engines:
- piper (FREE, 100% offline British high quality, default MUST BE PIPER)
- elevenlabs (premium with your voice CwhRBWXzGAHq8TQ4Fs17, deep British cinematic)
- edge (free online fallback with premium FX)
- xtts (free local cloning)
- pyttsx3 (free offline fallback)
"""

import os
import asyncio
import tempfile
from pathlib import Path

from ..config import config


VOICE_PRESETS = {
    "manina_premium": {
        "description": "Manina Labs premium - deep British, cinematic, reverb, authoritative - FREE via piper or premium via your ElevenLabs CwhRBWXzGAHq8TQ4Fs17",
        "free": True,
        "edge_voice": "en-GB-RyanNeural",
        "piper_voice": "en_GB-alan-medium",
        "elevenlabs_voice": "CwhRBWXzGAHq8TQ4Fs17",
        "openai_voice": "onyx",
        "effects": {"pitch": -2, "speed": 0.92, "reverb": 0.32, "bass_boost": 6, "eq": "cinematic", "chorus": 0.15},
        "style_prompt": "Deep British male, 35-40, calm, authoritative, like movie JARVIS, premium cinematic"
    },
    "jarvis_classic": {
        "description": "Classic Paul Bettany JARVIS - British calm witty - FREE or your CwhRBWXzGAHq8TQ4Fs17",
        "free": True,
        "edge_voice": "en-GB-RyanNeural",
        "piper_voice": "en_GB-alan-medium",
        "elevenlabs_voice": "CwhRBWXzGAHq8TQ4Fs17",
        "openai_voice": "onyx",
        "effects": {"pitch": -1, "speed": 0.95, "reverb": 0.15, "bass_boost": 3, "chorus": 0.05},
        "style_prompt": "British male, calm, sophisticated, Paul Bettany as JARVIS"
    },
    "jarvis_deep": {
        "description": "Deeper commanding JARVIS - gravitas - FREE or CwhRBWXzGAHq8TQ4Fs17",
        "free": True,
        "edge_voice": "en-US-GuyNeural",
        "piper_voice": "en_GB-southern_english_male-medium",
        "elevenlabs_voice": "CwhRBWXzGAHq8TQ4Fs17",
        "openai_voice": "onyx",
        "effects": {"pitch": -4, "speed": 0.88, "reverb": 0.28, "bass_boost": 8, "chorus": 0.1},
        "style_prompt": "Deep British male, commanding, gravitas, slower"
    },
    "friday": {
        "description": "FRIDAY - Female Irish warm - FREE",
        "free": True,
        "edge_voice": "en-GB-SoniaNeural",
        "piper_voice": "en_GB-jenny_dioco-medium",
        "elevenlabs_voice": "EXAVITQu4vr4xnSDxMaL",
        "openai_voice": "nova",
        "effects": {"pitch": 1, "speed": 1.02, "reverb": 0.1, "bass_boost": 0, "chorus": 0},
        "style_prompt": "Irish female, warm, caring"
    },
    "manina_blender": {
        "description": "Manina Blender style - clear technical energetic - FREE",
        "free": True,
        "edge_voice": "en-GB-RyanNeural",
        "piper_voice": "en_GB-alan-medium",
        "elevenlabs_voice": "CwhRBWXzGAHq8TQ4Fs17",
        "openai_voice": "echo",
        "effects": {"pitch": 0, "speed": 0.98, "reverb": 0.1, "bass_boost": 2, "chorus": 0},
        "style_prompt": "Clear British male, technical, energetic"
    }
}


class PremiumTTS:
    def __init__(self, engine: str = None, voice_preset: str = None, voice_id: str = None):
        """
        YOUR ElevenLabs voice CwhRBWXzGAHq8TQ4Fs17 for premium JARVIS, with Piper free offline fallback
        engine: piper (FREE offline British, default), elevenlabs (premium with your voice CwhRBWXzGAHq8TQ4Fs17), edge, xtts
        """
        self.engine = engine or os.getenv("TTS_ENGINE", "piper")
        self.voice_preset_name = voice_preset or os.getenv("PREMIUM_VOICE_STYLE", "manina_premium")
        self.preset = VOICE_PRESETS.get(self.voice_preset_name, VOICE_PRESETS["manina_premium"])
        
        # YOUR VOICE ID - default for elevenlabs
        # Priority: explicit voice_id arg > ELEVENLABS_VOICE_ID env > TTS_VOICE env > preset
        if voice_id:
            self.voice_id = voice_id
        elif os.getenv("ELEVENLABS_VOICE_ID"):
            self.voice_id = os.getenv("ELEVENLABS_VOICE_ID")
        elif self.engine == "elevenlabs":
            # For elevenlabs, use your voice CwhRBWXzGAHq8TQ4Fs17 as default JARVIS voice
            self.voice_id = "CwhRBWXzGAHq8TQ4Fs17"
        else:
            # For piper/edge, use TTS_VOICE or preset
            self.voice_id = os.getenv("TTS_VOICE", self.preset.get("piper_voice" if self.engine == "piper" else "edge_voice", self.preset["edge_voice"]))
        
        # API keys
        self.elevenlabs_key = os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVENLABS_KEY")
        self.openai_key = os.getenv("OPENAI_API_KEY")
        
        self.xtts_model = None
        self.xtts_samples_dir = config.MEMORY_FILE.parent / "voices"
        self.xtts_samples_dir.mkdir(parents=True, exist_ok=True)
        self.piper_models_dir = config.MEMORY_FILE.parent / "piper_models"
        self.piper_models_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"🎙️ Premium TTS: engine={self.engine}, preset={self.voice_preset_name}, voice_id={self.voice_id[:20]}... ({self.preset['description'][:60]})")
        self._init_engine()
    
    def _init_engine(self):
        # Piper - best free offline, MUST BE PIPER by default
        if self.engine == "piper":
            try:
                import piper
                print("✓ Piper TTS available - 100% free offline, high quality British")
            except ImportError:
                print("Piper not installed, pip install piper-tts, falling back to edge (still free)")
                self.engine = "edge"
        
        if self.engine == "xtts":
            try:
                from TTS.api import TTS
                print("✓ XTTS available - free local voice cloning (2GB model)")
            except ImportError:
                print("XTTS not installed, falling back to edge (free)")
                self.engine = "edge"
        
        if self.engine == "edge":
            try:
                import edge_tts
                print("✓ Edge TTS available - free, no key, premium FX")
            except ImportError:
                print("edge-tts not installed, falling back to pyttsx3")
                self.engine = "pyttsx3"
        
        if self.engine == "pyttsx3":
            try:
                import pyttsx3
                print("✓ pyttsx3 available - free offline fallback")
            except ImportError:
                print("pyttsx3 not available")
        
        if self.engine == "elevenlabs":
            if not self.elevenlabs_key:
                print(f"⚠️ ElevenLabs engine selected with voice {self.voice_id} but no API key - set ELEVENLABS_API_KEY in .env to use your voice CwhRBWXzGAHq8TQ4Fs17, falling back to piper free for now")
                # Don't fallback immediately if user explicitly wants elevenlabs, keep engine but will fail later with clear message
                # For now fallback to piper to still have voice
                if not os.getenv("ELEVENLABS_API_KEY"):
                    print("Falling back to piper free offline British, Sir. Set ELEVENLABS_API_KEY to use your premium voice CwhRBWXzGAHq8TQ4Fs17")
                    self.engine = "piper"
            else:
                print(f"✓ ElevenLabs available with your voice {self.voice_id} - premium JARVIS voice CwhRBWXzGAHq8TQ4Fs17")
        
        if self.engine == "openai":
            if not self.openai_key:
                print("OpenAI TTS requires API key, falling back to piper free")
                self.engine = "piper"
        
        print(f"✓ Premium TTS ready: {self.engine} + {self.voice_preset_name} + voice {str(self.voice_id)[:30]}")
    
    def _clean_text(self, text: str) -> str:
        import re
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        text = re.sub(r'\[.*?tool.*?\]', '', text, flags=re.IGNORECASE)
        text = text.replace('*', '').replace('#', '').strip()
        if len(text) > 1000:
            text = text[:1000] + " ... and so on, Sir."
        return text.strip()
    
    def _apply_premium_effects(self, audio_path: str) -> str:
        try:
            from pydub import AudioSegment
            from pydub.effects import low_pass_filter
            effects = self.preset.get("effects", {})
            bass_boost = effects.get("bass_boost", 0)
            reverb = effects.get("reverb", 0)
            chorus = effects.get("chorus", 0)
            if bass_boost == 0 and reverb == 0 and chorus == 0:
                return audio_path
            audio = AudioSegment.from_file(audio_path)
            if bass_boost > 0:
                low = low_pass_filter(audio, 250)
                audio = audio.overlay(low + bass_boost)
            if reverb > 0:
                delay_ms = 80
                reverb_audio = audio
                for i in range(1, 3):
                    d = delay_ms * i
                    db_reduction = 12 + (i * 6) - (reverb * 5)
                    echo = AudioSegment.silent(duration=d) + (audio - db_reduction)
                    reverb_audio = reverb_audio.overlay(echo)
                audio = reverb_audio
            if chorus > 0 and chorus > 0.05:
                delay_ms = 15
                chorus_echo = AudioSegment.silent(duration=delay_ms) + (audio - (15 - chorus*10))
                audio = audio.overlay(chorus_echo - 6)
            audio = audio + 1.5
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                new_path = f.name
            audio.export(new_path, format="mp3")
            try:
                os.unlink(audio_path)
            except:
                pass
            return new_path
        except ImportError:
            return audio_path
        except Exception as e:
            print(f"Premium effects failed: {e}")
            return audio_path
    
    def _get_edge_voice(self) -> str:
        """Get correct edge voice, handling piper voice ID incorrectly passed to edge"""
        voice_id = self.voice_id or self.preset["edge_voice"]
        # If voice_id looks like piper (en_GB-... with underscore) or is elevenlabs ID (21 chars alphanumeric), use preset edge
        if "_" in voice_id and "en_GB" in voice_id:
            return self.preset["edge_voice"]
        if len(voice_id) == 21 and voice_id.isalnum():
            # Looks like ElevenLabs ID CwhRBWXzGAHq8TQ4Fs17 (21 chars), not edge voice
            return self.preset["edge_voice"]
        if "Neural" not in voice_id and "_" not in voice_id and len(voice_id) < 5:
            return self.preset["edge_voice"]
        if "en-" in voice_id and "Neural" in voice_id:
            return voice_id
        # Check piper style
        if "_" in voice_id and "-" in voice_id and "en_" in voice_id.lower():
            return self.preset["edge_voice"]
        return voice_id or self.preset["edge_voice"]
    
    def _get_piper_voice(self) -> str:
        """Get correct piper voice, handling edge voice ID incorrectly passed to piper"""
        if self.voice_id and ("en-GB" in self.voice_id or "en-US" in self.voice_id) and "Neural" in self.voice_id:
            return self.preset.get("piper_voice", "en_GB-alan-medium")
        if len(self.voice_id) == 21 and self.voice_id.isalnum():
            # ElevenLabs ID passed to piper, use preset piper
            return self.preset.get("piper_voice", "en_GB-alan-medium")
        if self.voice_id and "_" in self.voice_id and "-" in self.voice_id and "en_" in self.voice_id.lower():
            return self.voice_id
        return self.preset.get("piper_voice", "en_GB-alan-medium")
    
    async def _edge_tts(self, text: str) -> str:
        import edge_tts
        voice = self._get_edge_voice()
        effects = self.preset.get("effects", {})
        speed = effects.get("speed", 1.0)
        rate_percent = int((speed - 1.0) * 100)
        rate_str = f"{rate_percent:+d}%" if rate_percent != 0 else "+0%"
        pitch = effects.get("pitch", 0)
        pitch_str = f"{pitch:+d}Hz" if pitch != 0 else "+0Hz"
        communicate = edge_tts.Communicate(text, voice, rate=rate_str, pitch=pitch_str)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_file = f.name
        await communicate.save(temp_file)
        return self._apply_premium_effects(temp_file)
    
    async def _piper_tts(self, text: str) -> str:
        try:
            import piper
            import wave
            
            piper_voice = self._get_piper_voice()
            model_path = self.piper_models_dir / f"{piper_voice}.onnx"
            config_path = self.piper_models_dir / f"{piper_voice}.onnx.json"
            
            if not model_path.exists() or not config_path.exists():
                print(f"Piper model {piper_voice} not found, auto-downloading free...")
                try:
                    import requests
                    parts = piper_voice.split('-')
                    if len(parts) >= 3:
                        name = parts[1]
                        quality = parts[2]
                        base_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/{name}/{quality}"
                        model_url = f"{base_url}/{piper_voice}.onnx"
                        config_url = f"{base_url}/{piper_voice}.onnx.json"
                        self.piper_models_dir.mkdir(parents=True, exist_ok=True)
                        if not model_path.exists():
                            print(f"Downloading {model_url} (free)...")
                            resp = requests.get(model_url, timeout=30)
                            if resp.status_code == 200:
                                model_path.write_bytes(resp.content)
                                print(f"✓ Downloaded {model_path.name} {len(resp.content)//1024}KB free")
                        if not config_path.exists():
                            resp = requests.get(config_url, timeout=15)
                            if resp.status_code == 200:
                                config_path.write_bytes(resp.content)
                                print(f"✓ Downloaded {config_path.name} free")
                except Exception as e:
                    print(f"Auto-download failed: {e}")
                
                if not model_path.exists() or not config_path.exists():
                    print(f"Piper model still missing, falling back to edge free")
                    return await self._edge_tts(text)
            
            voice = piper.PiperVoice.load(str(model_path), str(config_path))
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_file = f.name
            
            try:
                with wave.open(temp_file, "wb") as wav_file:
                    voice.synthesize(text, wav_file)
            except Exception as e1:
                if "channels" in str(e1).lower() or "not specified" in str(e1).lower():
                    try:
                        import json
                        config_data = json.loads(config_path.read_text())
                        sample_rate = config_data.get("audio", {}).get("sample_rate", 22050)
                        with wave.open(temp_file, "wb") as wav_file:
                            wav_file.setnchannels(1)
                            wav_file.setsampwidth(2)
                            wav_file.setframerate(sample_rate)
                            for chunk in voice.synthesize(text):
                                if hasattr(chunk, 'audio_int16_bytes'):
                                    wav_file.writeframes(chunk.audio_int16_bytes)
                                elif isinstance(chunk, bytes):
                                    wav_file.writeframes(chunk)
                                else:
                                    wav_file.writeframes(bytes(chunk))
                    except Exception as e2:
                        print(f"Piper manual wav failed: {e2}")
                        raise e1
                else:
                    raise e1
            
            return self._apply_premium_effects(temp_file)
        except Exception as e:
            print(f"Piper TTS failed: {e}, falling back to edge free")
            return await self._edge_tts(text)
    
    async def _elevenlabs_tts(self, text: str) -> str:
        """ElevenLabs with YOUR voice CwhRBWXzGAHq8TQ4Fs17 - premium JARVIS voice"""
        if not self.elevenlabs_key:
            raise Exception("ElevenLabs API key not set, set ELEVENLABS_API_KEY in .env to use your voice CwhRBWXzGAHq8TQ4Fs17")
        
        try:
            from elevenlabs import VoiceSettings
            from elevenlabs.client import ElevenLabs
            
            client = ElevenLabs(api_key=self.elevenlabs_key)
            voice_id = self.voice_id
            # If voice_id is not a 21-char ID, use your voice CwhRBWXzGAHq8TQ4Fs17
            if len(voice_id) != 21 or not voice_id.isalnum():
                # Check if it's piper or edge voice, then use your voice
                if "_" in voice_id or "en-" in voice_id.lower():
                    voice_id = "CwhRBWXzGAHq8TQ4Fs17"  # YOUR JARVIS voice
            
            # If still not your voice and env has it, use env
            if os.getenv("ELEVENLABS_VOICE_ID"):
                voice_id = os.getenv("ELEVENLABS_VOICE_ID")
            
            # Final fallback to your voice
            if len(voice_id) != 21:
                voice_id = "CwhRBWXzGAHq8TQ4Fs17"
            
            settings = VoiceSettings(stability=0.75, similarity_boost=0.75, style=0.5, use_speaker_boost=True)
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
            
            return self._apply_premium_effects(temp_file)
        
        except Exception as e:
            print(f"ElevenLabs TTS failed: {e}")
            raise e
    
    async def _xtts_tts(self, text: str) -> str:
        try:
            from TTS.api import TTS
            if not self.xtts_model:
                print("Loading XTTS v2 model (2GB, free, first time)...")
                self.xtts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=False)
            sample_path = None
            for ext in [".wav", ".mp3"]:
                candidate = self.xtts_samples_dir / f"{self.voice_preset_name}{ext}"
                if candidate.exists():
                    sample_path = str(candidate)
                    break
            if not sample_path:
                samples = list(self.xtts_samples_dir.glob("*.wav")) + list(self.xtts_samples_dir.glob("*.mp3"))
                if samples:
                    sample_path = str(samples[0])
            if not sample_path:
                print("No XTTS sample, falling back to edge free")
                return await self._edge_tts(text)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_file = f.name
            self.xtts_model.tts_to_file(text=text, file_path=temp_file, speaker_wav=sample_path, language="en")
            return self._apply_premium_effects(temp_file)
        except Exception as e:
            print(f"XTTS failed: {e}, falling back to edge free")
            return await self._edge_tts(text)
    
    async def _pyttsx3_tts(self, text: str) -> str:
        import pyttsx3
        import time
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_file = f.name
        engine = pyttsx3.init()
        voices = engine.getProperty('voices')
        for v in voices:
            if 'british' in v.name.lower() or 'uk' in v.name.lower():
                engine.setProperty('voice', v.id)
                break
        rate = engine.getProperty('rate')
        speed = self.preset.get("effects", {}).get("speed", 1.0)
        engine.setProperty('rate', int(rate * speed))
        engine.save_to_file(text, temp_file)
        engine.runAndWait()
        time.sleep(0.5)
        return self._apply_premium_effects(temp_file)
    
    async def speak_async(self, text: str) -> str:
        clean = self._clean_text(text)
        if not clean:
            return None
        print(f"🔊 Premium TTS: {self.voice_preset_name} via {self.engine} voice {str(self.voice_id)[:30]}: {clean[:80]}...")
        try:
            if self.engine == "piper":
                return await self._piper_tts(clean)
            elif self.engine == "elevenlabs":
                return await self._elevenlabs_tts(clean)
            elif self.engine == "xtts":
                return await self._xtts_tts(clean)
            elif self.engine == "pyttsx3":
                return await self._pyttsx3_tts(clean)
            else:
                return await self._edge_tts(clean)
        except Exception as e:
            print(f"Premium TTS {self.engine} failed: {e}, falling back to piper free")
            try:
                return await self._piper_tts(clean)
            except:
                try:
                    return await self._edge_tts(clean)
                except Exception as e2:
                    print(f"Edge fallback also failed: {e2}")
                    return None
    
    def speak(self, text: str, blocking: bool = True):
        import threading
        def _play():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                audio_path = loop.run_until_complete(self.speak_async(text))
                loop.close()
                if not audio_path:
                    return
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
                        try:
                            import subprocess
                            subprocess.run(["aplay", audio_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
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
        print("\n🎙️ Voice Presets (Piper FREE default, your ElevenLabs CwhRBWXzGAHq8TQ4Fs17 premium):\n")
        for name, preset in VOICE_PRESETS.items():
            free_badge = "✓ FREE" if preset.get("free") else ""
            print(f"- {name}: {preset['description']} [{free_badge}]")
        print(f"\nYour ElevenLabs voice ID: CwhRBWXzGAHq8TQ4Fs17 (JARVIS premium British)\nEngines:\n- piper: FREE offline British (default, MUST BE PIPER)\n- elevenlabs: YOUR VOICE CwhRBWXzGAHq8TQ4Fs17 premium, needs ELEVENLABS_API_KEY\n- edge: FREE online fallback\n")
    
    def set_preset(self, preset_name: str):
        if preset_name in VOICE_PRESETS:
            self.voice_preset_name = preset_name
            self.preset = VOICE_PRESETS[preset_name]
            print(f"✓ Voice preset set to {preset_name}: {self.preset['description']}")
        else:
            print(f"Preset {preset_name} not found. Available: {list(VOICE_PRESETS.keys())}")


_premium_instance = None

def get_premium_tts(engine: str = None, preset: str = None, voice_id: str = None):
    global _premium_instance
    if _premium_instance is None:
        _premium_instance = PremiumTTS(engine=engine, voice_preset=preset, voice_id=voice_id)
    else:
        if preset:
            _premium_instance.set_preset(preset)
        if engine:
            _premium_instance.engine = engine
        if voice_id:
            _premium_instance.voice_id = voice_id
    return _premium_instance
