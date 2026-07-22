"""Recording control widget with audio level meter."""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.theme import (
    ACCENT_PRIMARY, ACCENT_PRIMARY_HOVER, ACCENT_PRIMARY_PRESSED,
    ACCENT_SECONDARY,
    BG_SURFACE_2, BG_SURFACE_3,
    FONT_MONO,
    RADIUS_LG, RADIUS_MD,
    STATUS_RECORDING, STATUS_PAUSED, STATUS_SUCCESS,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
)
from src.ui.i18n import tr


class RecordingIndicator(QWidget):
    """Pulsing dot indicator for recording state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._color = QColor(TEXT_TERTIARY)
        self._opacity = 1.0

        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._update_pulse)
        self._pulse_growing = False

    def set_state(self, state: object):
        state_value = _state_value(state)
        if state_value == "recording":
            self._color = QColor(STATUS_RECORDING)
            if not self._pulse_timer.isActive():
                self._pulse_timer.start(50)
        elif state_value == "paused":
            self._color = QColor(STATUS_PAUSED)
            self._pulse_timer.stop()
            self._opacity = 1.0
        else:
            self._color = QColor(TEXT_TERTIARY)
            self._pulse_timer.stop()
            self._opacity = 1.0
        self.update()

    def _update_pulse(self):
        if self._pulse_growing:
            self._opacity += 0.04
            if self._opacity >= 1.0:
                self._opacity = 1.0
                self._pulse_growing = False
        else:
            self._opacity -= 0.04
            if self._opacity <= 0.3:
                self._opacity = 0.3
                self._pulse_growing = True
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._color)
        color.setAlphaF(self._opacity)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        margin = 2
        painter.drawEllipse(margin, margin, self.width() - margin * 2, self.height() - margin * 2)


class AudioLevelMeter(QWidget):
    """Thin audio level meter bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(6)
        self.setMaximumHeight(6)
        self._level = 0.0

    def set_level(self, level: float):
        self._level = max(0.0, min(1.0, level))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        h = self.height()
        w = self.width()
        r = h / 2

        # Background
        path_bg = QPainterPath()
        path_bg.addRoundedRect(0, 0, w, h, r, r)
        painter.fillPath(path_bg, QColor(BG_SURFACE_3))

        # Level bar
        if self._level > 0.005:
            bar_w = max(h, int(w * self._level))

            if self._level < 0.6:
                color = QColor(STATUS_SUCCESS)
            elif self._level < 0.85:
                color = QColor(STATUS_PAUSED)
            else:
                color = QColor(STATUS_RECORDING)

            path_bar = QPainterPath()
            path_bar.addRoundedRect(0, 0, bar_w, h, r, r)
            painter.fillPath(path_bar, color)


