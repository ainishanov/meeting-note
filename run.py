#!/usr/bin/env python3
"""
Meeting Note - Audio recording and transcription service.

Run this script to start the application:
    python run.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.app import run_app


if __name__ == "__main__":
    sys.exit(run_app())
