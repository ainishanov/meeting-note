#!/usr/bin/env python3
"""
Meeting Note - Audio recording and transcription service.

Run this script to start the application:
    python run.py
"""

import sys
from pathlib import Path


RELEASES_URL = "https://github.com/ainishanov/meeting-note/releases/latest"
RUNTIME_ERROR_EXIT_CODE = 70

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def load_qt_runtime() -> str:
    """Load the complete GUI runtime before application initialization."""
    from PySide6.QtCore import qVersion
    from PySide6.QtWidgets import QApplication  # noqa: F401

    return qVersion()


def runtime_smoke_test() -> int:
    """Exercise the frozen Qt runtime without touching user data or app state."""
    from PySide6.QtWidgets import QApplication

    if not load_qt_runtime():
        return RUNTIME_ERROR_EXIT_CODE
    app = QApplication(["MeetingNote", "--runtime-smoke-test"])
    app.quit()
    return 0


def show_runtime_recovery() -> None:
    """Explain a broken GUI runtime without depending on that runtime."""
    if sys.platform != "win32":
        return

    import ctypes

    message = (
        "Файлы приложения повреждены или несовместимы.\n\n"
        "Скачайте и установите последнюю версию Meeting Note. "
        "Ваши записи останутся на компьютере.\n\n"
        "Открыть страницу скачивания?"
    )
    answer = ctypes.windll.user32.MessageBoxW(
        None,
        message,
        "Meeting Note не удалось запустить",
        0x10 | 0x04,
    )
    if answer == 6:  # IDYES
        import os

        os.startfile(RELEASES_URL)


def main(argv: list[str] | None = None) -> int:
    """Run the application or its packaging-only runtime check."""
    arguments = sys.argv if argv is None else argv
    if arguments[1:] == ["--runtime-smoke-test"]:
        try:
            return runtime_smoke_test()
        except (ImportError, OSError):
            return RUNTIME_ERROR_EXIT_CODE

    try:
        load_qt_runtime()
    except (ImportError, OSError):
        show_runtime_recovery()
        return RUNTIME_ERROR_EXIT_CODE

    from src.app import run_app

    return run_app()


if __name__ == "__main__":
    sys.exit(main())
