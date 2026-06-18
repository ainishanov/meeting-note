#!/usr/bin/env python3
"""Entry point for Meeting Note application."""

import sys
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from src.app import run_app


def main():
    """Main entry point."""
    sys.exit(run_app())


if __name__ == "__main__":
    main()
