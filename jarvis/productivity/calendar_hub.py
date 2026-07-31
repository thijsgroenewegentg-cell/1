"""
Calendar Hub - Sync local calendars, parse upcoming events
100% FREE, local, no API keys, parses ICS files

Supports:
- Local ICS files in workspace/calendar/, data/calendar/, ~/Calendar/
- CalDAV is optional future, but for now local ICS is 100% free and private
- Parses upcoming events, today, tomorrow, week
- No Google Calendar API needed (free local), but optional support if user wants

ICS parsing via icalendar (free) or fallback simple parser
"""

import os
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json

from ..config import config


def _parse_ics_simple(ics_content: str) -> List[Dict]:
    """Simple ICS parser fallback if icalendar not available"""
    events = []
    # Split by BEGIN:VEVENT
    vevents = re.split(r'BEGIN:VEVENT', ics_content, flags=re.IGNORECASE)
    for vevent in vevents[1:]:  # skip first part before first VEVENT
        try:
            # Extract until END:VEVENT
            vevent = vevent.split('END:VEVENT')[0]
            
            # Extract fields
            def get_field(field_name):
                # Handle folded lines? Simplified
                pattern = rf'{field_name}[^:]*:(.+?)(?:\r\n|\n)'
                match = re.search(pattern, vevent, re.IGNORECASE)
                if match:
                    return match.group(1).strip().replace('\\n', '\n').replace('\\,', ',')
                return ""
            
            summary = get_field('SUMMARY') or "Untitled Event"
            dtstart = get_field('DTSTART')
            dtend = get_field('DTEND')
            location = get_field('LOCATION')
            description = get_field('DESCRIPTION')
            
            # Parse dates - try multiple formats
            start_dt = _parse_ics_date(dtstart)
            end_dt = _parse_ics_date(dtend) if dtend else None
            
            if start_dt:
                events.append({
                    "summary": summary,
                    "start": start_dt,
                    "end": end_dt,
                    "location": location,
                    "description": description[:500] if description else "",
                    "raw_dtstart": dtstart,
                    "source": "ics_simple"
                })
        except Exception as e:
            continue
    
    return events

def _parse_ics_date(date_str: str) -> Optional[datetime]:
    """Parse ICS date string"""
    if not date_str:
        return None
    
    # Remove TZID etc: DTSTART;TZID=Europe/Amsterdam:20260101T100000
    # Extract after last colon
    if ':' in date_str and 'T' in date_str:
        # Has time
        date_part = date_str.split(':')[-1]
    else:
        date_part = date_str.split(':')[-1] if ':' in date_str else date_str
    
    date_part = date_part.strip()
    
    # Remove Z
    is_utc = date_part.endswith('Z')
    if is_utc:
        date_part = date_part[:-1]
    
    # Try formats
    formats = [
        "%Y%m%dT%H%M%S",
        "%Y%m%dT%H%M%S%f",
        "%Y%m%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d"
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_part, fmt)
            return dt
        except:
            continue
    
    return None


