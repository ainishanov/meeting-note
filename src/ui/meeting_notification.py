"""Meeting detection notification popup widget."""

from loguru import logger
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.theme import (
    BG_OVERLAY, BG_SURFACE_3, BG_SURFACE_4,
    BORDER_DEFAULT, BORDER_SUBTLE,
    RADIUS_MD, RADIUS_XL,
    STATUS_RECORDING,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
)
from src.ui.i18n import tr


class MeetingNotificationWidget(QWidget):
    """Popup notification for meeting detection."""

    start_recording_clicked = Signal(str)
    dismiss_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._app_name = ""
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.timeout.connect(self.hide_notification)
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._update_countdown)
        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._update_fade)
        self._fade_direction = 1
        self._fade_opacity = 0.0
        self._fade_callback = None
        self._setup_ui()
        self._setup_styles()

    def _setup_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(10)

        self.content = QWidget()
        self.content.setObjectName("content")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(20, 18, 20, 18)
        content_layout.setSpacing(12)

        # Header
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        self.icon_label = QLabel("📹")
        self.icon_label.setStyleSheet("font-size: 26px;")
        header_layout.addWidget(self.icon_label)

        self.title_label = QLabel(tr("Обнаружен созвон"))
        self.title_label.setStyleSheet(f"font-weight: 600; font-size: 15px; color: {TEXT_PRIMARY};")
        header_layout.addWidget(self.title_label, stretch=1)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("close_btn")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.hide_notification)
        header_layout.addWidget(self.close_btn)

        content_layout.addLayout(header_layout)

        # App name
        self.app_label = QLabel("Zoom")
        self.app_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        content_layout.addWidget(self.app_label)

        # Separator
        separator = QWidget()
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"background-color: {BORDER_SUBTLE};")
        content_layout.addWidget(separator)

        # Buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)

        self.dismiss_btn = QPushButton(tr("Не сейчас"))
        self.dismiss_btn.setObjectName("dismiss_btn")
        self.dismiss_btn.setFixedHeight(40)
        self.dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dismiss_btn.clicked.connect(self._on_dismiss)
        buttons_layout.addWidget(self.dismiss_btn)

        self.record_btn = QPushButton(tr("Начать запись"))
        self.record_btn.setObjectName("record_btn")
        self.record_btn.setFixedHeight(40)
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.setDefault(True)
        self.record_btn.clicked.connect(self._on_start_recording)
        buttons_layout.addWidget(self.record_btn)

        content_layout.addLayout(buttons_layout)

        # Hint
        self.hint_label = QLabel(tr("Автоматически скроется через 30 сек"))
        self.hint_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px;")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.hint_label)

        layout.addWidget(self.content)
        self.setFixedSize(340, 200)

    def _setup_styles(self):
        self.setStyleSheet(f"""
            #content {{
                background-color: {BG_OVERLAY};
                border-radius: {RADIUS_XL}px;
                border: 1px solid {BORDER_DEFAULT};
            }}
            QLabel {{
                color: {TEXT_PRIMARY};
            }}
            QPushButton {{
                border-radius: {RADIUS_MD}px;
                font-size: 13px;
                font-weight: 600;
            }}
            #close_btn {{
                background: transparent;
                color: {TEXT_TERTIARY};
                border: none;
                border-radius: 14px;
            }}
            #close_btn:hover {{
                color: {TEXT_PRIMARY};
                background-color: {BG_SURFACE_4};
            }}
            #dismiss_btn {{
                background-color: {BG_SURFACE_3};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                padding: 8px 16px;
            }}
            #dismiss_btn:hover {{
                background-color: {BG_SURFACE_4};
            }}
            #record_btn {{
                background-color: {STATUS_RECORDING};
                color: #ffffff;
                border: none;
                padding: 8px 16px;
            }}
            #record_btn:hover {{
                background-color: #e05555;
            }}
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(0, 6)
        self.content.setGraphicsEffect(shadow)

    def show_notification(self, app_name: str, app_icon: str = "📹"):
        logger.debug(f"Showing notification for: {app_name}")
        self._app_name = app_name
        self.icon_label.setText(app_icon)
        self.app_label.setText(app_name)

        self._position_window()

        self.setWindowOpacity(0.0)
        self.show()
        QApplication.processEvents()

        self._fade_in()

        self._remaining_seconds = 30
        self._update_hint()
        self._auto_hide_timer.start(30000)
        self._countdown_timer.start(1000)

    def _update_countdown(self):
        self._remaining_seconds -= 1
        self._update_hint()
        if self._remaining_seconds <= 0:
            self._countdown_timer.stop()

    def _update_hint(self):
        self.hint_label.setText(
            tr("Автоматически скроется через {seconds} сек", seconds=self._remaining_seconds)
        )

    def _position_window(self):
        screen = QApplication.primaryScreen()
        if screen:
            screen_rect = screen.availableGeometry()
            x = screen_rect.right() - self.width() - 20
            y = screen_rect.bottom() - self.height() - 20
            self.move(x, y)

    def _fade_in(self):
        self._fade_opacity = 0.0
        self._fade_direction = 1
        self._fade_callback = None
        if not self._fade_timer.isActive():
            self._fade_timer.start(20)

    def _fade_out(self, callback=None):
        self._fade_opacity = 1.0
        self._fade_direction = -1
        self._fade_callback = callback
        if not self._fade_timer.isActive():
            self._fade_timer.start(20)

    def _update_fade(self):
        self._fade_opacity += 0.08 * self._fade_direction

        if self._fade_direction > 0:
            if self._fade_opacity >= 1.0:
                self.setWindowOpacity(1.0)
                self._fade_timer.stop()
            else:
                self.setWindowOpacity(self._fade_opacity)
        else:
            if self._fade_opacity <= 0.0:
                self.setWindowOpacity(0.0)
                self._fade_timer.stop()
                self.hide()
                if self._fade_callback:
                    self._fade_callback()
                    self._fade_callback = None
            else:
                self.setWindowOpacity(self._fade_opacity)

    def hide_notification(self):
        if self._auto_hide_timer.isActive():
            self._auto_hide_timer.stop()
        if self._countdown_timer.isActive():
            self._countdown_timer.stop()
        self._fade_out()

    def _on_start_recording(self):
        logger.info(f"Start recording clicked for: {self._app_name}")
        if self._auto_hide_timer.isActive():
            self._auto_hide_timer.stop()
        if self._countdown_timer.isActive():
            self._countdown_timer.stop()
        if self._fade_timer.isActive():
            self._fade_timer.stop()
        self.hide()
        self.start_recording_clicked.emit(self._app_name)

    def _on_dismiss(self):
        logger.info(f"Notification dismissed for: {self._app_name}")
        if self._auto_hide_timer.isActive():
            self._auto_hide_timer.stop()
        if self._countdown_timer.isActive():
            self._countdown_timer.stop()
        self.hide_notification()
        self.dismiss_clicked.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 1))
        painter.drawRect(self.rect())


class MeetingNotificationManager:
    """Manager for meeting notifications."""

    def __init__(self, parent=None):
        self._parent = parent
        self._notification: MeetingNotificationWidget = None
        self._dismissed_apps: set = set()

    def show_notification(self, app_name: str, on_start_recording=None, on_dismiss=None):
        if app_name in self._dismissed_apps:
            return

        if self._notification is None:
            self._notification = MeetingNotificationWidget(parent=self._parent)

        try:
            self._notification.start_recording_clicked.disconnect()
        except TypeError:
            pass
        try:
            self._notification.dismiss_clicked.disconnect()
        except TypeError:
            pass

        if on_start_recording:
            self._notification.start_recording_clicked.connect(on_start_recording)
        if on_dismiss:
            self._notification.dismiss_clicked.connect(on_dismiss)

        icon = self._get_app_icon(app_name)
        self._notification.show_notification(app_name, icon)

    def hide_notification(self):
        if self._notification:
            self._notification.hide_notification()

    def mark_dismissed(self, app_name: str):
        self._dismissed_apps.add(app_name)

    def clear_dismissed(self):
        self._dismissed_apps.clear()

    def _get_app_icon(self, app_name: str) -> str:
        app_lower = app_name.lower()
        if "zoom" in app_lower:
            return "📹"
        elif "teams" in app_lower:
            return "💼"
        elif "meet" in app_lower:
            return "🎥"
        elif "discord" in app_lower:
            return "💬"
        elif "slack" in app_lower:
            return "💬"
        elif "telemost" in app_lower:
            return "🇷🇺"
        return "📹"
