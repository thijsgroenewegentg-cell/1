"""
Media & Entertainment Tools - Music playback, smart speaker zones, media metadata
100% FREE, local, no API keys needed
"""

from ..config import config

# Lazy singletons
_music_player = None
_speaker_zones = None
_media_metadata = None

def _get_music():
    global _music_player
    if _music_player is None:
        try:
            from ..media import MusicPlayer
            _music_player = MusicPlayer()
        except Exception as e:
            print(f"MusicPlayer not available: {e}")
    return _music_player

def _get_speakers():
    global _speaker_zones
    if _speaker_zones is None:
        try:
            from ..media import SmartSpeakerZones
            _speaker_zones = SmartSpeakerZones()
        except Exception as e:
            print(f"SmartSpeakerZones not available: {e}")
    return _speaker_zones

def _get_metadata():
    global _media_metadata
    if _media_metadata is None:
        try:
            from ..media import MediaMetadata
            _media_metadata = MediaMetadata()
        except Exception as e:
            print(f"MediaMetadata not available: {e}")
    return _media_metadata


# Music Playback Tools

def play_music(query: str = None, file_path: str = None, zone: str = None) -> str:
    try:
        player = _get_music()
        if not player:
            return "Music player not available, Sir. Install pygame: pip install pygame --break-system-packages"
        
        return player.play(query=query, file_path=file_path, zone=zone)
    except Exception as e:
        return f"Play music failed: {e}"


def pause_music() -> str:
    try:
        player = _get_music()
        if not player:
            return "Music player not available"
        return player.pause()
    except Exception as e:
        return f"Pause failed: {e}"


def stop_music() -> str:
    try:
        player = _get_music()
        if not player:
            return "Music player not available"
        return player.stop()
    except Exception as e:
        return f"Stop failed: {e}"


def next_track() -> str:
    try:
        player = _get_music()
        if not player:
            return "Music player not available"
        return player.next_track()
    except Exception as e:
        return f"Next track failed: {e}"


def previous_track() -> str:
    try:
        player = _get_music()
        if not player:
            return "Music player not available"
        return player.previous_track()
    except Exception as e:
        return f"Previous track failed: {e}"


def set_volume(volume: int) -> str:
    try:
        player = _get_music()
        if not player:
            return "Music player not available"
        return player.set_volume(volume=volume)
    except Exception as e:
        return f"Set volume failed: {e}"


def list_music(query: str = None, limit: int = 10) -> str:
    try:
        player = _get_music()
        if not player:
            return "Music player not available"
        
        tracks = player.list_music(query=query, limit=limit)
        
        if not tracks:
            return f"No music found{' for '+query if query else ''}, Sir. Add MP3s to workspace/music/ or ~/Music/. Found 0 files."
        
        output = [f"Music library ({len(tracks)} tracks){' for '+query if query else ''}, Sir:\n"]
        for i, t in enumerate(tracks, 1):
            output.append(f"{i}. {t.get('artist','Unknown')} - {t.get('title','Unknown')} ({t.get('filename','')}, {t.get('size_mb',0)}MB)")
        
        return "\n".join(output)[:4000]
    except Exception as e:
        return f"List music failed: {e}"


def get_music_status() -> str:
    try:
        player = _get_music()
        if not player:
            return "Music player not available"
        
        status = player.get_status()
        
        current = status.get("current_filename","none")
        is_playing = status.get("is_playing", False)
        is_paused = status.get("is_paused", False)
        vol = status.get("volume", 0)
        playlist_len = status.get("playlist_length", 0)
        
        state = "Playing" if is_playing else "Paused" if is_paused else "Stopped"
        
        return f"Music status, Sir: {state} | Current: {current} | Volume: {vol}% | Playlist: {playlist_len} tracks | Mixer: {'✓' if status.get('mixer_initialized') else '✗'}"
    except Exception as e:
        return f"Music status failed: {e}"


# Smart Speaker Zones Tools

def list_speaker_zones() -> str:
    try:
        zones = _get_speakers()
        if not zones:
            return "Speaker zones not available"
        
        overview = zones.get_overview()
        all_zones = zones.list_zones()
        
        output = [f"Speaker zones ({overview['total_zones']} total, {overview['muted_zones']} muted, avg volume {overview['avg_volume']}%), Sir:\n"]
        for name, data in all_zones.items():
            muted = "🔇 Muted" if data.get("muted") else f"🔊 {data.get('volume',0)}%"
            output.append(f"- {name}: {muted} - {data.get('description','')}")
        
        return "\n".join(output)
    except Exception as e:
        return f"List zones failed: {e}"


def set_zone_volume(zone: str, volume: int) -> str:
    try:
        zones = _get_speakers()
        if not zones:
            return "Speaker zones not available"
        return zones.set_volume(zone=zone, volume=volume)
    except Exception as e:
        return f"Set zone volume failed: {e}"


