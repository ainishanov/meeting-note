"""Main application class for Meeting Note."""

import sys
import time
import traceback
from typing import Optional

from loguru import logger

from src.utils.config import get_settings
from src.utils.logger import setup_logger


SINGLE_INSTANCE_SERVER = "MeetingNote.SingleInstance"


def global_exception_handler(exc_type, exc_value, exc_tb):
    """Global exception handler to prevent silent crashes."""
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.error(f"Unhandled exception:\n{error_msg}")

    # Show error dialog if QApplication exists
    from PyQt6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance()
    if app:
        QMessageBox.critical(
            None,
            "Ошибка",
            f"Произошла непредвиденная ошибка:\n\n{exc_value}\n\nПодробности в логах.",
        )


class MeetingNoteApp:
    """
    Main application class for Meeting Note.

    Manages the application lifecycle, system tray, and hotkeys.
    """

    def __init__(self):
        self.settings = get_settings()
        self._app: Optional[object] = None
        self._main_window: Optional[object] = None
        self._tray: Optional[object] = None
        self._hotkeys: Optional[object] = None
        self._single_instance_server: Optional[object] = None
        self._single_instance_clients: list[object] = []

    def run(self) -> int:
        """Run the application."""
        startup_started_at = time.perf_counter()

        # Setup logging
        setup_logger(
            log_level=self.settings.log_level,
            log_file=self.settings.log_file,
        )
        logger.info("Starting Meeting Note application")

        # Install global exception handler
        sys.excepthook = global_exception_handler

        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        from src.ui.resources import get_app_icon

        # Create Qt application
        self._app = QApplication(sys.argv)
        self._app.setApplicationName("Meeting Note")
        self._app.setWindowIcon(get_app_icon())
        self._app.setQuitOnLastWindowClosed(True)  # Close app when window is closed

        if self._notify_existing_instance():
            logger.info("Another Meeting Note instance is already running")
            return 0

        self._start_single_instance_server()

        # Set dark theme
        self._set_dark_theme()

        # Create main window
        import_started_at = time.perf_counter()
        from src.ui.main_window import MainWindow

        logger.info(
            f"Main window module imported in {time.perf_counter() - import_started_at:.2f}s"
        )
        window_started_at = time.perf_counter()
        self._main_window = MainWindow()
        logger.info(
            f"Main window created in {time.perf_counter() - window_started_at:.2f}s"
        )

        # Create system tray
        self._setup_tray()

        # Setup hotkeys
        self._setup_hotkeys()

        # Connect signals
        self._connect_signals()

        # Cleanup on app quit
        self._app.aboutToQuit.connect(self._cleanup)

        # Show window
        self._main_window.show()
        QTimer.singleShot(250, self._main_window.check_interrupted_recordings)

        logger.info(f"Application window shown in {time.perf_counter() - startup_started_at:.2f}s")
        logger.info("Application started successfully")

        # Run event loop
        return self._app.exec()

    def _cleanup(self) -> None:
        """Cleanup resources before app quits."""
        logger.info("Cleaning up application resources")

        if self._main_window and hasattr(self._main_window, "cleanup_runtime_services"):
            self._main_window.cleanup_runtime_services()

        # Stop hotkeys
        if self._hotkeys:
            self._hotkeys.stop()

        # Hide tray
        if self._tray:
            self._tray.hide()

        if self._single_instance_server:
            from PyQt6.QtNetwork import QLocalServer

            self._single_instance_server.close()
            QLocalServer.removeServer(SINGLE_INSTANCE_SERVER)

    def _notify_existing_instance(self) -> bool:
        """Ask an already running instance to show its window."""
        from PyQt6.QtNetwork import QLocalSocket

        socket = QLocalSocket()
        socket.connectToServer(SINGLE_INSTANCE_SERVER)
        if not socket.waitForConnected(250):
            socket.abort()
            return False

        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(250)
        socket.disconnectFromServer()
        return True

    def _start_single_instance_server(self) -> None:
        """Listen for later launches and use them as a show-window signal."""
        from PyQt6.QtNetwork import QLocalServer

        QLocalServer.removeServer(SINGLE_INSTANCE_SERVER)

        server = QLocalServer()
        if not server.listen(SINGLE_INSTANCE_SERVER):
            logger.warning(f"Single-instance server failed: {server.errorString()}")
            return

        server.newConnection.connect(self._handle_single_instance_connection)
        self._single_instance_server = server
        logger.info("Single-instance guard initialized")

    def _handle_single_instance_connection(self) -> None:
        """Handle activation messages from a second launch."""
        if not self._single_instance_server:
            return

        while self._single_instance_server.hasPendingConnections():
            socket = self._single_instance_server.nextPendingConnection()
            self._single_instance_clients.append(socket)
            socket.readyRead.connect(self._show_window)
            socket.disconnected.connect(lambda s=socket: self._forget_single_instance_client(s))
            self._show_window()

    def _forget_single_instance_client(self, socket: object) -> None:
        """Drop a completed local socket connection."""
        try:
            self._single_instance_clients.remove(socket)
        except ValueError:
            pass
        socket.deleteLater()

    def _set_dark_theme(self) -> None:
        """Apply dark theme to the application."""
        from src.ui.theme import get_global_stylesheet
        self._app.setStyleSheet(get_global_stylesheet())

    def _setup_tray(self) -> None:
        """Setup system tray icon."""
        from src.ui.system_tray import SystemTrayIcon

        self._tray = SystemTrayIcon()

        # Connect tray signals
        self._tray.start_recording_clicked.connect(self._on_tray_start)
        self._tray.stop_recording_clicked.connect(self._on_tray_stop)
        self._tray.show_window_clicked.connect(self._show_window)
        self._tray.settings_clicked.connect(self._open_settings)
        self._tray.quit_clicked.connect(self._quit)

    def _setup_hotkeys(self) -> None:
        """Setup global hotkeys."""
        from src.ui.hotkeys import AppHotkeys

        self._hotkeys = AppHotkeys(
            on_toggle_recording=self._toggle_recording,
        )
        self._hotkeys.setup_default_hotkeys()
        self._hotkeys.start()

    def _connect_signals(self) -> None:
        """Connect application signals."""
        # Connect main window recording state to tray via existing Qt signal (thread-safe)
        if self._main_window and self._tray:
            self._main_window._recording_state_signal.connect(self._tray.set_recording_state)

    def _on_tray_start(self) -> None:
        """Handle start recording from tray."""
        if self._main_window:
            self._main_window._start_recording()

    def _on_tray_stop(self) -> None:
        """Handle stop recording from tray."""
        if self._main_window:
            self._main_window._stop_recording()

    def _toggle_recording(self) -> None:
        """Toggle recording state."""
        if self._main_window:
            is_recording = getattr(self._main_window, "is_recording_active", lambda: False)
            if is_recording():
                self._main_window._stop_recording()
            else:
                self._main_window._start_recording()

    def _show_window(self) -> None:
        """Show main window."""
        if self._main_window:
            self._main_window.show()
            self._main_window.activateWindow()
            self._main_window.raise_()

    def _open_settings(self) -> None:
        """Open settings dialog."""
        if self._main_window:
            self._main_window._open_settings()

    def _quit(self) -> None:
        """Quit application — cleanup is handled by aboutToQuit → _cleanup."""
        logger.info("Quitting application")
        if self._main_window:
            self._main_window.close()
        elif self._app:
            self._app.quit()


def run_app() -> int:
    """Entry point for running the application."""
    app = MeetingNoteApp()
    return app.run()
