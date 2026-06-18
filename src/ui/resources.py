"""Helpers for locating bundled UI assets."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon


def resource_path(relative_path: str) -> Path:
    """Return a path to a source-tree or PyInstaller-bundled resource."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return bundle_root / relative_path


def get_app_icon() -> QIcon:
    """Return the Meeting Note application icon."""
    return QIcon(str(resource_path("assets/app_icon.ico")))
