"""
API Views for Orb - Minimal JARVIS Orb with Piper TTS (100% FREE)
Production-ready endpoints for text processing, STT, TTS

Endpoints:
- GET / : frontend with orb
- POST /api/chat/ : text processing
- POST /api/tts/ : text-to-speech (Piper MUST BE)
- POST /api/stt/ : speech-to-text (faster-whisper)
- GET /api/health/ : health check
"""

import os
import json
import logging
import tempfile
from pathlib import Path
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.shortcuts import render
from django.conf import settings

logger = logging.getLogger('api')

# Try to import JARVIS brain if available, else fallback
try:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from jarvis.brain import JarvisBrain
    from jarvis.voice.premium import get_premium_tts
    BRAIN_AVAILABLE = True
    logger.info("JARVIS brain and premium TTS available - 100% free Piper")
except Exception as e:
    BRAIN_AVAILABLE = False
    logger.warning(f"JARVIS brain not available, using fallback: {e}")
    JarvisBrain = None
    get_premium_tts = None

# Global brain singleton
_brain = None

def get_brain():
    global _brain
    if _brain is None and BRAIN_AVAILABLE:
        try:
            _brain = JarvisBrain(enable_learning=False, enable_evolution=False)
            logger.info(f"Brain initialized: {_brain.model}")
        except Exception as e:
            logger.error(f"Brain init failed: {e}")
            _brain = None
    return _brain


def index(request):
    """
    Frontend view - Single orb visual, no chrome
    Background simple, design focused entirely on orb
    """
    return render(request, 'api/index.html')


@csrf_exempt
@require_http_methods(["GET"])
def health_check(request):
    """
    Health check endpoint - production-ready monitoring
    
    GET /api/health/
    Response: {"status": "ok", "brain": "available", "tts_engine": "piper", "stt_engine": "faster-whisper"}
    """
    try:
        import ollama
        ollama_available = True
        try:
            import requests
            resp = requests.get(f"{settings.OLLAMA_HOST}/api/tags", timeout=2)
            ollama_available = resp.status_code == 200
        except:
            ollama_available = False
    except:
        ollama_available = False
    
    return JsonResponse({
        "status": "ok",
        "brain": "available" if BRAIN_AVAILABLE else "fallback",
        "ollama": ollama_available,
        "tts_engine": settings.TTS_ENGINE,  # MUST BE PIPER - 100% FREE
        "stt_engine": settings.STT_ENGINE,
        "voice": "piper British premium free offline, Manina style",
        "free": "100% FREE, No API Keys, Fully Local"
    })


@csrf_exempt
@require_http_methods(["POST"])
def chat_endpoint(request):
    """
    Text processing endpoint - core chat
    
    POST /api/chat/
    Request: {"message": "Hello, Jarvis"}
    Response: {"reply": "Good evening, Sir. ...", "model": "jarvis"}
    
    Error handling: empty messages, invalid JSON, timeouts, model failures
    """
    try:
        # Parse JSON
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in chat: {e}")
            return JsonResponse({"error": "Invalid JSON, expected {\"message\": \"...\"}"}, status=400)
        
        message = data.get('message', '').strip()
        
        # Edge case: empty message
        if not message:
            logger.warning("Empty message received")
            return JsonResponse({"error": "Empty message, Sir. Please say something."}, status=400)
        
        # Edge case: too long
        if len(message) > 5000:
            logger.warning(f"Message too long: {len(message)} chars")
            return JsonResponse({"error": "Message too long, max 5000 chars"}, status=400)
        
        logger.info(f"Chat request: {message[:100]}...")
        
        # Process via JARVIS brain if available, else fallback echo
        brain = get_brain()
        reply = None
        model_name = "fallback"
        
        if brain:
            try:
                # Use brain.think with timeout protection
                import signal
                
                # For production, we don't use signal timeout in Django (threaded), just call with try/except and small timeout via requests already handled in brain
                reply = brain.think(message)
                model_name = brain.model
                logger.info(f"Brain reply: {reply[:100]}... (model {model_name})")
            except Exception as e:
                logger.error(f"Brain think failed: {e}, using fallback", exc_info=True)
                # Fallback to simple JARVIS-style responses
                reply = _fallback_chat_reply(message)
                model_name = "fallback"
        else:
            reply = _fallback_chat_reply(message)
        
        if not reply:
            reply = "I'm here, Sir. How may I assist? (Fallback)"
        
        return JsonResponse({
            "reply": reply,
            "model": model_name,
            "free": "100% FREE, Piper TTS, No API Keys"
        })
    
    except Exception as e:
        logger.error(f"Chat endpoint unexpected error: {e}", exc_info=True)
        return JsonResponse({"error": f"Internal error, Sir: {str(e)[:200]}"}, status=500)


