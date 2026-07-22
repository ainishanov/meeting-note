"""Transcript view widget with speaker segments and summary."""

import html
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QTimer
from PyQt6.QtGui import QTextCharFormat, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.core.database import (
    ProcessingJob,
    Recording,
    Summary,
    Transcript,
    TranscriptSegment,
)
from src.core.recording_titles import display_recording_title
from src.ui.theme import (
    ACCENT_PRIMARY, ACCENT_PRIMARY_HOVER, ACCENT_PRIMARY_PRESSED,
    ACCENT_SECONDARY,
    BG_BASE, BG_SURFACE_1, BG_SURFACE_2, BG_SURFACE_3, BG_SURFACE_4,
    BORDER_DEFAULT, BORDER_SUBTLE,
    FONT_MONO,
    RADIUS_LG, RADIUS_MD, RADIUS_SM, RADIUS_ROUND,
    SPEAKER_COLORS,
    STATUS_ERROR, STATUS_PAUSED, STATUS_SUCCESS,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY, TEXT_INVERSE,
    _hex_to_rgba,
)
from src.ui.i18n import tr


class TranscriptViewWidget(QWidget):
    """Widget for viewing transcript with speaker segments."""

    export_requested = pyqtSignal(str, Recording)
    retry_transcription_requested = pyqtSignal(Recording)
    summary_regeneration_requested = pyqtSignal(Recording)
    delete_requested = pyqtSignal(int)  # recording_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._recording: Optional[Recording] = None
        self._transcript: Optional[Transcript] = None
        self._segments: list[TranscriptSegment] = []
        self._summary: Optional[Summary] = None
        self._processing_job: Optional[ProcessingJob] = None

        # Audio player is initialized lazily because Qt Multimedia can be slow on startup.
        self._player = None
        self._audio_output = None
        self._volume = 0.7
        self._is_slider_pressed = False
        self._audio_source_path: Optional[Path] = None
        self._pending_audio_play = False
        self._transcript_rendered = False
        self._delete_missing_button = None  # assigned in _setup_ui

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # Header
        header_frame = QFrame()
        header_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_SURFACE_2};
                border-radius: {RADIUS_LG}px;
            }}
        """)
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(20, 16, 20, 16)
        header_layout.setSpacing(12)

        # Title
        self.title_label = QLabel(tr("Выберите запись"))
        self.title_label.setStyleSheet(f"""
            font-size: 20px; font-weight: 600; color: {TEXT_PRIMARY};
            background: transparent; padding: 0;
        """)
        header_layout.addWidget(self.title_label)

        # Progress bar (hidden)
        self.progress_frame = QFrame()
        self.progress_frame.setVisible(False)
        self.progress_frame.setStyleSheet("background: transparent; border: none;")
        progress_layout = QVBoxLayout(self.progress_frame)
        progress_layout.setContentsMargins(0, 4, 0, 4)
        progress_layout.setSpacing(4)

        self.progress_label = QLabel(tr("Обработка..."))
        self.progress_label.setStyleSheet(f"font-size: 12px; color: {TEXT_SECONDARY}; background: transparent;")
        progress_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {BG_SURFACE_1};
                border: none;
                border-radius: {RADIUS_SM}px;
                text-align: center;
                color: {TEXT_PRIMARY};
                font-size: 10px;
            }}
            QProgressBar::chunk {{
                background-color: {ACCENT_PRIMARY};
                border-radius: {RADIUS_SM}px;
            }}
        """)
        progress_layout.addWidget(self.progress_bar)

        self._delete_missing_button = QPushButton(tr("Удалить из истории"))
        self._delete_missing_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_missing_button.setVisible(False)
        self._delete_missing_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {STATUS_ERROR};
                color: #ffffff;
                border: none;
                border-radius: {RADIUS_MD}px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 600;
                min-width: 0;
            }}
            QPushButton:hover {{ background-color: #e05555; }}
        """)
        progress_layout.addWidget(self._delete_missing_button)

        header_layout.addWidget(self.progress_frame)

        # Action buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)
        buttons_layout.addStretch()

        # Ghost button style (also used in _reset_copy_button)
        self._ghost_btn_style = f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD}px;
                padding: 8px 16px;
                font-size: 13px;
                color: {TEXT_SECONDARY};
            }}
            QPushButton:hover {{
                background-color: {BG_SURFACE_3};
                color: {TEXT_PRIMARY};
                border: 1px solid {TEXT_TERTIARY};
            }}
            QPushButton:pressed {{
                background-color: {BG_SURFACE_4};
            }}
            QPushButton:disabled {{
                color: {TEXT_TERTIARY};
                border: 1px solid {BG_SURFACE_3};
            }}
        """
        ghost_btn_style = self._ghost_btn_style

        # Retry button
        self.retry_button = QPushButton(tr("Повторить"))
        self.retry_button.setEnabled(False)
        self.retry_button.setVisible(False)
        self.retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_button.clicked.connect(self._on_retry_clicked)
        self.retry_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {STATUS_PAUSED};
                border: none;
                border-radius: {RADIUS_MD}px;
                padding: 8px 16px;
                font-size: 13px;
                color: {TEXT_INVERSE};
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: #ffe066; }}
            QPushButton:pressed {{ background-color: #f0c030; }}
        """)
        buttons_layout.addWidget(self.retry_button)

        # Copy button
        self.copy_button = QPushButton(tr("Копировать"))
        self.copy_button.setEnabled(False)
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self._on_copy_clicked)
        self.copy_button.setStyleSheet(ghost_btn_style)
        buttons_layout.addWidget(self.copy_button)

        # Export format
        self.export_format = QComboBox()
        self.export_format.addItems(["TXT", "MD", "DOCX"])
        self.export_format.setFixedWidth(75)
        buttons_layout.addWidget(self.export_format)

        # Export button
        self.export_button = QPushButton(tr("Экспорт"))
        self.export_button.setEnabled(False)
        self.export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_button.clicked.connect(self._on_export_clicked)
        self.export_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_PRIMARY};
                border: none;
                border-radius: {RADIUS_MD}px;
                padding: 8px 16px;
                font-size: 13px;
                color: #ffffff;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {ACCENT_PRIMARY_HOVER}; }}
            QPushButton:pressed {{ background-color: {ACCENT_PRIMARY_PRESSED}; }}
            QPushButton:disabled {{
                background-color: {BG_SURFACE_3};
                color: {TEXT_TERTIARY};
            }}
        """)
        buttons_layout.addWidget(self.export_button)

        header_layout.addLayout(buttons_layout)
        layout.addWidget(header_frame)

        # Audio player
        self.player_frame = QFrame()
        self.player_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_SURFACE_2};
                border-radius: {RADIUS_LG}px;
            }}
        """)
        self.player_frame.setVisible(False)
        player_layout = QHBoxLayout(self.player_frame)
        player_layout.setContentsMargins(12, 8, 12, 8)
        player_layout.setSpacing(12)

        # Play button
        self.play_button = QPushButton("▶")
        self.play_button.setFixedSize(40, 40)
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_PRIMARY};
                color: #ffffff;
                border-radius: {RADIUS_ROUND}px;
                font-size: 16px;
                border: none;
            }}
            QPushButton:hover {{ background-color: {ACCENT_PRIMARY_HOVER}; }}
        """)
        self.play_button.clicked.connect(self._toggle_playback)
        player_layout.addWidget(self.play_button)

        # Time label
        self.time_label = QLabel("0:00")
        self.time_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; min-width: 45px; font-family: {FONT_MONO}; background: transparent;")
        player_layout.addWidget(self.time_label)

        # Progress slider
        slider_style = f"""
            QSlider::groove:horizontal {{
                background: {BG_SURFACE_3};
                height: 4px;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {TEXT_PRIMARY};
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }}
            QSlider::handle:horizontal:hover {{
                background: #ffffff;
            }}
            QSlider::sub-page:horizontal {{
                background: {ACCENT_PRIMARY};
                border-radius: 2px;
            }}
        """

        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setStyleSheet(slider_style)
        self.progress_slider.sliderPressed.connect(self._on_slider_pressed)
        self.progress_slider.sliderReleased.connect(self._on_slider_released)
        self.progress_slider.sliderMoved.connect(self._on_slider_moved)
        player_layout.addWidget(self.progress_slider, stretch=1)

        # Duration label
        self.duration_label = QLabel("0:00")
        self.duration_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; min-width: 45px; font-family: {FONT_MONO}; background: transparent;")
        player_layout.addWidget(self.duration_label)

        # Volume
        volume_label = QLabel("🔊")
        volume_label.setStyleSheet("font-size: 14px; background: transparent;")
        player_layout.addWidget(volume_label)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: {BG_SURFACE_3};
                height: 4px;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {TEXT_SECONDARY};
                width: 10px;
                height: 10px;
                margin: -3px 0;
                border-radius: 5px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {TEXT_PRIMARY};
            }}
            QSlider::sub-page:horizontal {{
                background: {TEXT_TERTIARY};
                border-radius: 2px;
            }}
        """)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        player_layout.addWidget(self.volume_slider)

        layout.addWidget(self.player_frame)

        # Tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # === Transcript tab ===
        self.transcript_tab = QWidget()
        transcript_layout = QVBoxLayout(self.transcript_tab)
        transcript_layout.setContentsMargins(0, 8, 0, 0)

        # Search bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr("Поиск в транскрипте..."))
        self.search_input.setFixedHeight(36)
        self.search_input.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self.search_input)

        self.search_count_label = QLabel("")
        self.search_count_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        search_layout.addWidget(self.search_count_label)

        transcript_layout.addLayout(search_layout)

        # Transcript text
        self.transcript_text = QTextBrowser()
        self.transcript_text.setReadOnly(True)
        self.transcript_text.setOpenLinks(False)
        self.transcript_text.anchorClicked.connect(self._on_timestamp_clicked)
        self.transcript_text.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {BG_SURFACE_1};
                color: {TEXT_PRIMARY};
                border: none;
                border-radius: {RADIUS_LG}px;
                padding: 16px;
                font-size: 14px;
            }}
        """)
        transcript_layout.addWidget(self.transcript_text)

        self.tab_widget.addTab(self.transcript_tab, tr("Транскрипт"))

        # === Summary tab ===
        self.summary_tab = QWidget()
        summary_layout = QVBoxLayout(self.summary_tab)
        summary_layout.setContentsMargins(0, 8, 0, 0)

        summary_toolbar = QHBoxLayout()
        summary_toolbar.setContentsMargins(0, 0, 0, 0)
        summary_toolbar.setSpacing(8)

        self.summary_hint_label = QLabel("")
        self.summary_hint_label.setStyleSheet(
            f"color: {TEXT_TERTIARY}; font-size: 12px; background: transparent;"
        )
        summary_toolbar.addWidget(self.summary_hint_label, stretch=1)

        self.summary_retry_button = QPushButton(tr("Сгенерировать саммари"))
        self.summary_retry_button.setEnabled(False)
        self.summary_retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.summary_retry_button.clicked.connect(self._on_summary_retry_clicked)
        self.summary_retry_button.setStyleSheet(ghost_btn_style)
        summary_toolbar.addWidget(self.summary_retry_button)

        summary_layout.addLayout(summary_toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ background-color: transparent; border: none; }}")

        summary_content = QWidget()
        summary_content_layout = QVBoxLayout(summary_content)
        summary_content_layout.setSpacing(16)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)
        decisions_metric, self.decisions_count_label = self._create_metric_card(
            tr("Принятые решения"), ACCENT_SECONDARY
        )
        actions_metric, self.actions_count_label = self._create_metric_card(
            tr("Задачи"), ACCENT_PRIMARY
        )
        metrics_row.addWidget(decisions_metric)
        metrics_row.addWidget(actions_metric)
        summary_content_layout.addLayout(metrics_row)

        decisions_section = self._create_section(tr("Принятые решения"), ACCENT_SECONDARY)
        self.decisions_text = QLabel()
        self.decisions_text.setWordWrap(True)
        self.decisions_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.decisions_text.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; background: transparent;"
        )
        decisions_section.layout().addWidget(self.decisions_text)
        summary_content_layout.addWidget(decisions_section)

        action_items_section = self._create_section(tr("Задачи"), ACCENT_PRIMARY)
        self.action_items_text = QLabel()
        self.action_items_text.setWordWrap(True)
        self.action_items_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.action_items_text.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; background: transparent;"
        )
        action_items_section.layout().addWidget(self.action_items_text)
        summary_content_layout.addWidget(action_items_section)

        summary_section = self._create_section(tr("Краткое содержание"))
        self.summary_text = QLabel()
        self.summary_text.setWordWrap(True)
        self.summary_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary_text.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; background: transparent;")
        summary_section.layout().addWidget(self.summary_text)
        summary_content_layout.addWidget(summary_section)

        key_points_section = self._create_section(tr("Ключевые темы"))
        self.key_points_text = QLabel()
        self.key_points_text.setWordWrap(True)
        self.key_points_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.key_points_text.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; background: transparent;")
        key_points_section.layout().addWidget(self.key_points_text)
        summary_content_layout.addWidget(key_points_section)

        summary_content_layout.addStretch()

        scroll.setWidget(summary_content)
        summary_layout.addWidget(scroll)

        self.tab_widget.addTab(self.summary_tab, tr("Саммари"))

        # === Info tab ===
        self.info_tab = QWidget()
        info_layout = QVBoxLayout(self.info_tab)
        info_layout.setContentsMargins(12, 12, 12, 12)

        self.info_text = QLabel()
        self.info_text.setWordWrap(True)
        self.info_text.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.info_text.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        info_layout.addWidget(self.info_text)
        info_layout.addStretch()

        self.tab_widget.addTab(self.info_tab, tr("Информация"))
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

    def _create_section(self, title: str, accent: str = ACCENT_SECONDARY) -> QFrame:
        frame = QFrame()
        frame.setObjectName("summarySectionCard")
        frame.setStyleSheet(f"""
            QFrame#summarySectionCard {{
                background-color: {BG_SURFACE_2};
                border-radius: {RADIUS_LG}px;
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            font-size: 15px; font-weight: 600; color: {accent};
            background: transparent;
        """)
        layout.addWidget(title_label)

        return frame

    def _create_metric_card(self, title: str, accent: str) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setObjectName("summaryMetricCard")
        frame.setStyleSheet(f"""
            QFrame#summaryMetricCard {{
                background-color: {BG_SURFACE_2};
                border-radius: {RADIUS_LG}px;
                border: 1px solid {BORDER_SUBTLE};
            }}
        """)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(2)

        value_label = QLabel("0")
        value_label.setStyleSheet(
            f"font-size: 26px; font-weight: 700; color: {accent}; background: transparent;"
        )
        layout.addWidget(value_label)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"font-size: 12px; color: {TEXT_SECONDARY}; background: transparent;"
        )
        layout.addWidget(title_label)
        return frame, value_label

    def set_recording(
        self,
        recording,
        transcript,
        segments,
        summary,
        processing_job: Optional[ProcessingJob] = None,
    ):
        self._recording = recording
        self._transcript = transcript
        self._segments = segments
        self._summary = summary
        self._processing_job = processing_job
        self._transcript_rendered = False

        self.title_label.setText(display_recording_title(recording))
        self.export_button.setEnabled(transcript is not None)
        self.copy_button.setEnabled(transcript is not None and bool(transcript.full_text))
        self._reset_missing_file_notice()

        needs_retry = transcript is None or recording.status in (
            "error",
            "pending",
            "transcribing",
        )
        self.retry_button.setVisible(needs_retry)
        self.retry_button.setEnabled(needs_retry)

        can_generate_summary = transcript is not None and bool(transcript.full_text)
        self.summary_retry_button.setVisible(can_generate_summary)
        self.summary_retry_button.setEnabled(can_generate_summary)
        if summary:
            self.summary_retry_button.setText(tr("Обновить саммари"))
        elif recording.status == "summary_failed":
            self.summary_retry_button.setText(tr("Повторить саммари"))
        else:
            self.summary_retry_button.setText(tr("Сгенерировать саммари"))
        self.summary_hint_label.setVisible(can_generate_summary)
        self.summary_hint_label.setText(self._build_summary_hint())

        # Loading Qt Multimedia and rendering a long transcript can both block
        # the GUI thread. Prepare lightweight state here and defer the expensive
        # work until the user explicitly opens the transcript or presses Play.
        self._prepare_audio_ui()
        self.transcript_text.setHtml(
            f'<p style="color: {TEXT_TERTIARY}; text-align: center; margin-top: 40px;">'
            f'{tr("Откройте вкладку транскрипта, чтобы загрузить текст")}</p>'
        )
        self._update_summary_view()
        self._update_info_view()

        if transcript is not None or summary is not None:
            self.tab_widget.setCurrentWidget(self.summary_tab)
        else:
            self.tab_widget.setCurrentWidget(self.transcript_tab)

    def clear(self):
        self._recording = None
        self._transcript = None
        self._segments = []
        self._summary = None
        self._processing_job = None
        self._transcript_rendered = False

        self._clear_player_source()
        self.player_frame.setVisible(False)

        self.title_label.setText(tr("Выберите запись"))
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.retry_button.setVisible(False)
        self.retry_button.setEnabled(False)
        self.summary_retry_button.setVisible(False)
        self.summary_retry_button.setEnabled(False)
        self.summary_hint_label.setText("")
        self.transcript_text.clear()
        self.summary_text.setText("")
        self.key_points_text.setText("")
        self.decisions_text.setText("")
        self.action_items_text.setText("")
        self.decisions_count_label.setText("0")
        self.actions_count_label.setText("0")
        self.info_text.setText("")

    def _on_tab_changed(self, _index: int) -> None:
        if self.tab_widget.currentWidget() is not self.transcript_tab:
            return
        if self._transcript_rendered:
            return

        # Yield once so the selected tab can paint before a large rich-text
        # document is constructed.
        QTimer.singleShot(0, self._render_transcript_if_needed)

    def _render_transcript_if_needed(self) -> None:
        if self._transcript_rendered or self.tab_widget.currentWidget() is not self.transcript_tab:
            return
        self._transcript_rendered = True
        self._update_transcript_view()

    def _update_transcript_view(self):
        if not self._transcript:
            self.transcript_text.setHtml(
                f'<p style="color: {TEXT_TERTIARY}; text-align: center; margin-top: 40px;">'
                f'{tr("Транскрипт отсутствует")}</p>'
            )
            return

        if self._segments:
            html_parts = []
            current_speaker = None

            for seg in self._segments:
                speaker_label = seg.display_speaker
                if speaker_label != current_speaker:
                    current_speaker = speaker_label
                    speaker_color = self._get_speaker_color(seg.speaker)
                    escaped_speaker_label = html.escape(speaker_label)
                    html_parts.append(
                        f'<p style="margin-top: 16px; margin-bottom: 4px;">'
                        f'<span style="color: {speaker_color}; font-weight: 600; font-size: 13px;">'
                        f'{escaped_speaker_label}</span></p>'
                    )

                start_min = int(seg.start_time // 60)
                start_sec = int(seg.start_time % 60)
                timestamp_display = f"{start_min}:{start_sec:02d}"
                segment_text = html.escape(seg.text)
                timestamp_link = (
                    f'<a href="timestamp:{seg.start_time}" '
                    f'style="color: {ACCENT_SECONDARY}; text-decoration: none; font-size: 11px; '
                    f'font-family: {FONT_MONO};">{timestamp_display}</a>'
                )

                html_parts.append(
                    f'<p style="margin: 3px 0; margin-left: 24px; line-height: 1.7; color: {TEXT_PRIMARY};">'
                    f'{timestamp_link} '
                    f'{segment_text}</p>'
                )

            self.transcript_text.setHtml("".join(html_parts))
        else:
            self.transcript_text.setPlainText(self._transcript.full_text or "")

    def _update_summary_view(self):
        if not self._summary:
            if self._recording and self._recording.status == "summary_failed":
                self.summary_text.setText(
                    tr("Саммари не сгенерировано. Транскрипт сохранён, можно повторить генерацию.")
                )
            else:
                self.summary_text.setText(tr("Саммари не сгенерировано"))
            self.key_points_text.setText("")
            self.decisions_text.setText("")
            self.action_items_text.setText("")
            self.decisions_count_label.setText("0")
            self.actions_count_label.setText("0")
            return

        self.summary_text.setText(self._summary.summary or "")
        decisions = self._summary.decisions or []
        action_items = self._summary.action_items or []
        self.decisions_count_label.setText(str(len(decisions)))
        self.actions_count_label.setText(str(len(action_items)))

        if self._summary.key_points:
            points = "\n\n".join(f"•  {p}" for p in self._summary.key_points)
            self.key_points_text.setText(points)
        else:
            self.key_points_text.setText(tr("Нет ключевых тем"))

        if decisions:
            decision_text = "\n\n".join(f"✓  {item}" for item in decisions)
            self.decisions_text.setText(decision_text)
        else:
            self.decisions_text.setText(tr("Решения не зафиксированы"))

        if action_items:
            items = "\n\n".join(f"☐  {item}" for item in action_items)
            self.action_items_text.setText(items)
        else:
            self.action_items_text.setText(tr("Нет задач"))

    def _update_info_view(self):
        if not self._recording:
            self.info_text.setText("")
            return

        duration_str = "—"
        if self._recording.duration_seconds:
            hours = self._recording.duration_seconds // 3600
            minutes = (self._recording.duration_seconds % 3600) // 60
            seconds = self._recording.duration_seconds % 60
            if hours > 0:
                duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                duration_str = f"{minutes}:{seconds:02d}"

        date_str = "—"
        if self._recording.created_at:
            if isinstance(self._recording.created_at, str):
                date_str = self._recording.created_at
            else:
                date_str = self._recording.created_at.strftime("%d.%m.%Y %H:%M:%S")

        language = "—"
        if self._transcript and self._transcript.language:
            lang_names = {"ru": tr("Русский"), "en": "English"}
            language = lang_names.get(self._transcript.language, self._transcript.language)

        audio_path = Path(self._recording.audio_path) if self._recording.audio_path else None
        if audio_path and not audio_path.is_absolute():
            audio_path = Path.cwd() / audio_path
        file_status = tr("найден") if audio_path and audio_path.exists() else tr("не найден")

        info_html = f"""
        <p><b>{tr("Название:")}</b> {html.escape(display_recording_title(self._recording))}</p>
        <p><b>{tr("Дата:")}</b> {html.escape(date_str)}</p>
        <p><b>{tr("Длительность:")}</b> {html.escape(duration_str)}</p>
        <p><b>{tr("Язык:")}</b> {html.escape(language)}</p>
        <p><b>{tr("Статус:")}</b> {html.escape(self._display_status(self._recording.status))}</p>
        <p><b>{tr("Файл найден:")}</b> {html.escape(file_status)}</p>
        <p><b>{tr("Файл:")}</b> {html.escape(self._recording.audio_path)}</p>
        """

        if self._segments:
            speakers = set(s.display_speaker for s in self._segments if s.speaker)
            speakers_text = ", ".join(sorted(speakers)) if speakers else "—"
            info_html += f"<p><b>{tr('Спикеры:')}</b> {html.escape(speakers_text)}</p>"
            info_html += f"<p><b>{tr('Сегментов:')}</b> {len(self._segments)}</p>"

        if self._processing_job:
            info_html += self._processing_job_html(self._processing_job)

        self.info_text.setText(info_html)

    def _processing_job_html(self, job: ProcessingJob) -> str:
        payload = job.payload or {}
        progress = payload.get("progress") if isinstance(payload, dict) else None
        progress = progress if isinstance(progress, dict) else {}

        job_type = {
            "transcription": tr("Транскрибация"),
            "summary": tr("Саммари"),
        }.get(job.job_type, job.job_type)
        job_status = {
            "queued": tr("в очереди"),
            "running": tr("выполняется"),
            "completed": tr("завершена"),
            "failed": tr("ошибка"),
        }.get(job.status, job.status)

        info_html = f"""
        <hr>
        <p><b>{tr("Задача обработки:")}</b> {html.escape(job_type)}</p>
        <p><b>{tr("Статус задачи:")}</b> {html.escape(job_status)}</p>
        <p><b>{tr("Попыток:")}</b> {job.attempts}</p>
        """

        if job.started_at:
            info_html += f"<p><b>{tr('Запущена:')}</b> {html.escape(str(job.started_at))}</p>"
        if job.updated_at:
            info_html += f"<p><b>{tr('Обновлена:')}</b> {html.escape(str(job.updated_at))}</p>"
        if job.completed_at:
            info_html += f"<p><b>{tr('Завершена:')}</b> {html.escape(str(job.completed_at))}</p>"

        message = str(progress.get("message") or "").strip()
        current = progress.get("current")
        total = progress.get("total")
        if current is not None and total:
            progress_text = f"{current}/{total}"
            if message:
                progress_text += f" - {message}"
            info_html += f"<p><b>{tr('Прогресс:')}</b> {html.escape(progress_text)}</p>"
        elif message:
            info_html += f"<p><b>{tr('Прогресс:')}</b> {html.escape(message)}</p>"

        if job.error_message:
            info_html += f"<p><b>{tr('Ошибка:')}</b> {html.escape(job.error_message)}</p>"

        return info_html

    def _get_speaker_color(self, speaker: Optional[str]) -> str:
        if not speaker:
            return SPEAKER_COLORS[0]
        idx = sum(ord(c) for c in speaker) % len(SPEAKER_COLORS)
        return SPEAKER_COLORS[idx]

    def _on_search_changed(self, text: str):
        if not text:
            self.search_count_label.setText("")
            self._update_transcript_view()
            return

        cursor = self.transcript_text.textCursor()
        cursor.select(cursor.SelectionType.Document)

        plain_format = QTextCharFormat()
        cursor.setCharFormat(plain_format)

        highlight_format = QTextCharFormat()
        highlight_format.setBackground(QColor("#FFD54F"))
        highlight_format.setForeground(QColor("#000"))

        cursor.movePosition(cursor.MoveOperation.Start)
        count = 0

        while True:
            cursor = self.transcript_text.document().find(text, cursor)
            if cursor.isNull():
                break
            cursor.mergeCharFormat(highlight_format)
            count += 1

        self.search_count_label.setText(tr("Найдено: {count}", count=count))

    def _on_copy_clicked(self):
        if self._transcript and self._transcript.full_text:
            clipboard = QApplication.clipboard()
            clipboard.setText(self._transcript.full_text)

            original_text = self.copy_button.text()
            self.copy_button.setText(tr("Скопировано"))
            self.copy_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {STATUS_SUCCESS};
                    border: none;
                    border-radius: {RADIUS_MD}px;
                    padding: 8px 16px;
                    font-size: 13px;
                    color: #ffffff;
                    font-weight: 600;
                }}
            """)

            QTimer.singleShot(1500, lambda: self._reset_copy_button(original_text))

    def _reset_copy_button(self, original_text: str):
        self.copy_button.setText(original_text)
        self.copy_button.setStyleSheet(self._ghost_btn_style)

    def _on_export_clicked(self):
        if self._recording:
            format_map = {"TXT": "txt", "MD": "md", "DOCX": "docx"}
            format_type = format_map.get(self.export_format.currentText(), "txt")
            self.export_requested.emit(format_type, self._recording)

    def _on_retry_clicked(self):
        if self._recording:
            self.retry_button.setEnabled(False)
            self.retry_transcription_requested.emit(self._recording)

    def _on_summary_retry_clicked(self):
        if self._recording:
            self.summary_retry_button.setEnabled(False)
            self.summary_regeneration_requested.emit(self._recording)

    def _build_summary_hint(self) -> str:
        if not self._transcript or not self._transcript.full_text:
            return ""
        try:
            from src.core.summarizer import format_summary_estimate

            return format_summary_estimate(self._transcript.full_text)
        except Exception:
            return tr("Саммари: модель и стоимость будут показаны при запуске")

    def _display_status(self, status: str) -> str:
        return {
            "pending": tr("Ожидает обработки"),
            "recording": tr("Идёт запись"),
            "transcribing": tr("Транскрибация"),
            "transcribed": tr("Текст готов, саммари в очереди"),
            "summarizing": tr("Генерация саммари"),
            "summary_failed": tr("Текст готов, саммари не сгенерировано"),
            "completed": tr("Готово"),
            "error": tr("Ошибка"),
        }.get(status, status)

    # ==================== Audio Player Methods ====================

    def _ensure_player(self):
        if self._player is not None:
            return self._player

        from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._audio_output.setVolume(self._volume)
        self._player.setAudioOutput(self._audio_output)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        return self._player

    def _clear_player_source(self):
        if self._player is None:
            self._audio_source_path = None
            self._pending_audio_play = False
            return
        self._player.stop()
        self._player.setSource(QUrl())
        self._audio_source_path = None
        self._pending_audio_play = False

    def _prepare_audio_ui(self):
        """Show cheap audio metadata without initializing Qt Multimedia."""
        # Stopping is cheap, while clearing a WAV source can make some Windows
        # multimedia backends inspect the old file synchronously. Keep the old
        # source detached logically and replace it only after Play is clicked.
        if self._player is not None:
            self._player.stop()
        self._audio_source_path = None
        self._pending_audio_play = False
        self.play_button.setText("▶")
        self.play_button.setEnabled(True)
        self.time_label.setText("0:00")
        self.progress_slider.setValue(0)

        if not self._recording or not self._recording.audio_path:
            self.player_frame.setVisible(False)
            return

        audio_path = Path(self._recording.audio_path)
        if not audio_path.is_absolute():
            audio_path = Path.cwd() / audio_path

        if not audio_path.exists():
            self.player_frame.setVisible(False)
            return

        duration_seconds = int(self._recording.duration_seconds or 0)
        self.progress_slider.setRange(0, max(0, duration_seconds * 1000))
        self.duration_label.setText(self._format_time(duration_seconds * 1000))
        self.player_frame.setVisible(True)

    def _load_audio(self):
        if not self._recording or not self._recording.audio_path:
            self._clear_player_source()
            self.player_frame.setVisible(False)
            return

        audio_path = Path(self._recording.audio_path)
        if not audio_path.is_absolute():
            audio_path = Path.cwd() / audio_path

        if audio_path.exists():
            self._ensure_player().setSource(QUrl.fromLocalFile(str(audio_path)))
            self._audio_source_path = audio_path
            self.player_frame.setVisible(True)
        else:
            self._clear_player_source()
            self.player_frame.setVisible(False)

    def _toggle_playback(self):
        from PyQt6.QtMultimedia import QMediaPlayer

        player = self._ensure_player()
        if self._audio_source_path is None:
            self._pending_audio_play = True
            self.play_button.setText("…")
            self.play_button.setEnabled(False)
            # Allow the loading state to paint before the multimedia backend is
            # asked to inspect a potentially large WAV file.
            QTimer.singleShot(0, self._load_audio)
            return

        if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            player.pause()
        else:
            player.play()

    def _on_media_status_changed(self, status):
        from PyQt6.QtMultimedia import QMediaPlayer

        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self.play_button.setEnabled(True)
            self.play_button.setText("▶")
            if self._pending_audio_play:
                self._pending_audio_play = False
                self._player.play()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._pending_audio_play = False
            self.play_button.setEnabled(True)
            self.play_button.setText("▶")

    def _on_playback_state_changed(self, state):
        from PyQt6.QtMultimedia import QMediaPlayer

        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_button.setText("⏸")
        else:
            self.play_button.setText("▶")

    def _on_position_changed(self, position):
        if not self._is_slider_pressed:
            self.progress_slider.setValue(position)
        self.time_label.setText(self._format_time(position))

    def _on_duration_changed(self, duration):
        self.progress_slider.setRange(0, duration)
        self.duration_label.setText(self._format_time(duration))

    def _on_slider_pressed(self):
        self._is_slider_pressed = True

    def _on_slider_released(self):
        self._is_slider_pressed = False
        if self._player is not None:
            self._player.setPosition(self.progress_slider.value())

    def _on_slider_moved(self, position):
        self.time_label.setText(self._format_time(position))

    def _on_volume_changed(self, value):
        self._volume = value / 100.0
        if self._audio_output is not None:
            self._audio_output.setVolume(self._volume)

    def _format_time(self, ms: int) -> str:
        seconds = ms // 1000
        minutes = seconds // 60
        hours = minutes // 60
        if hours > 0:
            return f"{hours}:{minutes % 60:02d}:{seconds % 60:02d}"
        return f"{minutes}:{seconds % 60:02d}"

    def seek_to_time(self, seconds: float):
        from PyQt6.QtMultimedia import QMediaPlayer

        player = self._ensure_player()
        player.setPosition(int(seconds * 1000))
        if player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            player.play()

    def _on_timestamp_clicked(self, url):
        url_str = url.toString()
        if url_str.startswith("timestamp:"):
            try:
                seconds = float(url_str.replace("timestamp:", ""))
                self.seek_to_time(seconds)
            except ValueError:
                pass

    def show_progress(self, message: str = "Обработка..."):
        message = tr(message)
        self.progress_label.setText(message)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self._delete_missing_button.setVisible(False)
        self.progress_frame.setVisible(True)

    def update_progress(self, current: int, total: int, message: str = ""):
        if total > 0:
            percent = int((current / total) * 100)
            self.progress_bar.setValue(percent)
            if message:
                self.progress_label.setText(message)

    def hide_progress(self):
        self._delete_missing_button.setVisible(False)
        self.progress_bar.setVisible(False)
        self.progress_frame.setVisible(False)

    def _reset_missing_file_notice(self):
        try:
            self._delete_missing_button.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._delete_missing_button.setVisible(False)
        if self.progress_bar.isHidden():
            self.progress_label.setText(tr("Обработка..."))
            self.progress_frame.setVisible(False)

    def show_file_missing(
        self,
        recording: Recording,
        transcript,
        segments,
        summary,
        processing_job: Optional[ProcessingJob] = None,
    ):
        """Show a warning screen when the audio file for a recording is missing."""
        self._recording = recording
        self._transcript = transcript
        self._segments = segments
        self._summary = summary
        self._processing_job = processing_job
        self._transcript_rendered = True

        self._clear_player_source()
        self.player_frame.setVisible(False)

        self.title_label.setText(display_recording_title(recording))
        self.retry_button.setVisible(False)
        escaped_audio_path = html.escape(recording.audio_path)

        self.transcript_text.setHtml(f"""
            <div style="text-align: center; margin-top: 60px;">
                <p style="font-size: 32px; margin-bottom: 8px;">⚠️</p>
                <p style="color: {STATUS_ERROR}; font-size: 16px; font-weight: 600; margin-bottom: 12px;">
                    {tr("Аудиофайл не найден")}
                </p>
                <p style="color: {TEXT_TERTIARY}; font-size: 13px; margin-bottom: 4px;">
                    {tr("Файл был перемещён или удалён:")}
                </p>
                <p style="color: {TEXT_SECONDARY}; font-size: 12px; font-family: monospace;">
                    {escaped_audio_path}
                </p>
                <p style="color: {TEXT_TERTIARY}; font-size: 12px; margin-top: 16px;">
                    {tr("Транскрипт и саммари сохранены и доступны на вкладках ниже.")}
                </p>
            </div>
        """)

        self.export_button.setEnabled(self._transcript is not None)
        self.copy_button.setEnabled(
            self._transcript is not None and bool(self._transcript.full_text)
        )

        self._update_summary_view()
        self._update_info_view()

        if transcript is not None or summary is not None:
            self.tab_widget.setCurrentWidget(self.summary_tab)
        else:
            self.tab_widget.setCurrentWidget(self.transcript_tab)

        self.progress_label.setText(tr("Аудиофайл не найден. Хотите удалить запись из истории?"))
        self.progress_bar.setVisible(False)
        self.progress_frame.setVisible(True)

        try:
            self._delete_missing_button.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._delete_missing_button.clicked.connect(
            lambda: self.delete_requested.emit(recording.id)
        )
        self._delete_missing_button.setVisible(True)
