"""
Music Player - Manage local or streaming music playback, 100% FREE local
Uses pygame mixer for local playback, no API keys, no paid services

Supports:
- Local files in workspace/music/, ~/Music/, etc
- Play, pause, stop, next, previous, volume
- Playlist management
- Search local library
- Metadata via mutagen (free)
- Smart speaker zones integration
- Streaming: placeholder for Spotify via spotipy (optional, free API but needs key) - but we keep local as primary free
"""

import os
import random
from pathlib import Path
from typing import List, Dict, Optional
import json
from datetime import datetime

from ..config import config


class MusicPlayer:
    def __init__(self, music_dirs: List[Path] = None):
        self.music_dirs = music_dirs or [
            config.WORKSPACE_DIR / "music",
            Path.home() / "Music",
            Path.home() / "music",
            Path.cwd() / "music"
        ]
        
        # Ensure workspace music dir exists
        (config.WORKSPACE_DIR / "music").mkdir(parents=True, exist_ok=True)
        
        self.current_track: Optional[Path] = None
        self.playlist: List[Path] = []
        self.playlist_index = 0
        self.is_playing = False
        self.is_paused = False
        self.volume = 70
        
        # For pygame mixer
        self.mixer_initialized = False
        self._init_mixer()
        
        # Smart speaker zones
        try:
            from .smart_speakers import SmartSpeakerZones
            self.speaker_zones = SmartSpeakerZones()
        except:
            self.speaker_zones = None
    
    def _init_mixer(self):
        try:
            import pygame
            pygame.mixer.init()
            self.mixer_initialized = True
            print("✓ Music player pygame mixer ready - 100% free local playback")
        except Exception as e:
            print(f"Music player mixer init failed: {e} (install: pip install pygame --break-system-packages)")
            self.mixer_initialized = False
    
    def _find_music_files(self, query: str = None, limit: int = 50) -> List[Path]:
        """Find music files in music dirs, optionally filtered by query"""
        music_files = []
        query_lower = query.lower() if query else None
        
        for music_dir in self.music_dirs:
            if not music_dir.exists():
                continue
            try:
                for file in music_dir.rglob("*"):
                    if file.is_file() and file.suffix.lower() in ['.mp3', '.wav', '.flac', '.m4a', '.ogg', '.wma', '.aac']:
                        if query_lower:
                            # Filter by query in filename
                            if query_lower not in file.name.lower() and query_lower not in str(file.parent).lower():
                                continue
                        music_files.append(file)
                        if len(music_files) >= limit:
                            break
            except:
                continue
            if len(music_files) >= limit:
                break
        
        return music_files[:limit]
    
    def list_music(self, query: str = None, limit: int = 20) -> List[Dict]:
        """List music files with metadata"""
        files = self._find_music_files(query=query, limit=limit)
        
        result = []
        for f in files:
            try:
                # Try to get metadata via mutagen
                title = f.stem
                artist = "Unknown"
                try:
                    from mutagen import File as MutagenFile
                    audio = MutagenFile(str(f), easy=True)
                    if audio:
                        if audio.get('title'):
                            title = str(audio.get('title')[0])
                        if audio.get('artist'):
                            artist = str(audio.get('artist')[0])
                except:
                    pass
                
                result.append({
                    "file": str(f),
                    "filename": f.name,
                    "title": title,
                    "artist": artist,
                    "size_mb": round(f.stat().st_size / (1024*1024), 1)
                })
            except:
                result.append({
                    "file": str(f),
                    "filename": f.name,
                    "title": f.stem,
                    "artist": "Unknown",
                    "size_mb": 0
                })
        
        return result
    
    def search_music(self, query: str, limit: int = 10) -> List[Dict]:
        """Search music library"""
        return self.list_music(query=query, limit=limit)
    
    def play(self, query: str = None, file_path: str = None, zone: str = None) -> str:
        """
        Play music - local file or search query
        If query provided, searches and plays first result
        If file_path provided, plays that file
        If zone provided, plays in that smart speaker zone (volume from zone)
        """
        try:
            import pygame
            
            if not self.mixer_initialized:
                self._init_mixer()
                if not self.mixer_initialized:
                    return "Music player mixer not available, Sir. Install pygame: pip install pygame"
            
            # Determine file to play
            target_file = None
            
            if file_path:
                p = Path(file_path)
                if not p.exists():
                    # Try workspace/music
                    p = config.WORKSPACE_DIR / "music" / file_path
                if not p.exists():
                    # Try home music
                    p = Path.home() / "Music" / file_path
                if p.exists() and p.is_file():
                    target_file = p
                else:
                    return f"File not found: {file_path}, Sir. Place music in workspace/music/ or ~/Music/"
            
            elif query:
                # Search
                files = self._find_music_files(query=query, limit=5)
                if not files:
                    return f"No music found for '{query}', Sir. Add MP3s to workspace/music/ or ~/Music/. Currently have {len(self._find_music_files(limit=100))} files total."
                target_file = files[0]
                
                # Build playlist from search results
                self.playlist = files
                self.playlist_index = 0
            else:
                # Play current or first in library
                if self.current_track and self.current_track.exists():
                    target_file = self.current_track
                else:
                    files = self._find_music_files(limit=5)
                    if not files:
                        return f"No music files found, Sir. Add MP3s to workspace/music/ (currently empty) or ~/Music/. Found 0 files."
                    target_file = files[0]
                    self.playlist = files
            
            if not target_file:
                return f"No music to play, Sir. Query: {query}, file: {file_path}"
            
            # Check zone volume if zone specified
            volume = self.volume
            zone_info = ""
            if zone and self.speaker_zones:
                zone_data = self.speaker_zones.get_zone(zone)
                if zone_data:
                    if zone_data.get("muted"):
                        return f"Zone {zone} is muted, Sir. Unmute first."
                    volume = zone_data.get("volume", self.volume)
                    zone_info = f" in zone {zone} (volume {volume}%)"
            
            # Play
            pygame.mixer.music.load(str(target_file))
            pygame.mixer.music.set_volume(volume / 100.0)
            pygame.mixer.music.play()
            
            self.current_track = target_file
            self.is_playing = True
            self.is_paused = False
            
            return f"Playing{zone_info}, Sir: {target_file.name} ({target_file.parent.name}) | Volume {volume}% | {len(self.playlist)} tracks in playlist"
        
        except Exception as e:
            return f"Play failed, Sir: {e}. Install pygame: pip install pygame"
    
    def pause(self) -> str:
        try:
            import pygame
            if not self.is_playing:
                return "Nothing playing to pause, Sir."
            if self.is_paused:
                pygame.mixer.music.unpause()
                self.is_paused = False
                return f"Resumed, Sir: {self.current_track.name if self.current_track else 'music'}"
            else:
                pygame.mixer.music.pause()
                self.is_paused = True
                return f"Paused, Sir: {self.current_track.name if self.current_track else 'music'}"
        except Exception as e:
            return f"Pause failed: {e}"
    
    def stop(self) -> str:
        try:
            import pygame
            pygame.mixer.music.stop()
            self.is_playing = False
            self.is_paused = False
            return f"Stopped, Sir. Last track: {self.current_track.name if self.current_track else 'none'}"
        except Exception as e:
            return f"Stop failed: {e}"
    
    def next_track(self) -> str:
        try:
            if not self.playlist:
                return "No playlist, Sir. Search and play music first."
            
            self.playlist_index = (self.playlist_index + 1) % len(self.playlist)
            next_file = self.playlist[self.playlist_index]
            return self.play(file_path=str(next_file))
        except Exception as e:
            return f"Next track failed: {e}"
    
    def previous_track(self) -> str:
        try:
            if not self.playlist:
                return "No playlist, Sir."
            
            self.playlist_index = (self.playlist_index - 1) % len(self.playlist)
            prev_file = self.playlist[self.playlist_index]
            return self.play(file_path=str(prev_file))
        except Exception as e:
            return f"Previous track failed: {e}"
    
    def set_volume(self, volume: int) -> str:
        try:
            import pygame
            volume = max(0, min(100, volume))
            self.volume = volume
            if self.is_playing and self.mixer_initialized:
                pygame.mixer.music.set_volume(volume / 100.0)
            return f"Volume set to {volume}%, Sir."
        except Exception as e:
            return f"Set volume failed: {e}"
    
    def get_status(self) -> Dict:
        try:
            import pygame
            is_busy = False
            try:
                is_busy = pygame.mixer.music.get_busy() if self.mixer_initialized else False
            except:
                pass
            
            return {
                "is_playing": self.is_playing and is_busy,
                "is_paused": self.is_paused,
                "current_track": str(self.current_track) if self.current_track else None,
                "current_filename": self.current_track.name if self.current_track else None,
                "volume": self.volume,
                "playlist_length": len(self.playlist),
                "playlist_index": self.playlist_index,
                "mixer_initialized": self.mixer_initialized
            }
        except Exception as e:
            return {"error": str(e), "is_playing": False}
    
    def get_overview(self) -> Dict:
        files = self._find_music_files(limit=100)
        total = len(files)
        
        return {
            "total_files": total,
            "music_dirs": [str(d) for d in self.music_dirs if d.exists()],
            "current_track": str(self.current_track) if self.current_track else None,
            "is_playing": self.is_playing,
            "volume": self.volume,
            "playlist_length": len(self.playlist)
        }
