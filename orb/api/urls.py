"""
URL routes for orb api - Minimal JARVIS Orb
Single orb visual, no chrome, production-ready endpoints
"""

from django.urls import path
from . import views

urlpatterns = [
    # Frontend - single orb, no chrome
    path('', views.index, name='index'),
    
    # API Endpoints - production-ready, documented, error handling
    # Chat: text processing
    path('api/chat/', views.chat_endpoint, name='chat'),
    
    # TTS: text-to-speech MUST BE PIPER - 100% FREE OFFLINE British premium
    path('api/tts/', views.tts_endpoint, name='tts'),
    
    # STT: speech-to-text faster-whisper free offline
    path('api/stt/', views.stt_endpoint, name='stt'),
    
    # Health check for monitoring
    path('api/health/', views.health_check, name='health'),
]