def mute_zone(zone: str) -> str:
    try:
        zones = _get_speakers()
        if not zones:
            return "Speaker zones not available"
        return zones.mute_zone(zone=zone)
    except Exception as e:
        return f"Mute zone failed: {e}"


def unmute_zone(zone: str) -> str:
    try:
        zones = _get_speakers()
        if not zones:
            return "Speaker zones not available"
        return zones.unmute_zone(zone=zone)
    except Exception as e:
        return f"Unmute zone failed: {e}"


def play_in_zone(zone: str, query: str = None, file_path: str = None) -> str:
    try:
        # First set zone, then play
        zones = _get_speakers()
        music = _get_music()
        
        if not zones or not music:
            return "Music or zones not available"
        
        zone_data = zones.get_zone(zone)
        if not zone_data:
            return f"Zone '{zone}' not found, Sir. Available: {', '.join(zones.list_zones().keys())}"
        
        if zone_data.get("muted"):
            return f"Zone {zone} is muted, Sir. Unmute first with unmute_zone."
        
        # Play with zone volume
        result = music.play(query=query, file_path=file_path, zone=zone)
        return result
    except Exception as e:
        return f"Play in zone failed: {e}"


# Media Metadata Tools

def get_media_metadata(file_path: str) -> str:
    try:
        meta = _get_metadata()
        if not meta:
            return "Media metadata not available, Sir. Install mutagen: pip install mutagen --break-system-packages"
        
        data = meta.get_local_metadata(file_path=file_path)
        
        if data.get("error"):
            return f"Metadata failed, Sir: {data['error']}"
        
        output = f"""Media metadata for {file_path}, Sir:

Title: {data.get('title','Unknown')}
Artist: {data.get('artist','Unknown')}
Album: {data.get('album','Unknown')}
Genre: {data.get('genre','Unknown')}
Date: {data.get('date','')}
Duration: {data.get('duration_formatted','Unknown')} ({data.get('duration_seconds',0)}s)
File: {data.get('filename','')} - {data.get('size_bytes',0)//1024}KB

100% free local via mutagen, Sir.
"""
        return output
    except Exception as e:
        return f"Get metadata failed: {e}"


def search_media_metadata(query: str) -> str:
    try:
        meta = _get_metadata()
        if not meta:
            return "Media metadata not available"
        
        # Try MusicBrainz search (free, no key)
        result = meta.search_musicbrainz(query=query)
        
        if result.get("error"):
            return f"MusicBrainz search failed: {result['error']}. Install: pip install musicbrainzngs --break-system-packages (free, no key)"
        
        results = result.get("results", [])
        if not results:
            return f"No results on MusicBrainz for '{query}', Sir."
        
        output = [f"MusicBrainz search for '{query}' (free, no key), Sir:\n"]
        for i, r in enumerate(results, 1):
            output.append(f"{i}. {r.get('artist','Unknown')} - {r.get('title','Unknown')} (ID: {r.get('id','')[:8]}..., Length: {r.get('length',0)//1000}s)")
        
        return "\n".join(output)
    except Exception as e:
        return f"Search media metadata failed: {e}"


def get_media_overview() -> str:
    try:
        music = _get_music()
        meta = _get_metadata()
        zones = _get_speakers()
        
        music_overview = music.get_overview() if music else {"error": "no music"}
        meta_overview = meta.get_overview() if meta else {"error": "no metadata"}
        zones_overview = zones.get_overview() if zones else {"error": "no zones"}
        
        return f"""Media & Entertainment Overview, Sir:

🎵 Music Library:
  Total files: {music_overview.get('total_files',0)} | Size: {music_overview.get('total_size_mb',0)}MB
  Dirs: {', '.join(music_overview.get('music_dirs',[])[:2])}
  Formats: {music_overview.get('formats',{})}
  Current: {music_overview.get('current_track','none')} | Playing: {music_overview.get('is_playing',False)}

🔊 Speaker Zones:
  Total: {zones_overview.get('total_zones',0)} | Muted: {zones_overview.get('muted_zones',0)} | Avg vol: {zones_overview.get('avg_volume',0)}%
  Zones: {', '.join(zones_overview.get('zones',{}).keys()) if isinstance(zones_overview.get('zones'), dict) else 'none'}

📀 Metadata:
  MusicBrainz enabled: {meta_overview.get('musicbrainz_enabled',False)}
  Mutagen: {'✓' if not meta_overview.get('error') else '✗ Install mutagen'}

Add MP3s to workspace/music/ or ~/Music/ for local playback, Sir. 100% free local via pygame mixer.

Smart speaker zones in data/speaker_zones.json, fully free configurable.

For streaming: placeholder for Spotify via spotipy (free API but needs key) - currently local only for 100% free.
"""
    except Exception as e:
        return f"Media overview failed: {e}"
