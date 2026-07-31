"""
Proactive Scheduler - Schedules morning briefings, evening summaries, routine checks
Uses APScheduler if available, fallback to threading
"""

import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List
import json
from pathlib import Path

from ..config import config


class ProactiveScheduler:
    def __init__(self):
        self.jobs: List[Dict] = []
        self.is_running = False
        self.thread: threading.Thread = None
        self.stop_event = threading.Event()
        
        # Try APScheduler
        self.use_apscheduler = False
        self.scheduler = None
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            self.scheduler = BackgroundScheduler()
            self.use_apscheduler = True
            print("✓ APScheduler available for proactive scheduling")
        except ImportError:
            print("APScheduler not available, using fallback threading scheduler")
        
        self.job_callbacks: Dict[str, Callable] = {}
    
    def add_daily_job(self, job_id: str, hour: int, minute: int, callback: Callable, args: tuple = ()):
        """Add daily job at hour:minute"""
        job = {
            "id": job_id,
            "type": "daily",
            "hour": hour,
            "minute": minute,
            "callback": callback,
            "args": args
        }
        self.jobs.append(job)
        self.job_callbacks[job_id] = (callback, args)
        
        if self.use_apscheduler and self.scheduler:
            try:
                self.scheduler.add_job(
                    callback,
                    'cron',
                    hour=hour,
                    minute=minute,
                    id=job_id,
                    args=args,
                    replace_existing=True
                )
                print(f"✓ Scheduled daily job {job_id} at {hour:02d}:{minute:02d}")
            except Exception as e:
                print(f"Failed to schedule {job_id}: {e}")
        else:
            print(f"✓ Added daily job {job_id} at {hour:02d}:{minute:02d} (fallback)")
    
    def add_interval_job(self, job_id: str, minutes: int, callback: Callable, args: tuple = ()):
        """Add interval job every N minutes"""
        job = {
            "id": job_id,
            "type": "interval",
            "minutes": minutes,
            "callback": callback,
            "args": args,
            "last_run": None
        }
        self.jobs.append(job)
        self.job_callbacks[job_id] = (callback, args)
        
        if self.use_apscheduler and self.scheduler:
            try:
                self.scheduler.add_job(
                    callback,
                    'interval',
                    minutes=minutes,
                    id=job_id,
                    args=args,
                    replace_existing=True
                )
                print(f"✓ Scheduled interval job {job_id} every {minutes}min")
            except Exception as e:
                print(f"Failed to schedule interval {job_id}: {e}")
        else:
            print(f"✓ Added interval job {job_id} every {minutes}min (fallback)")
    
    def _fallback_loop(self):
        """Fallback scheduler loop using threading"""
        print("⏰ Fallback scheduler loop started, Sir.")
        while not self.stop_event.is_set():
            try:
                now = datetime.now()
                for job in self.jobs:
                    if job["type"] == "daily":
                        # Check if should run today (hour/minute match and not already run today)
                        if now.hour == job["hour"] and now.minute == job["minute"]:
                            last_run = job.get("last_run")
                            if not last_run or last_run.date() != now.date():
                                print(f"⏰ Running daily job {job['id']}, Sir.")
                                try:
                                    job["callback"](*job.get("args", ()))
                                    job["last_run"] = now
                                except Exception as e:
                                    print(f"Daily job {job['id']} failed: {e}")
                    
                    elif job["type"] == "interval":
                        last_run = job.get("last_run")
                        if not last_run or (now - last_run).total_seconds() >= job["minutes"] * 60:
                            print(f"⏰ Running interval job {job['id']}, Sir.")
                            try:
                                job["callback"](*job.get("args", ()))
                                job["last_run"] = now
                            except Exception as e:
                                print(f"Interval job {job['id']} failed: {e}")
                
                time.sleep(30)  # check every 30 sec
            
            except Exception as e:
                print(f"Fallback scheduler loop error: {e}")
                time.sleep(30)
    
    def start(self):
        if self.is_running:
            return
        
        if self.use_apscheduler and self.scheduler:
            try:
                self.scheduler.start()
                print("✓ APScheduler started")
            except Exception as e:
                print(f"APScheduler start failed: {e}, using fallback")
                self.use_apscheduler = False
        
        if not self.use_apscheduler:
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._fallback_loop, daemon=True)
            self.thread.start()
        
        self.is_running = True
        print("✓ Proactive scheduler started, Sir. I'll handle timing.")
    
    def stop(self):
        if not self.is_running:
            return
        
        if self.use_apscheduler and self.scheduler:
            try:
                self.scheduler.shutdown()
            except:
                pass
        
        if self.thread:
            self.stop_event.set()
            self.thread.join(timeout=2)
        
        self.is_running = False
        print("✓ Proactive scheduler stopped")
    
    def list_jobs(self) -> List[Dict]:
        return [{"id": j["id"], "type": j["type"], "hour": j.get("hour"), "minute": j.get("minute"), "minutes": j.get("minutes"), "last_run": str(j.get("last_run"))} for j in self.jobs]
