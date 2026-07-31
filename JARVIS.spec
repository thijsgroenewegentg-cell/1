# -*- mode: python ; coding: utf-8 -*-
# JARVIS Singular App - Single .EXE - 100% FREE - RX 9070 XT 16GB Optimized
# Voice MUST BE PIPER by default, YOUR ElevenLabs CwhRBWXzGAHq8TQ4Fs17 optional premium
# Build: pip install pyinstaller && pyinstaller JARVIS.spec --noconfirm
# Output: dist/JARVIS.exe - single file, everything in one, double-click to start

from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files
import os
from pathlib import Path

block_cipher = None

# Collect all jarvis modules
jarvis_datas = []
jarvis_hidden = []

# Collect submodules for hidden imports
for pkg in ['jarvis', 'jarvis.voice', 'jarvis.tools', 'jarvis.learning', 'jarvis.evolution', 'jarvis.coding', 'jarvis.knowledge', 'jarvis.computer', 'jarvis.proactive', 'jarvis.agents', 'jarvis.productivity', 'jarvis.media', 'api', 'config', 'web']:
    try:
        datas, binaries, hidden = collect_all(pkg)
        jarvis_datas += datas
        jarvis_hidden += hidden
    except:
        pass

# Additional hidden imports
hidden_imports = [
    'jarvis.brain',
    'jarvis.config',
    'jarvis.voice.premium',
    'jarvis.voice.wakeword',
    'jarvis.tools',
    'jarvis.learning.vector_store',
    'jarvis.evolution.evolution_engine',
    'jarvis.coding.codebase_rag',
    'jarvis.knowledge.document_rag',
    'jarvis.computer.browser',
    'jarvis.productivity.calendar_hub',
    'jarvis.productivity.email_hub',
    'jarvis.media.music_player',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'edge_tts',
    'pygame',
    'pydub',
    'faster_whisper',
    'speech_recognition',
    'pypdf',
    'docx',
    'playwright',
    'apscheduler',
    'plyer',
    'customtkinter',
    'PIL',
    'pystray',
    'webview',
    'piper',
    'onnxruntime',
    'mutagen',
    'musicbrainzngs',
] + jarvis_hidden

# Data files - include web UI, voices, piper models, etc
datas = [
    ('web', 'web'),
    ('orb/api/templates', 'api/templates'),
    ('orb/api/static', 'api/static'),
    ('orb/config', 'config'),
    ('desktop/icon.png', 'desktop'),
    ('Modelfile', '.'),
    ('Modelfile.9070xt', '.'),
    ('.env.example', '.'),
    ('README.md', '.'),
    ('INSTALL.md', '.'),
]

# Include data dirs if exist
for data_dir in ['data/piper_models', 'data/voices', 'workspace/music', 'workspace/calendar']:
    if Path(data_dir).exists():
        datas.append((data_dir, data_dir))

# Add jarvis datas
datas += jarvis_datas

a = Analysis(
    ['JARVIS.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'torch', 'tensorflow', 'cv2'],  # exclude heavy ML that not needed for basic
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='JARVIS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # True = show black console with logs (like your screenshot), False = windowed no console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='desktop/icon.png' if Path('desktop/icon.png').exists() else None,
)

# For singular app, onefile is enough - everything in one .exe
# User double-clicks JARVIS.exe and it starts:
# - Checks Ollama running, tries to start
# - Indexes codebase in background
# - Starts proactive engine (morning briefing, git watcher)
# - Starts web server at http://localhost:8000 + /holo movable UI
# - Opens browser to /holo automatically
# - System tray icon (close = minimize to tray, stays alive like real JARVIS)
# - Voice MUST BE PIPER by default (100% free offline British), or YOUR ElevenLabs CwhRBWXzGAHq8TQ4Fs17 if API key in .env
# - All 89 tools, second brain, browser computer use, goals, calendar, email, media, team, agent
# - 100% FREE, No API Keys (except optional ElevenLabs for your premium voice CwhRBWXzGAHq8TQ4Fs17)