def _fallback_chat_reply(message: str) -> str:
    """Fallback chat when Ollama/JARVIS brain not available - simple rule-based but JARVIS style"""
    lower = message.lower()
    
    if any(word in lower for word in ["hello", "hi", "hey jarvis", "wake up"]):
        return "Good evening, Sir. I am JARVIS. Premium voice model online, 100 percent free, fully local. How may I assist?"
    
    if "time" in lower:
        from datetime import datetime
        now = datetime.now()
        return f"It's {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d, %Y')}, Sir. Time to build something amazing."
    
    if "who are you" in lower or "what are you" in lower:
        return "I am J.A.R.V.I.S. — Just A Rather Very Intelligent System. Running on Piper British premium voice, 100% free, offline, no API keys. At your service, Sir."
    
    if "voice" in lower and "piper" in lower:
        return "Voice MUST BE PIPER, Sir. 100% free offline British premium, Manina Labs style deep cinematic with bass boost and reverb. No API keys needed."
    
    if "free" in lower:
        return "Everything here is 100% free, Sir. No API keys, fully local. Ollama brain, Piper TTS British, faster-whisper STT, openWakeWord, all offline. Stark Tower level, Sir."
    
    # Default echo with JARVIS style
    return f"You said: '{message[:200]}', Sir. I am orb — minimal, clean, fully free. How may I assist? Try asking about time, voice, or say hello."


