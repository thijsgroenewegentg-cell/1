"""
Media Metadata - Fetch media metadata for local files and streaming
100% FREE, local + MusicBrainz (free, no key) for additional metadata
"""

import os
from pathlib import Path
from typing import Dict, Optional


class MediaMetadata:
    def __init__(self):
        self.musicbrainz_enabled = True
        try:
            import musicbrainzngs
            musicbrainzngs.set_useragent("JARVIS Media Hub", "4.0", "https://github.com/jarvis")
        except ImportError:
            self.musicbrainz_enabled = False
    
    def get_local_metadata(self, file_path: str) -> Dict:
        """Get metadata from local file via mutagen (free)"""
        try:
            from mutagen import File as MutagenFile
            from mutagen.easyid3 import EasyID3
            from mutagen.mp3 import MP3
            
            path = Path(file_path)
            if not path.exists():
                # Try workspace/music
                from ..config import config
                alt = config.WORKSPACE_DIR / "music" / file_path
                if alt.exists():
                    path = alt
                else:
                    return {"error": f"File not found: {file_path}"}
            
            audio = MutagenFile(str(path), easy=True)
            if not audio:
                return {"file": str(path), "error": "Could not read metadata, unsupported format"}
            
            # Extract common tags
            metadata = {
                "file": str(path),
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "title": str(audio.get('title', ['Unknown'])[0]) if audio.get('title') else path.stem,
                "artist": str(audio.get('artist', ['Unknown'])[0]) if audio.get('artist') else "Unknown",
                "album": str(audio.get('album', ['Unknown'])[0]) if audio.get('album') else "Unknown",
                "genre": str(audio.get('genre', ['Unknown'])[0]) if audio.get('genre') else "Unknown",
                "date": str(audio.get('date', [''])[0]) if audio.get('date') else "",
            }
            
            # Try to get length
            try:
                if hasattr(audio, 'info') and hasattr(audio.info, 'length'):
                    length = audio.info.length
                    metadata["duration_seconds"] = int(length)
                    metadata["duration_formatted"] = f"{int(length//60)}:{int(length%60):02d}"
            except:
                pass
            
            return metadata
        
        except ImportError:
            return {"error": "mutagen not installed, Sir. pip install mutagen --break-system-packages for media metadata (free)"}
        except Exception as e:
            return {"error": f"Metadata extraction failed: {e}", "file": file_path}
    
    def search_musicbrainz(self, artist: str = None, title: str = None, query: str = None) -> Dict:
        """
        Search MusicBrainz (free, no API key) for additional metadata
        MusicBrainz is free, open music database, no key needed
        """
        try:
            import musicbrainzngs
            
            if query and not artist and not title:
                # Parse query as "artist title" or just search
                # For simplicity, search recording
                result = musicbrainzngs.search_recordings(query=query, limit=3)
                recordings = result.get('recording-list', [])
                
                if not recordings:
                    return {"query": query, "results": [], "message": "No results on MusicBrainz"}
                
                results = []
                for rec in recordings[:3]:
                    results.append({
                        "title": rec.get('title', 'Unknown'),
                        "artist": rec.get('artist-credit-phrase', 'Unknown'),
                        "id": rec.get('id', ''),
                        "length": rec.get('length', 0),
                        "tags": [t['name'] for t in rec.get('tag-list', [])][:5]
                    })
                
                return {"query": query, "results": results, "source": "MusicBrainz free, no key"}
            
            else:
                # Search by artist and title
                search_query = ""
                if artist:
                    search_query += f"artist:{artist} "
                if title:
                    search_query += f"recording:{title}"
                
                if not search_query:
                    search_query = query or ""
                
                result = musicbrainzngs.search_recordings(query=search_query.strip(), limit=3)
                recordings = result.get('recording-list', [])
                
                results = []
                for rec in recordings[:3]:
                    results.append({
                        "title": rec.get('title', 'Unknown'),
                        "artist": rec.get('artist-credit-phrase', 'Unknown'),
                        "id": rec.get('id', ''),
                        "length": rec.get('length', 0)
                    })
                
                return {"query": search_query, "results": results, "source": "MusicBrainz free"}
        
        except ImportError:
            return {"error": "musicbrainzngs not installed, pip install musicbrainzngs --break-system-packages (free, no key) for enhanced metadata"}
        except Exception as e:
            return {"error": f"MusicBrainz search failed: {e}", "query": query}
    
    def get_overview(self, music_dir: str = None) -> Dict:
        """Get overview of local music library"""
        try:
            from ..config import config
            music_dirs = [
                Path(music_dir) if music_dir else None,
                config.WORKSPACE_DIR / "music",
                Path.home() / "Music",
                Path.home() / "music"
            ]
            music_dirs = [d for d in music_dirs if d and d.exists()]
            
            if not music_dirs:
                return {"error": "No music directories found. Create workspace/music/ and add MP3s, or set music dir"}
            
            total_files = 0
            total_size = 0
            formats = {}
            
            for mdir in music_dirs[:1]:  # only first existing for speed
                for file in mdir.rglob("*"):
                    if file.is_file() and file.suffix.lower() in ['.mp3', '.wav', '.flac', '.m4a', '.ogg', '.wma']:
                        total_files += 1
                        total_size += file.stat().st_size
                        ext = file.suffix.lower()
                        formats[ext] = formats.get(ext, 0) + 1
            
            return {
                "music_dirs": [str(d) for d in music_dirs],
                "total_files": total_files,
                "total_size_mb": round(total_size / (1024*1024), 1),
                "formats": formats,
                "musicbrainz_enabled": self.musicbrainz_enabled
            }
        except Exception as e:
            return {"error": f"Overview failed: {e}"}
