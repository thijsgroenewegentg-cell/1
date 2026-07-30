#!/usr/bin/env python3
"""
JARVIS CLI - Entry point
Usage:
  python cli.py
  python cli.py --voice
  python cli.py --model llama3.1:8b
  python cli.py --prompt "what time is it"
"""
from jarvis.app import main

if __name__ == "__main__":
    main()