class CalendarHub:
    def __init__(self, calendar_dirs: List[Path] = None):
        self.calendar_dirs = calendar_dirs or [
            config.WORKSPACE_DIR / "calendar",
            config.MEMORY_FILE.parent / "calendar",
            Path.home() / "Calendar",
            Path.home() / "calendar",
            Path.home() / ".calendar",
            Path.cwd() / "calendar"
        ]
        
        # Ensure workspace calendar dir exists
        (config.WORKSPACE_DIR / "calendar").mkdir(parents=True, exist_ok=True)
        (config.MEMORY_FILE.parent / "calendar").mkdir(parents=True, exist_ok=True)
        
        self.events_cache: List[Dict] = []
        self.last_sync: Optional[datetime] = None
    
    def _find_ics_files(self) -> List[Path]:
        ics_files = []
        for cal_dir in self.calendar_dirs:
            if not cal_dir.exists():
                continue
            try:
                # Find .ics files recursively up to depth 2
                for file in cal_dir.rglob("*.ics"):
                    if file.is_file() and file.stat().st_size < 5_000_000:  # skip huge
                        ics_files.append(file)
                # Also look in top level only for performance
                for file in cal_dir.glob("*.ics"):
                    if file not in ics_files and file.is_file():
                        ics_files.append(file)
            except:
                continue
        return list(set(ics_files))  # deduplicate
    
    def _parse_ics_file(self, file_path: Path) -> List[Dict]:
        """Parse single ICS file using icalendar if available, else simple parser"""
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"Failed to read ICS {file_path}: {e}")
            return []
        
        events = []
        
        # Try icalendar library first (better)
        try:
            from icalendar import Calendar
            cal = Calendar.from_ical(content)
            for component in cal.walk():
                if component.name == "VEVENT":
                    try:
                        summary = str(component.get('summary', 'Untitled Event'))
                        dtstart = component.get('dtstart')
                        dtend = component.get('dtend')
                        location = str(component.get('location', ''))
                        description = str(component.get('description', ''))
                        
                        start_dt = None
                        end_dt = None
                        
                        if dtstart:
                            dt = dtstart.dt
                            if hasattr(dt, 'hour'):  # datetime
                                start_dt = dt if isinstance(dt, datetime) else datetime.combine(datetime.today(), dt) if hasattr(dt, 'hour') else None
                                if isinstance(dt, datetime):
                                    start_dt = dt.replace(tzinfo=None) if dt.tzinfo else dt
                            else:  # date
                                start_dt = datetime.combine(dt, datetime.min.time())
                        
                        if dtend:
                            dt = dtend.dt
                            if hasattr(dt, 'hour'):
                                end_dt = dt if isinstance(dt, datetime) else None
                                if isinstance(dt, datetime):
                                    end_dt = end_dt.replace(tzinfo=None) if end_dt.tzinfo else end_dt
                            else:
                                end_dt = datetime.combine(dt, datetime.min.time())
                        
                        if start_dt:
                            events.append({
                                "summary": summary,
                                "start": start_dt,
                                "end": end_dt,
                                "location": location,
                                "description": description[:500],
                                "source_file": str(file_path),
                                "source": "icalendar"
                            })
                    except Exception as e:
                        continue
            
            if events:
                return events
        except ImportError:
            # icalendar not installed, use simple parser
            pass
        except Exception as e:
            print(f"icalendar parse failed for {file_path}: {e}, trying simple parser")
        
        # Fallback simple parser
        return _parse_ics_simple(content)
    
    def sync_calendars(self) -> Dict:
        """Sync local calendars - parse all ICS files"""
        print("📅 Syncing local calendars, Sir...")
        ics_files = self._find_ics_files()
        
        all_events = []
        files_parsed = 0
        
        for ics_file in ics_files:
            try:
                events = self._parse_ics_file(ics_file)
                if events:
                    all_events.extend(events)
                    files_parsed += 1
            except Exception as e:
                print(f"Failed to parse {ics_file}: {e}")
                continue
        
        # Sort by start date
        all_events.sort(key=lambda x: x.get("start") or datetime.max)
        
        self.events_cache = all_events
        self.last_sync = datetime.now()
        
        result = {
            "files_found": len(ics_files),
            "files_parsed": files_parsed,
            "total_events": len(all_events),
            "last_sync": self.last_sync.isoformat(),
            "calendar_dirs": [str(d) for d in self.calendar_dirs if d.exists()]
        }
        
        print(f"✓ Calendar sync: {files_parsed}/{len(ics_files)} files, {len(all_events)} events, Sir.")
        return result
    
    def get_upcoming_events(self, days: int = 7, limit: int = 10) -> List[Dict]:
        """Get upcoming events in next N days"""
        if not self.events_cache:
            self.sync_calendars()
        
        now = datetime.now()
        future = now + timedelta(days=days)
        
        upcoming = []
        for event in self.events_cache:
            start = event.get("start")
            if not start:
                continue
            # Ensure start is datetime
            if isinstance(start, str):
                try:
                    start = datetime.fromisoformat(start)
                except:
                    continue
            
            if now <= start <= future:
                upcoming.append(event)
        
        # Already sorted by start
        return upcoming[:limit]
    
    def get_today_events(self) -> List[Dict]:
        """Get today's events"""
        if not self.events_cache:
            self.sync_calendars()
        
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        today_events = []
        for event in self.events_cache:
            start = event.get("start")
            if not start:
                continue
            if isinstance(start, str):
                try:
                    start = datetime.fromisoformat(start)
                except:
                    continue
            
            if today_start <= start <= today_end:
                today_events.append(event)
        
        return today_events
    
    def get_tomorrow_events(self) -> List[Dict]:
        """Get tomorrow's events"""
        if not self.events_cache:
            self.sync_calendars()
        
        now = datetime.now()
        tomorrow = now + timedelta(days=1)
        tomorrow_start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_end = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        tomorrow_events = []
        for event in self.events_cache:
            start = event.get("start")
            if not start:
                continue
            if isinstance(start, str):
                try:
                    start = datetime.fromisoformat(start)
                except:
                    continue
            
            if tomorrow_start <= start <= tomorrow_end:
                tomorrow_events.append(event)
        
        return tomorrow_events
    
    def format_events(self, events: List[Dict]) -> str:
        """Format events for display"""
        if not events:
            return "No events found, Sir."
        
        lines = []
        for i, event in enumerate(events, 1):
            start = event.get("start")
            if isinstance(start, datetime):
                time_str = start.strftime("%A %b %d, %I:%M %p")
            else:
                time_str = str(start)
            
            summary = event.get("summary", "Untitled")
            location = event.get("location", "")
            loc_str = f" @ {location}" if location else ""
            
            lines.append(f"{i}. {time_str} - {summary}{loc_str}")
            if event.get("description"):
                desc = event.get("description", "")[:100]
                if desc:
                    lines.append(f"   {desc}...")
        
        return "\n".join(lines)
    
    def get_overview(self) -> Dict:
        """Get calendar overview"""
        if not self.events_cache:
            self.sync_calendars()
        
        now = datetime.now()
        today = self.get_today_events()
        tomorrow = self.get_tomorrow_events()
        upcoming_week = self.get_upcoming_events(days=7)
        
        return {
            "total_events": len(self.events_cache),
            "today_count": len(today),
            "tomorrow_count": len(tomorrow),
            "week_count": len(upcoming_week),
            "last_sync": self.last_sync.isoformat() if self.last_sync else None,
            "calendar_dirs": [str(d) for d in self.calendar_dirs if d.exists()],
            "files_found": len(self._find_ics_files())
        }
