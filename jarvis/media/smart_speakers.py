"""
Smart Speaker Zones - Manage smart speaker zones, adjust volume, play in zones
100% FREE, local, config file based, with optional Home Assistant integration

For now: virtual zones with volume control, can be extended to Home Assistant, Snapcast, etc
Zones: living_room, bedroom, lab, kitchen, office, etc - configurable
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from ..config import config


DEFAULT_ZONES = {
    "living_room": {"volume": 70, "muted": False, "description": "Living Room"},
    "bedroom": {"volume": 50, "muted": False, "description": "Bedroom"},
    "lab": {"volume": 80, "muted": False, "description": "Lab / Stark Lab"},
    "kitchen": {"volume": 60, "muted": False, "description": "Kitchen"},
    "office": {"volume": 65, "muted": False, "description": "Office"},
    "all": {"volume": 70, "muted": False, "description": "All Zones (master)"}
}


class SmartSpeakerZones:
    def __init__(self, zones_file: Path = None):
        self.zones_file = zones_file or config.MEMORY_FILE.parent / "speaker_zones.json"
        self.zones_file.parent.mkdir(parents=True, exist_ok=True)
        self.zones = self._load()
    
    def _load(self) -> Dict:
        if self.zones_file.exists():
            try:
                data = json.loads(self.zones_file.read_text())
                # Merge with defaults to ensure all default zones exist
                merged = DEFAULT_ZONES.copy()
                merged.update(data)
                return merged
            except:
                return DEFAULT_ZONES.copy()
        return DEFAULT_ZONES.copy()
    
    def _save(self):
        try:
            self.zones_file.write_text(json.dumps(self.zones, indent=2))
        except Exception as e:
            print(f"Failed to save zones: {e}")
    
    def list_zones(self) -> Dict:
        """List all speaker zones with volume and status"""
        return self.zones
    
    def get_zone(self, zone: str) -> Optional[Dict]:
        zone = zone.lower().replace(" ", "_")
        return self.zones.get(zone)
    
    def set_volume(self, zone: str, volume: int) -> str:
        """Set volume for zone 0-100"""
        zone = zone.lower().replace(" ", "_")
        
        if zone not in self.zones:
            # If zone is "all", set all zones
            if zone == "all":
                for z in self.zones:
                    self.zones[z]["volume"] = max(0, min(100, volume))
                    self.zones[z]["muted"] = False
                self._save()
                return f"Set all zones volume to {volume}%, Sir."
            else:
                return f"Zone '{zone}' not found, Sir. Available zones: {', '.join(self.zones.keys())}"
        
        volume = max(0, min(100, volume))
        self.zones[zone]["volume"] = volume
        self.zones[zone]["muted"] = False if volume > 0 else self.zones[zone]["muted"]
        self._save()
        
        # If setting "all", also set all others
        if zone == "all":
            for z in self.zones:
                if z != "all":
                    self.zones[z]["volume"] = volume
                    self.zones[z]["muted"] = False
            self._save()
            return f"Set all zones volume to {volume}%, Sir."
        
        return f"Set {zone} volume to {volume}%, Sir. {self.zones[zone]['description']}"
    
    def mute_zone(self, zone: str) -> str:
        zone = zone.lower().replace(" ", "_")
        if zone not in self.zones:
            return f"Zone '{zone}' not found, Sir."
        
        self.zones[zone]["muted"] = True
        self._save()
        
        if zone == "all":
            for z in self.zones:
                self.zones[z]["muted"] = True
            self._save()
            return f"Muted all zones, Sir. Enjoy the silence."
        
        return f"Muted {zone}, Sir."
    
    def unmute_zone(self, zone: str) -> str:
        zone = zone.lower().replace(" ", "_")
        if zone not in self.zones:
            return f"Zone '{zone}' not found, Sir."
        
        self.zones[zone]["muted"] = False
        self._save()
        
        if zone == "all":
            for z in self.zones:
                self.zones[z]["muted"] = False
            self._save()
            return f"Unmuted all zones, Sir. Back in business."
        
        return f"Unmuted {zone}, Sir."
    
    def add_zone(self, zone: str, description: str = "", volume: int = 70) -> str:
        zone_key = zone.lower().replace(" ", "_")
        if zone_key in self.zones:
            return f"Zone '{zone}' already exists, Sir."
        
        self.zones[zone_key] = {
            "volume": max(0, min(100, volume)),
            "muted": False,
            "description": description or zone.title(),
            "created_at": datetime.now().isoformat()
        }
        self._save()
        return f"Added zone {zone_key} ({description or zone.title()}) with volume {volume}%, Sir."
    
    def remove_zone(self, zone: str) -> str:
        zone_key = zone.lower().replace(" ", "_")
        if zone_key not in self.zones:
            return f"Zone '{zone}' not found, Sir."
        
        if zone_key in ["all", "living_room"]:  # protect default important zones?
            # Allow but warn
            pass
        
        del self.zones[zone_key]
        self._save()
        return f"Removed zone {zone_key}, Sir."
    
    def get_overview(self) -> Dict:
        total = len(self.zones)
        muted_count = sum(1 for z in self.zones.values() if z.get("muted"))
        avg_volume = sum(z.get("volume", 0) for z in self.zones.values()) // total if total else 0
        
        return {
            "total_zones": total,
            "muted_zones": muted_count,
            "avg_volume": avg_volume,
            "zones": self.zones
        }
