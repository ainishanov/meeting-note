"""System tray icon with menu and notifications."""

from typing import Callable, Optional

from PyQt6.QtCore import QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QApplication

from loguru import logger
from src.ui.i18n import tr
from src.ui.resources import get_app_icon


class SystemTrayIcon(QObject):
    """
    System tray icon for Meeting Note.

    Provides quick access to recording controls and status.
    """

    # Signals
    start_recording_clicked = pyqtSignal()
    stop_recording_clicked = pyqtSignal()
    show_window_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    quit_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tray: Optional[QSystemTrayIcon] = None
        self._recording_state = "idle"
        self._setup_tray()

    def _setup_tray(self) -> None:
        """Initialize system tray icon."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("System tray not available")
            return

        self._tray = QSystemTrayIcon()
        self._tray.setToolTip("Meeting Note")

        # Set default icon
        self._update_icon()

        # Create context menu
        self._create_menu()

        # Connect signals
        self._tray.activated.connect(self._on_tray_activated)

        self._tray.show()
        logger.info("System tray icon initialized")

    def _create_menu(self) -> None:
        """Create tray context menu."""
        menu = QMenu()

        # Recording actions
        self.start_action = QAction(tr("Начать запись"), menu)
        self.start_action.triggered.connect(self.start_recording_clicked.emit)
        menu.addAction(self.start_action)

        self.stop_action = QAction(tr("Остановить запись"), menu)
        self.stop_action.setEnabled(False)
        self.stop_action.triggered.connect(self.stop_recording_clicked.emit)
        menu.addAction(self.stop_action)

        menu.addSeparator()

        # Window actions
        show_action = QAction(tr("Показать окно"), menu)
        show_action.triggered.connect(self.show_window_clicked.emit)
        menu.addAction(show_action)

        settings_action = QAction(tr("Настройки"), menu)
        settings_action.triggered.connect(self.settings_clicked.emit)
        menu.addAction(settings_action)

        menu.addSeparator()

        # Quit
        quit_action = QAction(tr("Выход"), menu)
        quit_action.triggered.connect(self.quit_clicked.emit)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window_clicked.emit()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Single click - toggle recording
            if _state_value(self._recording_state) == "recording":
                self.stop_recording_clicked.emit()
            elif _state_value(self._recording_state) in {"preparing", "stopping"}:
                return
            else:
                self.start_recording_clicked.emit()

    def _update_icon(self) -> None:
        """Update tray icon based on recording state."""
        if not self._tray:
            return

        # Create colored icon based on state
        # Note: In production, use actual icon files
        app = QApplication.instance()
        if app:
            style = app.style()
            state_value = _state_value(self._recording_state)
            if state_value == "recording":
                # Red icon for recording
                icon = style.standardIcon(style.StandardPixmap.SP_MediaStop)
                self._tray.setToolTip(f"Meeting Note - {tr('Запись')}...")
            elif state_value == "stopping":
                icon = style.standardIcon(style.StandardPixmap.SP_BrowserReload)
                self._tray.setToolTip(f"Meeting Note - {tr('Сохранение...')}")
            else:
                icon = get_app_icon()
                self._tray.setToolTip("Meeting Note")

            self._tray.setIcon(icon)

    def set_recording_state(self, state: object) -> None:
        """Update tray based on recording state."""
        self._recording_state = state
        self._update_icon()

        if not hasattr(self, "start_action") or not hasattr(self, "stop_action"):
            return

        state_value = _state_value(state)
        if state_value in {"recording", "paused"}:
            self.start_action.setEnabled(False)
            self.stop_action.setEnabled(True)
        elif state_value in {"preparing", "stopping"}:
            self.start_action.setEnabled(False)
            self.stop_action.setEnabled(False)
        else:
            self.start_action.setEnabled(True)
            self.stop_action.setEnabled(False)

    def show_notification(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
        duration_ms: int = 3000,
    ) -> None:
        """Show a system notification."""
        if self._tray:
            self._tray.showMessage(title, message, icon, duration_ms)

    def hide(self) -> None:
        """Hide tray icon."""
        if self._tray:
            self._tray.hide()

    def show(self) -> None:
        """Show tray icon."""
        if self._tray:
            self._tray.show()


def _state_value(state: object) -> str:
    """Return a stable string for RecordingState without importing audio code."""
    value = getattr(state, "value", state)
    return str(value)
