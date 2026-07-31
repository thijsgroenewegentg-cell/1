# JARVIS Orb — Minimal Single-Visual App — Piper Voice MUST BE — 100% FREE

> Single orb as only visual element. No panels, controls, menus, or UI chrome. Background simple, design focused entirely on orb. Fully free, local, no API keys, Piper British premium.

![Free](https://img.shields.io/badge/100%25%20FREE-No_API_Keys-black) ![Piper](https://img.shields.io/badge/Voice-MUST_BE_PIPER-blue) ![Django](https://img.shields.io/badge/Backend-Django-green)

---

## Overview

A production-ready Django web application featuring a **single animated orb** that responds to user input via text or voice. Minimal, clean, fully free.

- **Orb as only visual:** No panels, controls, menus, UI chrome. Just orb.
- **Idle animation:** Gentle breathing (scale sin 0.98-1.02) + slow floating (translateY sin) + slow rotation. Never completely still, like living orb.
- **Speaking animation:** Pulses grows/shrinks rhythmically with intensity varying based on speech intensity via Web Audio API AnalyserNode.
- **Text mode:** User types in minimal transparent input box always present but invisible (opacity 0.02), backend `/api/chat/` processes, orb animates while speaking response via Piper TTS.
- **Voice mode:** Backend listens in background continuously via Web Speech API continuous SpeechRecognition + MediaRecorder fallback to `/api/stt/` (faster-whisper free offline). User speaks, backend processes, orb animates while playing audio response.

Background simple radial gradient, design focused entirely on orb.

---

## Quick Start

```bash
# Clone this repo's orb folder (already in /home/user/1/orb if you are in main JARVIS repo)
cd orb

# 1. Python env
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# 2. Install deps - 100% FREE, no keys
pip install -r ../requirements.txt  # or pip install django requests python-dotenv psutil edge-tts pygame pydub SpeechRecognition faster-whisper
pip install django  # if not in requirements

# 3. Piper voice MUST BE - 100% free offline British premium, Manina Labs style
pip install piper-tts
python -m piper.download_voices en_GB-alan-medium --data-dir ../data/piper_models
# Or manual:
# mkdir -p ../data/piper_models
# wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx -P ../data/piper_models/
# wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json -P ../data/piper_models/

# 4. Ollama (optional but recommended, free local LLM)
# Install from https://ollama.com
# ollama serve in another terminal
# ollama pull qwen2.5:7b
# ollama create jarvis -f ../Modelfile  # or Modelfile.9070xt for RX 9070 XT 16GB

# 5. Migrate (SQLite)
python manage.py migrate --noinput

# 6. Run
python manage.py runserver 0.0.0.0:8000
# Open http://localhost:8000/ - single orb, no chrome
```

That's it. No API keys. Piper voice is free offline, not ElevenLabs/OpenAI.

---

## Dependencies

**All 100% FREE, No API Keys, Fully Local:**

- **Backend:** `django>=5.0`, `requests`, `python-dotenv`, `psutil`
- **TTS MUST BE PIPER:** `piper-tts` (best free offline British, local ONNX), `edge-tts` (free online fallback with premium FX bass+reverb via `pydub`), `pygame` (playback), `pydub` (premium FX), `pyttsx3` (fallback)
- **STT:** `faster-whisper` (free offline, tiny/base for real-time), `SpeechRecognition`, `openwakeword` optional for wake word
- **Optional:** `ollama` Python package for brain if you want smarter replies, else fallback rule-based JARVIS style

**Env vars (optional, all have defaults, no keys needed):**

```
DJANGO_SECRET_KEY=... (default insecure for dev)
DJANGO_DEBUG=True
ALLOWED_HOSTS=*
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=jarvis
TTS_ENGINE=piper  # MUST BE PIPER - free offline British
TTS_VOICE=en_GB-alan-medium
STT_ENGINE=faster-whisper
LOG_LEVEL=INFO
```

No `ELEVENLABS_API_KEY`, no `OPENAI_API_KEY` needed. Fully free.

---

## Backend Endpoints — Production-Ready, Documented

All endpoints have error handling for invalid input, API failures, edge cases (empty messages, network timeouts, unsupported audio formats), logging, and user-facing messages.

### GET /
- **Purpose:** Frontend - single orb visual, no chrome
- **Response:** HTML with Canvas orb, invisible transparent input, Web Audio API animation
- **No auth, no params**

### GET /api/health/
- **Purpose:** Health check for monitoring
- **Request:** None
- **Response 200:**
```json
{
  "status": "ok",
  "brain": "available|fallback",
  "ollama": true|false,
  "tts_engine": "piper",
  "stt_engine": "faster-whisper",
  "voice": "piper British premium free offline, Manina style",
  "free": "100% FREE, No API Keys, Fully Local"
}
```

### POST /api/chat/
- **Purpose:** Text processing - user message -> JARVIS reply
- **Request:**
```json
{
  "message": "Hello, Jarvis"
}
```
- **Validation:** message required, trimmed, 1-5000 chars. Empty -> 400, too long -> 400, invalid JSON -> 400
- **Processing:** Tries JARVIS brain (Ollama) if available (with timeout), else fallback rule-based JARVIS style. See `views.py:_fallback_chat_reply()` for simple time, who are you, voice, free queries.
- **Response 200:**
```json
{
  "reply": "Good evening, Sir. I am JARVIS...",
  "model": "jarvis|fallback",
  "free": "100% FREE, Piper TTS, No API Keys"
}
```
- **Error 400:** `{"error": "Empty message, Sir..."}`
- **Error 500:** `{"error": "Internal error, Sir: ..."}`
- **Logging:** INFO for request, ERROR with exc_info for failures

### POST /api/tts/
- **Purpose:** Text-to-Speech synthesis - MUST BE PIPER, 100% FREE OFFLINE British premium
- **Request (JSON):**
```json
{
  "text": "Good evening, Sir",
  "engine": "piper",
  "preset": "manina_premium"
}
```
- **Request (Form):** `text=...&engine=piper&preset=manina_premium`
- **Validation:** text required, 1-2000 chars for real-time, empty -> 400, too long -> 400, invalid engine -> fallback to piper
- **Processing:**
  - `engine`: piper (MUST, best free offline British, local ONNX, auto-downloads model from HuggingFace free if missing), edge (free online Microsoft with premium FX bass boost+reverb+chorus via pydub), xtts (free local cloning, 2GB), pyttsx3 (fallback)
  - `preset`: manina_premium (deep British cinematic reverb 0.32 bass 6), jarvis_classic (Paul Bettany), jarvis_deep, friday, manina_blender - all free
  - FX: `pydub` low_pass_filter 250Hz overlay for bass, echo 80ms decay for reverb, 15ms detune for chorus, +1.5dB
  - Returns audio file, cleans temp file after 10s via background thread
- **Response 200:** `audio/mpeg` or `audio/wav` binary, `Content-Disposition: inline; filename="jarvis-piper-manina_premium.mp3"`
- **Error 400:** `{"error": "Empty text for TTS, Sir..."}`
- **Error 500:** `{"error": "TTS generation failed, Sir: ... Check piper model exists in data/piper_models/"}`
- **Logging:** INFO for request, ERROR for failures

### POST /api/stt/
- **Purpose:** Speech-to-Text - faster-whisper free offline
- **Request (multipart):** FormData with field `audio` file: webm, wav, mp3, m4a, ogg, flac, aac - max 10MB
- **Request (JSON):** `{"audio_base64": "base64...", "format": "webm"}`
- **Validation:** no audio -> 400, empty file -> 400, too large >10MB -> 400, unsupported format warning but tries anyway
- **Processing:**
  - Try faster-whisper (base/tiny, cpu int8, beam 5, vad_filter) - free offline
  - Fallback to SpeechRecognition google (free online, no key) -> sphinx offline
  - Cleans temp files
  - Returns empty transcript -> 400 with user-friendly message
- **Response 200:**
```json
{
  "transcript": "Hello Jarvis",
  "engine": "faster-whisper-base",
  "free": "100% FREE, faster-whisper offline, no API keys"
}
```
- **Error 400:** `{"error": "No audio file provided, Sir...", "engine": "..."}` or `{"error": "Could not transcribe audio, Sir. Try again..."}`
- **Error 500:** `{"error": "Internal STT error, Sir: ..."}`
- **Logging:** INFO for file received, WARNING for empty, ERROR for failures

**All endpoints:**
- CSRF exempt for API (production: add token or use API gateway)
- Require POST/GET methods enforced
- Logging to console + file `orb.log`
- Timeouts: Ollama 20s for chat, 15s for STT/briefing, 10MB max upload
- User-facing messages include "Sir" JARVIS style, not raw stack traces

---

## Frontend — Modern Vanilla JS + Canvas

**Framework:** Vanilla JavaScript with Canvas/WebGL (no React/Vue to keep minimal, single visual element, no chrome, production-ready, no build step)

**Orb Rendering (Canvas 2D):**

- **Idle animation:** Gentle breathing + slow floating + rotation, rather than staying completely still
  - `breathingScale = 0.98 + sin(breathPhase) * 0.02` (0.98-1.02 scale)
  - `floatingY = sin(floatPhase) * 10px`
  - `rotation += 0.002` slow rotation
  - `breathPhase += 0.015`, `floatPhase += 0.005` per frame (~60fps) = smooth continuous
  - Never completely still, like living orb

- **Speaking animation:** Pulses grows/shrinks rhythmically with intensity varying based on speech intensity
  - Web Audio API `AnalyserNode` -> `getByteFrequencyData()` -> average volume 0-255 -> intensity 0-1: `targetIntensity = min(1, (avg/90)*1.2)`
  - Smooth lerp: `speakIntensity += (targetIntensity - speakIntensity) * 0.15`
  - Orb scale: `baseRadius * breathingScale * (1 + intensity * 0.4)` → grows 40% max with loud speech
  - Pulsing: `pulseScale = sin(Date.now()*0.015) * intensity * 0.12` → rapid pulse scaled by intensity, more intense when loud
  - Final radius: `currentRadius * (1 + pulseScale)`

- **Visuals:**
  - Outer glow: radial gradient `rgba(0,212,255, glowIntensity)` where `glowIntensity = 0.15 + intensity*0.35`, radius `2.2 + intensity*0.8` times base
  - Second glow purple `rgba(124,58,237, 0.08 + intensity*0.15)` for Manina holographic
  - Main body: radial gradient from white center (intensity makes whiter) to deep blue edge, with rotation
  - Inner highlight white spot for 3D
  - Outer ring cyan border `rgba(0,212,255, 0.3 + intensity*0.5)` width `1 + intensity*2`
  - Inner core bright center grows with intensity `coreSize = finalRadius * (0.15 + intensity*0.1)`

- **Responsive:** Canvas size `85vmin`, max 400px, resize handler with DPR scaling, mobile 300px

**Text Input:**
- Minimal transparent input box always present but invisible/visually hidden
- CSS: `position: fixed; bottom: 8%; left: 50%; transform: translateX(-50%); width: 420px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.04); opacity: 0.02; backdrop-filter: blur(12px);`
- `:focus { opacity: 0.15; }`, `:hover { opacity: 0.06; }`
- Always present in DOM, always focused via `setInterval(keepInputFocused, 2000)` and `input.focus()` on load, but invisible
- On Enter: send to `/api/chat/`, backend processes, orb animates while speaking response via TTS
- Edge cases: empty trimmed -> error toast, too long handled by backend

**Voice Input:**
- Backend listens in background continuously
- Frontend: Web Speech API `SpeechRecognition` continuous if available (`continuous: true`, `lang: en-US`, auto-restart onend after 500ms)
- Visual: `#status-dot` tiny 8px top right, gray idle, cyan glowing when listening, white when speaking, red on error — minimal, not chrome
- On result final: transcript -> `/api/chat/` -> reply -> TTS -> orb animates
- Fallback: MediaRecorder for STT via backend `/api/stt/` (100% free faster-whisper)
  - Click orb to trigger MediaRecorder if Web Speech API not supported
  - Long-press orb 600ms for MediaRecorder (mobile friendly)
  - Records 5s max, sends multipart `audio` webm to `/api/stt/`, gets transcript, then chat
- Page visibility handling: pause recognition when hidden to save battery, resume when visible

**Text-to-Speech Integration:**
- Primary: backend `/api/tts/` (Piper MUST BE, 100% free offline British premium) returns mp3 blob, played via Web Audio API with AnalyserNode for intensity-based animation scaling
- Fallback: Web Speech API SpeechSynthesis (free built-in browser) British voice if backend TTS fails, with fake intensity pulsing via random
- Analyser: `audioContext.createMediaElementSource(audio)` -> `analyser` -> `analyser.connect(destination)`, loop `getByteFrequencyData` to compute avg volume -> `targetIntensity`

**Background:**
- Simple radial gradient `radial-gradient(ellipse at center, #0a0e14 0%, #040506 70%)`, no panels, design focused entirely on orb

**Responsive & Smooth Animations:**
- `requestAnimationFrame(animate)` for 60fps smooth
- Lerp for intensity decay
- CSS transitions for status dot, error toast
- Mobile: orb 300px, input 90vw, bottom 5%

**Error Handling User-Facing:**
- `showError(msg)` → minimal toast bottom center, red dashed border, 4s auto-hide, status dot red 2s
- Network offline: `Offline, Sir. Check internet - but Piper TTS is offline, so voice still works locally.`
- Backend down: `Chat failed: ...` with slice of error
- Empty message, STT empty, TTS failed, mic permission denied → all user-friendly with "Sir" JARVIS style

---

## How to Run Locally

```bash
cd orb
python3 -m venv venv
source venv/bin/activate
pip install -r ../requirements.txt
pip install django  # if not in requirements
pip install piper-tts  # for Piper MUST BE
python -m piper.download_voices en_GB-alan-medium --data-dir ../data/piper_models

python manage.py migrate
python manage.py runserver 0.0.0.0:8000
# Open http://localhost:8000/
# Single orb, no chrome, type anywhere (invisible input focused), or allow mic and say "Jarvis" for voice mode
```

For RX 9070 XT 16GB, Ollama optional:
```bash
ollama serve &
ollama pull qwen2.5:14b
ollama create jarvis -f ../Modelfile.9070xt --force
```

Then chat will use smarter brain.

---

## Code Conventions

- Django conventions: apps.py, views.py, urls.py, settings with env vars, logging, CSRF exempt for API (production: add auth), SQLite
- Docstrings for all endpoints with request/response formats
- Inline comments for animation logic, idle vs speaking, STT/TTS integration, intensity scaling, non-obvious backend processing
- Error handling with try/except, logging with exc_info, user-facing messages not stack traces
- Production-ready: file upload limits 10MB, timeouts, temp file cleanup background thread, content-type checks, size checks

---

## 100% FREE — No API Keys

Everything free:

- **TTS MUST BE PIPER**: `piper-tts` local ONNX British `en_GB-alan-medium`, auto-downloads from HuggingFace free, premium FX via `pydub` free (bass boost low-pass 250Hz overlay, reverb echo 80ms, chorus 15ms detune)
- **STT**: `faster-whisper` tiny/base free offline, `SpeechRecognition` google fallback free no key, sphinx offline
- **Chat**: Ollama free local or fallback rule-based
- **Frontend**: Web Speech API built-in browser free, Web Audio API free

Optional paid NOT needed: ElevenLabs, OpenAI — we don't use.

---

At your service, Sir. Single orb, no chrome, Piper British premium, fully free.