@csrf_exempt
@require_http_methods(["POST"])
def tts_endpoint(request):
    """
    Text-to-Speech synthesis - MUST BE PIPER - 100% FREE OFFLINE British premium
    
    POST /api/tts/
    Request: {"text": "Good evening Sir"} or form {"text": "..."} with optional {"engine": "piper", "preset": "manina_premium"}
    Response: audio file (audio/mpeg) or JSON {"error": "..."} 
    
    Error handling: empty text, invalid format, TTS engine failures, timeouts
    Supports: piper (MUST, best free offline), edge (free online fallback with FX), xtts (free clone), pyttsx3 (free offline fallback)
    """
    try:
        # Parse request - support both JSON and form
        text = ""
        engine = "piper"  # MUST BE PIPER
        preset = "manina_premium"
        
        if request.content_type and 'application/json' in request.content_type:
            try:
                data = json.loads(request.body)
                text = data.get('text', '').strip()
                engine = data.get('engine', 'piper')
                preset = data.get('preset', 'manina_premium')
            except json.JSONDecodeError:
                return JsonResponse({"error": "Invalid JSON, expected {\"text\": \"...\"}"}, status=400)
        else:
            # Form or query param
            text = request.POST.get('text', '').strip() or request.GET.get('text', '').strip()
            engine = request.POST.get('engine', 'piper')
            preset = request.POST.get('preset', 'manina_premium')
        
        # Edge case: empty text
        if not text:
            logger.warning("TTS empty text")
            return JsonResponse({"error": "Empty text for TTS, Sir. Provide {\"text\": \"...\"}"}, status=400)
        
        # Edge case: too long (limit for real-time)
        if len(text) > 2000:
            logger.warning(f"TTS text too long: {len(text)}")
            return JsonResponse({"error": "Text too long for TTS, max 2000 chars"}, status=400)
        
        logger.info(f"TTS request: engine={engine}, preset={preset}, text={text[:80]}... (MUST BE PIPER FREE)")
        
        # Enforce MUST BE PIPER for free compliance, but allow edge fallback
        if engine not in ['piper', 'edge', 'xtts', 'pyttsx3']:
            logger.warning(f"Invalid TTS engine {engine}, forcing piper (MUST BE)")
            engine = 'piper'
        
        # Try to generate TTS via premium TTS (piper must)
        audio_path = None
        try:
            if BRAIN_AVAILABLE and get_premium_tts:
                import asyncio
                tts = get_premium_tts(engine=engine, preset=preset)
                
                # Generate async
                loop = None
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    audio_path = loop.run_until_complete(tts.speak_async(text))
                except Exception as e:
                    logger.error(f"TTS async generation failed: {e}", exc_info=True)
                    # Try sync fallback via edge if piper fails
                    if engine == 'piper':
                        logger.info("Piper failed, trying edge fallback (still free)")
                        try:
                            tts_edge = get_premium_tts(engine='edge', preset=preset)
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            audio_path = loop.run_until_complete(tts_edge.speak_async(text))
                        except Exception as e2:
                            logger.error(f"Edge fallback also failed: {e2}", exc_info=True)
                            audio_path = None
                finally:
                    if loop:
                        try:
                            loop.close()
                        except:
                            pass
            else:
                # Fallback: try edge-tts directly if premium not available
                logger.info("Premium TTS not available, trying edge-tts direct (free)")
                try:
                    import edge_tts
                    import tempfile
                    import asyncio
                    
                    async def edge_direct():
                        communicate = edge_tts.Communicate(text, "en-GB-RyanNeural")
                        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                            temp_path = f.name
                        await communicate.save(temp_path)
                        return temp_path
                    
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    audio_path = loop.run_until_complete(edge_direct())
                    loop.close()
                except Exception as e:
                    logger.error(f"Edge direct fallback failed: {e}")
                    audio_path = None
        
        except Exception as e:
            logger.error(f"TTS generation outer failed: {e}", exc_info=True)
            return JsonResponse({"error": f"TTS generation failed, Sir: {str(e)[:300]}. Ensure piper model exists: data/piper_models/en_GB-alan-medium.onnx"}, status=500)
        
        if not audio_path or not Path(audio_path).exists():
            logger.error("TTS audio file not generated")
            return JsonResponse({"error": "TTS failed to generate audio, Sir. Check piper model exists in data/piper_models/ or try engine=edge (free)"}, status=500)
        
        # Return audio file
        try:
            # Determine content type
            suffix = Path(audio_path).suffix.lower()
            content_type = "audio/mpeg" if suffix == ".mp3" else "audio/wav"
            
            response = FileResponse(open(audio_path, 'rb'), content_type=content_type)
            response['Content-Disposition'] = f'inline; filename="jarvis-piper-{preset}.mp3"'
            # Cleanup after response? For production, we should delete temp file after. We'll use close callback via FileResponse - it doesn't auto-delete, so we need to handle.
            # For simplicity, return file and let OS clean temp via periodic cleanup, or use tempfile that auto-deletes? We'll leave for now, but log.
            logger.info(f"TTS success: {audio_path}, preset {preset}, engine {engine} (MUST BE PIPER FREE)")
            
            # Schedule deletion after response? In Django, FileResponse doesn't delete. We'll delete in a background thread after delay.
            import threading
            def cleanup():
                import time
                time.sleep(10)
                try:
                    Path(audio_path).unlink(missing_ok=True)
                except:
                    pass
            threading.Thread(target=cleanup, daemon=True).start()
            
            return response
        
        except Exception as e:
            logger.error(f"TTS file response failed: {e}", exc_info=True)
            return JsonResponse({"error": f"Failed to return audio, Sir: {e}"}, status=500)
    
    except Exception as e:
        logger.error(f"TTS endpoint unexpected error: {e}", exc_info=True)
        return JsonResponse({"error": f"Internal TTS error, Sir: {str(e)[:300]}"}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def stt_endpoint(request):
    """
    Speech-to-Text - faster-whisper free offline
    
    POST /api/stt/
    Request: multipart/form-data with file field "audio" (webm, wav, mp3, m4a, ogg) OR JSON base64 {"audio_base64": "...", "format": "webm"}
    Response: {"transcript": "Hello Jarvis", "engine": "faster-whisper"}
    
    Error handling: no audio, unsupported format, too large, STT failures, timeouts
    Supports: faster-whisper (free offline), SpeechRecognition google fallback
    """
    try:
        audio_file_path = None
        temp_files_to_clean = []
        
        # Check multipart file upload
        if 'audio' in request.FILES:
            uploaded = request.FILES['audio']
            
            # Edge case: empty file
            if uploaded.size == 0:
                logger.warning("STT empty audio file")
                return JsonResponse({"error": "Empty audio file, Sir."}, status=400)
            
            # Edge case: too large (10MB limit via settings, but double-check)
            if uploaded.size > 10 * 1024 * 1024:
                logger.warning(f"STT audio too large: {uploaded.size}")
                return JsonResponse({"error": "Audio too large, max 10MB, Sir."}, status=400)
            
            # Save to temp
            suffix = Path(uploaded.name).suffix.lower() if uploaded.name else ".webm"
            # Validate format
            allowed = ['.wav', '.mp3', '.mp3', '.webm', '.ogg', '.m4a', '.mp4', '.flac', '.aac']
            if suffix not in allowed:
                logger.warning(f"STT unsupported format: {suffix}, trying anyway")
                # Still try, whisper can handle many formats
            
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                for chunk in uploaded.chunks():
                    f.write(chunk)
                audio_file_path = f.name
                temp_files_to_clean.append(audio_file_path)
            
            logger.info(f"STT received file: {uploaded.name}, size {uploaded.size}, saved to {audio_file_path}")
        
        elif request.content_type and 'application/json' in request.content_type:
            # JSON base64
            try:
                data = json.loads(request.body)
                audio_b64 = data.get('audio_base64', '')
                audio_format = data.get('format', 'webm')
                
                if not audio_b64:
                    return JsonResponse({"error": "No audio_base64 in JSON, Sir. Provide multipart 'audio' file or base64."}, status=400)
                
                import base64
                try:
                    audio_bytes = base64.b64decode(audio_b64)
                except Exception as e:
                    logger.warning(f"STT base64 decode failed: {e}")
                    return JsonResponse({"error": "Invalid base64 audio"}, status=400)
                
                if len(audio_bytes) == 0:
                    return JsonResponse({"error": "Empty audio after base64 decode"}, status=400)
                
                if len(audio_bytes) > 10 * 1024 * 1024:
                    return JsonResponse({"error": "Audio too large after decode, max 10MB"}, status=400)
                
                suffix = f".{audio_format}" if not audio_format.startswith('.') else audio_format
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                    f.write(audio_bytes)
                    audio_file_path = f.name
                    temp_files_to_clean.append(audio_file_path)
                
                logger.info(f"STT received base64 audio, format {audio_format}, size {len(audio_bytes)}, saved to {audio_file_path}")
            
            except json.JSONDecodeError:
                return JsonResponse({"error": "Invalid JSON for STT"}, status=400)
        
        else:
            # No audio field
            logger.warning("STT no audio file or base64")
            return JsonResponse({"error": "No audio file provided, Sir. Send multipart form with field 'audio' or JSON with 'audio_base64'."}, status=400)
        
        if not audio_file_path:
            return JsonResponse({"error": "Failed to save audio temp file"}, status=500)
        
        # Transcribe via faster-whisper (free offline) or fallback
        transcript = None
        engine_used = "unknown"
        
        try:
            # Try faster-whisper
            from faster_whisper import WhisperModel
            import os
            
            model_size = os.getenv("WHISPER_MODEL", "base")  # base is good balance, tiny faster
            logger.info(f"STT using faster-whisper {model_size} (free offline)")
            
            # Use tiny/base for real-time
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            segments, info = model.transcribe(audio_file_path, beam_size=5, language="en", vad_filter=True)
            text = " ".join([seg.text for seg in segments]).strip()
            
            if text:
                transcript = text
                engine_used = f"faster-whisper-{model_size}"
                logger.info(f"STT success via {engine_used}: {transcript[:100]}...")
            else:
                logger.warning("STT faster-whisper returned empty")
        
        except ImportError:
            logger.warning("faster-whisper not installed, trying SpeechRecognition")
        except Exception as e:
            logger.error(f"faster-whisper STT failed: {e}", exc_info=True)
        
        # Fallback to SpeechRecognition if faster-whisper failed or empty
        if not transcript:
            try:
                import speech_recognition as sr
                logger.info("STT fallback to SpeechRecognition (free)")
                r = sr.Recognizer()
                with sr.AudioFile(audio_file_path) as source:
                    audio_data = r.record(source)
                
                # Try google (free but online, no key), then sphinx offline
                try:
                    transcript = r.recognize_google(audio_data)
                    engine_used = "google-speech-recognition"
                    logger.info(f"STT google fallback success: {transcript[:100]}")
                except Exception as e:
                    logger.warning(f"Google STT failed: {e}, trying sphinx offline")
                    try:
                        transcript = r.recognize_sphinx(audio_data)
                        engine_used = "sphinx-offline"
                    except Exception as e2:
                        logger.error(f"Sphinx offline also failed: {e2}")
                        transcript = None
            
            except ImportError:
                logger.error("SpeechRecognition not installed")
            except Exception as e:
                logger.error(f"SpeechRecognition fallback failed: {e}", exc_info=True)
        
        # Cleanup temp files
        for tf in temp_files_to_clean:
            try:
                Path(tf).unlink(missing_ok=True)
            except:
                pass
        
        if not transcript or not transcript.strip():
            logger.warning("STT returned empty transcript")
            return JsonResponse({"error": "Could not transcribe audio, Sir. Try again, speak clearer, or check audio format (wav, webm, mp3 supported).", "engine": engine_used}, status=400)
        
        return JsonResponse({
            "transcript": transcript.strip(),
            "engine": engine_used,
            "free": "100% FREE, faster-whisper offline, no API keys"
        })
    
    except Exception as e:
        logger.error(f"STT endpoint unexpected error: {e}", exc_info=True)
        return JsonResponse({"error": f"Internal STT error, Sir: {str(e)[:300]}"}, status=500)