class RecordingWidget(QWidget):
    """Widget for recording controls."""

    start_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    resume_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._recording_state = "idle"
        self._recording_duration = 0
        self._detected_app = ""
        self._setup_ui()
        self._setup_timer()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)

        # Recording frame
        self.frame = QFrame()
        self.frame.setObjectName("recordingFrame")
        self.frame.setMinimumHeight(76)
        self._set_frame_style()

        frame_layout = QHBoxLayout(self.frame)
        frame_layout.setContentsMargins(16, 11, 14, 11)
        frame_layout.setSpacing(14)

        self.indicator = RecordingIndicator()
        frame_layout.addWidget(self.indicator)

        status_column = QVBoxLayout()
        status_column.setSpacing(3)

        self.status_label = QLabel(tr("Готов к записи"))
        self.status_label.setStyleSheet(f"""
            font-size: 14px; font-weight: 600; color: {TEXT_PRIMARY};
            background: transparent;
        """)
        status_column.addWidget(self.status_label)

        self.context_label = QLabel(tr("Системный звук и микрофон"))
        self.context_label.setStyleSheet(
            f"font-size: 12px; color: {TEXT_TERTIARY}; background: transparent;"
        )
        status_column.addWidget(self.context_label)

        self.level_meter = AudioLevelMeter()
        self.level_meter.setMinimumWidth(190)
        self.level_meter.hide()
        status_column.addWidget(self.level_meter)
        frame_layout.addLayout(status_column, stretch=1)

        self.duration_label = QLabel("00:00:00")
        self.duration_label.setStyleSheet(f"""
            font-size: 16px; font-family: {FONT_MONO}; color: {TEXT_SECONDARY};
            background: transparent;
        """)
        self.duration_label.hide()
        frame_layout.addWidget(self.duration_label)

        self.main_button = QPushButton(tr("Записать встречу"))
        self.main_button.setMinimumSize(170, 40)
        self.main_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main_button.clicked.connect(self._on_main_button_clicked)
        self._update_main_button_style("start")
        frame_layout.addWidget(self.main_button)

        self.stop_button = QPushButton(tr("Остановить"))
        self.stop_button.setMinimumSize(112, 40)
        self.stop_button.setEnabled(False)
        self.stop_button.hide()
        self.stop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_stop_button_style()
        self.stop_button.clicked.connect(self.stop_clicked.emit)
        frame_layout.addWidget(self.stop_button)

        layout.addWidget(self.frame)

    def _set_frame_style(self, accent: str | None = None) -> None:
        border = accent or "transparent"
        self.frame.setStyleSheet(f"""
            QFrame#recordingFrame {{
                background-color: {BG_SURFACE_2};
                border-radius: {RADIUS_LG}px;
                border: 1px solid {border};
            }}
        """)

    def _apply_stop_button_style(self):
        self.stop_button.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {STATUS_RECORDING};
                border: 1px solid {STATUS_RECORDING};
                border-radius: {RADIUS_MD}px;
                font-size: 13px;
                font-weight: 600;
                padding: 8px 20px;
            }}
            QPushButton:hover {{
                background-color: {STATUS_RECORDING};
                color: #ffffff;
            }}
            QPushButton:pressed {{
                background-color: #e05555;
                color: #ffffff;
            }}
            QPushButton:disabled {{
                background-color: transparent;
                color: {TEXT_TERTIARY};
                border: 1px solid {TEXT_TERTIARY};
            }}
        """)

    def _setup_timer(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_duration)
        self._detection_timer = QTimer(self)
        self._detection_timer.setSingleShot(True)
        self._detection_timer.timeout.connect(self._clear_detected_meeting)

    def _update_main_button_style(self, mode: str):
        styles = {
            "start": (ACCENT_PRIMARY, ACCENT_PRIMARY_HOVER, ACCENT_PRIMARY_PRESSED, "#ffffff"),
            "pause": (STATUS_PAUSED, "#ffe066", "#f0c030", TEXT_TERTIARY),
            "resume": (ACCENT_SECONDARY, "#33d6d1", "#00b5b0", TEXT_TERTIARY),
        }
        bg, hover, pressed, fg = styles.get(mode, styles["start"])
        self.main_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: none;
                border-radius: {RADIUS_MD}px;
                font-size: 14px;
                font-weight: 600;
                padding: 8px 24px;
            }}
            QPushButton:hover {{ background-color: {hover}; }}
            QPushButton:pressed {{ background-color: {pressed}; }}
            QPushButton:disabled {{
                background-color: {BG_SURFACE_3};
                color: {TEXT_TERTIARY};
            }}
        """)

    def _on_main_button_clicked(self):
        state_value = _state_value(self._recording_state)
        if state_value == "idle":
            self._clear_detected_meeting()
            self.start_clicked.emit()
        elif state_value == "recording":
            self.pause_clicked.emit()
        elif state_value == "paused":
            self.resume_clicked.emit()

    def set_recording_state(self, state: object):
        self._recording_state = state
        self.indicator.set_state(state)

        state_value = _state_value(state)
        if state_value == "preparing":
            self._clear_detected_meeting(reset_ui=False)
            self.status_label.setText(tr("Подготовка аудио..."))
            self.context_label.setText(tr("Проверяем аудиоустройства"))
            self.status_label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {TEXT_SECONDARY}; background: transparent;")
            self.main_button.setText(tr("Подготовка..."))
            self.main_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.stop_button.hide()
            self.duration_label.show()
            self.level_meter.show()
            self._timer.stop()
            self._set_frame_style()

        elif state_value == "idle":
            self._clear_detected_meeting(reset_ui=False)
            self.status_label.setText(tr("Готов к записи"))
            self.context_label.setText(tr("Системный звук и микрофон"))
            self.status_label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {TEXT_PRIMARY}; background: transparent;")
            self.main_button.setText(tr("Записать встречу"))
            self.main_button.setEnabled(True)
            self._update_main_button_style("start")
            self.stop_button.setEnabled(False)
            self.stop_button.hide()
            self.duration_label.hide()
            self.level_meter.hide()
            self._timer.stop()
            self._recording_duration = 0
            self.duration_label.setText("00:00:00")
            self._set_frame_style()

        elif state_value == "recording":
            self._clear_detected_meeting(reset_ui=False)
            self.status_label.setText(tr("Запись"))
            self.context_label.setText(tr("Системный звук и микрофон записываются"))
            self.status_label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {STATUS_RECORDING}; background: transparent;")
            self.main_button.setText(tr("Пауза"))
            self.main_button.setEnabled(True)
            self._update_main_button_style("pause")
            self.stop_button.setEnabled(True)
            self.stop_button.show()
            self.duration_label.show()
            self.level_meter.show()
            if not self._timer.isActive():
                self._timer.start(1000)
            self._set_frame_style(STATUS_RECORDING)

        elif state_value == "paused":
            self._clear_detected_meeting(reset_ui=False)
            self.status_label.setText(tr("Пауза"))
            self.context_label.setText(tr("Запись приостановлена"))
            self.status_label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {STATUS_PAUSED}; background: transparent;")
            self.main_button.setText(tr("Продолжить"))
            self.main_button.setEnabled(True)
            self._update_main_button_style("resume")
            self.stop_button.setEnabled(True)
            self.stop_button.show()
            self.duration_label.show()
            self.level_meter.show()
            self._timer.stop()
            self._set_frame_style(STATUS_PAUSED)

        elif state_value == "stopping":
            self._clear_detected_meeting(reset_ui=False)
            self.status_label.setText(tr("Остановка..."))
            self.context_label.setText(tr("Сохраняем запись"))
            self.main_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.stop_button.show()
            self.duration_label.show()
            self.level_meter.show()
            self._timer.stop()

    def set_detected_meeting(self, app_name: str) -> None:
        """Highlight a detected call without taking over recording controls."""
        if _state_value(self._recording_state) != "idle":
            return

        self._detected_app = _friendly_meeting_app(app_name)
        self.status_label.setText(tr("Обнаружен созвон"))
        self.context_label.setText(self._detected_app)
        self.main_button.setText(tr("Записать этот созвон"))
        self._set_frame_style(ACCENT_SECONDARY)
        self._detection_timer.start(30_000)

    def _clear_detected_meeting(self, reset_ui: bool = True) -> None:
        self._detection_timer.stop()
        self._detected_app = ""
        if reset_ui and _state_value(self._recording_state) == "idle":
            self.status_label.setText(tr("Готов к записи"))
            self.context_label.setText(tr("Системный звук и микрофон"))
            self.main_button.setText(tr("Записать встречу"))
            self._set_frame_style()

    def set_audio_level(self, level: float):
        self.level_meter.set_level(level)

    def _update_duration(self):
        self._recording_duration += 1
        hours = self._recording_duration // 3600
        minutes = (self._recording_duration % 3600) // 60
        seconds = self._recording_duration % 60
        self.duration_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")


def _state_value(state: object) -> str:
    value = getattr(state, "value", state)
    return str(value)


def _friendly_meeting_app(app_name: str) -> str:
    value = (app_name or "").lower()
    labels = (
        ("zoom", "Zoom"),
        ("teams", "Microsoft Teams"),
        ("telemost", "Yandex Telemost"),
        ("skype", "Skype"),
        ("discord", "Discord"),
    )
    for needle, label in labels:
        if needle in value:
            return label
    if "google meet" in value or "meet.google" in value:
        return "Google Meet"
    if any(browser in value for browser in ("chrome", "edge", "firefox", "browser")):
        return tr("Созвон в браузере")
    return app_name or tr("Приложение для встреч")
