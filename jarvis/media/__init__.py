"""
Media & Entertainment Hub - Manage local or streaming music playback, adjust smart speaker zones, fetch media metadata
100% FREE, local, no API keys needed (except optional streaming services)
"""

from .music_player import MusicPlayer
from .smart_speakers import SmartSpeakerZones
from .media_metadata import MediaMetadata

__all__ = ["MusicPlayer", "SmartSpeakerZones", "MediaMetadata"]
