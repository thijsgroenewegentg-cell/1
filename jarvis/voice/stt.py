"""
Speech To Text for JARVIS - Offline via faster-whisper
"""
import os
import tempfile
import queue
from ..config import config

class SpeechToText:
    def __init__(self, engine: str = None):
        self.engine = engine or config.STT_ENGINE
        self.recognizer = None
        self.whisper_model = None
        self._init_engine()
    
    def _init_engine(self):
        if self.engine in ["google", "sphinx"]:
            try:
                import speech_recognition as sr
                self.recognizer = sr.Recognizer()
                self.recognizer.energy_threshold = 300
                self.recognizer.dynamic_energy_threshold = True
                print(f"✓ STT: SpeechRecognition ({self.engine}) ready")
            except ImportError:
                print("SpeechRecognition not installed")
        elif self.engine == "faster-whisper":
            try:
                from faster_whisper import WhisperModel
                # Use tiny or base for speed, small for accuracy
                model_size = os.getenv("WHISPER_MODEL", "base")
                print(f"Loading faster-whisper model: {model_size}...")
                self.whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
                import speech_recognition as sr
                self.recognizer = sr.Recognizer()
                print(f"✓ STT: faster-whisper ({model_size}) ready")
            except ImportError as e:
                print(f"faster-whisper not available: {e}, falling back to google")
                self.engine = "google"
                self._init_engine()
            except Exception as e:
                print(f"Whisper init failed: {e}, falling back")
                self.engine = "google"
                self._init_engine()
    
    def listen(self, timeout: int = 5, phrase_timeout: int = 3) -> str:
        """Listen for audio and return text"""
        if not self.recognizer:
            return ""
        
        try:
            import speech_recognition as sr
            with sr.Microphone() as source:
                print("🎤 Listening...")
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                try:
                    audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_timeout+5)
                except sr.WaitTimeoutError:
                    return ""
                
                print("🧠 Transcribing...")
                
                if self.engine == "faster-whisper" and self.whisper_model:
                    # Save temp wav
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                        f.write(audio.get_wav_data())
                        temp_path = f.name
                    
                    try:
                        segments, info = self.whisper_model.transcribe(temp_path, beam_size=5, language="en")
                        text = " ".join([seg.text for seg in segments]).strip()
                        os.unlink(temp_path)
                        return text
                    except Exception as e:
                        print(f"Whisper transcribe error: {e}")
                        os.unlink(temp_path)
                        # fallback to google
                        return self.recognizer.recognize_google(audio)
                
                elif self.engine == "google":
                    try:
                        return self.recognizer.recognize_google(audio)
                    except sr.UnknownValueError:
                        return ""
                    except Exception as e:
                        print(f"Google STT error: {e}")
                        return ""
                else:
                    # sphinx offline
                    try:
                        return self.recognizer.recognize_sphinx(audio)
                    except:
                        return ""
        except ImportError:
            print("pyaudio / SpeechRecognition not installed")
            return ""
        except Exception as e:
            print(f"STT error: {e}")
            return ""
    
    def listen_for_wake_word(self, wake_word: str = None) -> bool:
        """Continuous listen for wake word"""
        wake_word = (wake_word or config.WAKE_WORD).lower()
        text = self.listen(timeout=10, phrase_timeout=2)
        if not text:
            return False
        print(f"Heard: {text}")
        return wake_word in text.lower()
    
    def text_input_fallback(self, prompt: str = "You: ") -> str:
        """If no mic, use text"""
        return input(prompt)

# Singleton
_stt_instance = None
def get_stt():
    global _stt_instance
    if _stt_instance is None:
        _stt_instance = SpeechToText()
    return _stt_instance
