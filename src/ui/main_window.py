"""Main application window."""

import re
import subprocess
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from loguru import logger
from PySide6.QtCore import QTimer, Qt, Signal, QThread
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from src import __version__
from src.core.database import ProcessingJob, Recording, TranscriptSegment, get_database
from src.core.recording_titles import (
    display_recording_title,
    format_recording_title,
    is_auto_generated_title,
    sanitize_semantic_title,
    semantic_title_from_summary,
)
from src.ui.history_list import HistoryListWidget
from src.ui.meeting_notification import MeetingNotificationManager
from src.ui.recording_widget import RecordingWidget
from src.ui.resources import get_app_icon
from src.ui.transcript_view import TranscriptViewWidget
from src.ui.i18n import tr
from src.utils.config import get_settings
from src.utils.telemetry import capture_exception, duration_bucket, track_event

if TYPE_CHECKING:
    from src.core.audio_recorder import AudioRecorder
    from src.core.auto_trigger.trigger_manager import TriggerManager


PROCESSING_WATCHDOG_INTERVAL_MS = 60_000
PROCESSING_STALE_SECONDS = 15 * 60


def _set_deterministic_recording_title(db, recording_id: int) -> None:
    """Keep a stable date fallback until a semantic title is available."""
    recording = db.get_recording(recording_id)
    if not recording or not is_auto_generated_title(recording.title):
        return

    title = format_recording_title(recording.created_at)
    if display_recording_title(recording) != title:
        return
    if recording.title != title:
        db.update_recording_title(recording_id, title)
        logger.info(f"Updated recording title to deterministic title: {title}")


def _set_semantic_recording_title(
    db,
    summarizer,
    recording_id: int,
    transcript_text: str,
    summary,
) -> None:
    """Store a short topic title without overwriting a user-authored title."""
    recording = db.get_recording(recording_id)
    if not recording or not is_auto_generated_title(recording.title):
        return

    title = sanitize_semantic_title(summarizer.generate_title(transcript_text))
    if not title:
        title = semantic_title_from_summary(summary)
    if not title:
        return

    db.update_recording_title(recording_id, title)
    logger.info(f"Updated recording title to semantic title: {title}")


@dataclass
class StopRecordingResult:
    """Result of stopping and saving a recording off the UI thread."""

    audio_path: Optional[Path]
    duration_seconds: Optional[float] = None
    is_silent: bool = False


class RecorderSetupWorker(QThread):
    """Worker thread for slow audio device initialization."""

    completed = Signal(object)  # AudioRecorder or Exception

    def __init__(self, settings, on_level_change, on_state_change):
        super().__init__()
        self.settings = settings
        self.on_level_change = on_level_change
        self.on_state_change = on_state_change

    def run(self):
        started_at = time.perf_counter()
        try:
            from src.core.audio_recorder import AudioRecorder
            from src.utils.security import get_microphone_settings

            mic_settings = get_microphone_settings()
            recorder = AudioRecorder(
                output_dir=self.settings.recordings_dir,
                sample_rate=self.settings.sample_rate,
                channels=self.settings.channels,
                on_level_change=self.on_level_change,
                on_state_change=self.on_state_change,
                microphone_enabled=mic_settings.get("enabled", True),
                microphone_device_index=mic_settings.get("device_index"),
                microphone_volume=mic_settings.get("volume", 1.0),
            )

            if self.settings.audio_device_index is not None:
                recorder.set_device(self.settings.audio_device_index)

            logger.info(
                f"Recorder initialized: mic_enabled={mic_settings.get('enabled')}, "
                f"mic_device={mic_settings.get('device_index')}, "
                f"mic_volume={mic_settings.get('volume')}, "
                f"elapsed={time.perf_counter() - started_at:.2f}s"
            )
            self.completed.emit(recorder)
        except Exception as e:
            logger.error(f"Failed to initialize recorder: {e}")
            self.completed.emit(e)


class StopRecordingWorker(QThread):
    """Worker thread for stopping, saving, and probing a recording."""

    completed = Signal(object)  # StopRecordingResult or Exception

    def __init__(self, recorder, silence_threshold: int):
        super().__init__()
        self.recorder = recorder
        self.silence_threshold = silence_threshold

    def run(self):
        try:
            audio_path = self.recorder.stop_recording()
            if not audio_path:
                self.completed.emit(StopRecordingResult(audio_path=None))
                return

            self.completed.emit(
                StopRecordingResult(
                    audio_path=audio_path,
                    duration_seconds=self._get_audio_duration_seconds(audio_path),
                    is_silent=self._is_recording_silent(audio_path),
                )
            )
        except Exception as e:
            logger.error(f"Failed to stop recording: {e}")
            self.completed.emit(e)

    @staticmethod
    def _get_audio_duration_seconds(audio_path: Path) -> Optional[float]:
        try:
            with wave.open(str(audio_path), "rb") as wav:
                frame_rate = wav.getframerate()
                if frame_rate <= 0:
                    return None
                return wav.getnframes() / frame_rate
        except Exception as e:
            logger.error(f"Failed to read audio duration for {audio_path}: {e}")
            return None

    def _is_recording_silent(self, audio_path: Path) -> bool:
        try:
            import numpy as np
            from pydub import AudioSegment

            audio = AudioSegment.from_file(str(audio_path))
            samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
            if len(samples) == 0:
                return True

            rms = float(np.sqrt(np.mean(samples**2)))
            is_silent = rms < self.silence_threshold
            logger.info(
                f"Audio silence check: RMS={rms:.1f}, "
                f"threshold={self.silence_threshold}, silent={is_silent}"
            )
            return is_silent
        except Exception as e:
            logger.error(f"Failed to check audio silence: {e}")
            return False


class TranscriptionWorker(QThread):
    """Worker thread for transcription."""

    finished = Signal(object)  # TranscriptionResult or Exception
    progress = Signal(str)
    detailed_progress = Signal(int, int, str)  # current, total, message

    def __init__(self, audio_path: Path, recording_id: int):
        super().__init__()
        self.audio_path = audio_path
        self.recording_id = recording_id

    def _progress_callback(self, current: int, total: int, message: str):
        """Callback for detailed transcription progress."""
        self.detailed_progress.emit(current, total, message)

    def run(self):
        try:
            from src.core.transcriber import get_transcriber
            from src.core.database import (
                get_database,
                Transcript,
            )

            db = get_database()

            # Transcribe
            self.progress.emit(tr("Транскрибация аудио..."))
            transcriber = get_transcriber()
            from src.utils.config import get_settings
            settings = get_settings()
            logger.info(f"Using transcription language from settings: {settings.transcription_language}")
            result = transcriber.transcribe(
                self.audio_path,
                language=settings.transcription_language,
                model=settings.transcription_model,
                progress_callback=self._progress_callback,
                resume_key=f"recording-{self.recording_id}",
            )

            # Save transcript to database
            self.progress.emit("Saving transcript...")
            transcript = Transcript(
                recording_id=self.recording_id,
                full_text=result.full_text,
                language=result.language,
            )
            transcript_id = db.create_transcript(transcript)

            # Save segments
            for seg in result.segments:
                seg.transcript_id = transcript_id
            db.add_segments(result.segments)

            # Update recording duration
            db.update_recording_duration(
                self.recording_id, int(result.duration_seconds)
            )

            _set_deterministic_recording_title(db, self.recording_id)

            # Transcript is ready; summary is a separate durable queue step.
            db.update_recording_status(self.recording_id, "transcribed")

            self.finished.emit(result)

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            # Mark as error in database
            try:
                db = get_database()
                db.update_recording_status(self.recording_id, "error")
            except Exception as db_err:
                logger.error(f"Failed to update recording status to error: {db_err}")
            self.finished.emit(e)


class SummaryWorker(QThread):
    """Worker thread for summary-only regeneration (when transcript already exists)."""

    finished = Signal(object)  # True or Exception
    progress = Signal(str)

    def __init__(
        self,
        recording_id: int,
        transcript_text: str,
        segments: Optional[list[TranscriptSegment]] = None,
    ):
        super().__init__()
        self.recording_id = recording_id
        self.transcript_text = transcript_text
        self.segments = segments or []

    def run(self):
        try:
            from src.core.summarizer import (
                apply_speaker_names,
                create_speaker_aware_summary,
                format_summary_estimate,
                get_summarizer,
            )
            from src.core.database import get_database

            db = get_database()
            db.update_recording_status(self.recording_id, "summarizing")

            # Generate summary first; create_summary upserts only after success.
            self.progress.emit(
                tr("Генерация саммари ({estimate})", estimate=format_summary_estimate(self.transcript_text))
            )
            summarizer = get_summarizer()
            if any(segment.speaker for segment in self.segments) and not any(
                segment.speaker_name for segment in self.segments
            ):
                self.progress.emit("Detecting speaker names...")
                speaker_names = summarizer.infer_speaker_names(self.segments)
                apply_speaker_names(self.segments, speaker_names)
                if speaker_names and self.segments:
                    db.update_segment_speaker_names(
                        self.segments[0].transcript_id,
                        speaker_names,
                    )

            summary = create_speaker_aware_summary(
                summarizer, self.recording_id, self.transcript_text, self.segments
            )
            db.create_summary(summary)

            _set_semantic_recording_title(
                db,
                summarizer,
                self.recording_id,
                self.transcript_text,
                summary,
            )

            # Mark as completed
            db.update_recording_status(self.recording_id, "completed")

            self.finished.emit(True)

        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            try:
                db = get_database()
                db.update_recording_status(self.recording_id, "summary_failed")
            except Exception as db_err:
                logger.error(f"Failed to update recording status to summary_failed: {db_err}")
            self.finished.emit(e)


class MainWindow(QMainWindow):
    """Main application window."""

    # Signals for thread-safe UI updates from recording thread
    _audio_level_signal = Signal(float)
    _recording_state_signal = Signal(object)
    _meeting_detected_signal = Signal(str)  # Thread-safe meeting detection

    def __init__(self):
        super().__init__()
        self.settings = get_settings()
        self.db = get_database()
        self._transcription_worker: Optional[TranscriptionWorker] = None
        self._summary_worker: Optional[SummaryWorker] = None
        self._active_processing_job_id: Optional[int] = None
        self._active_processing_job_type: Optional[str] = None
        self._active_recording_id: Optional[int] = None
        self._active_processing_recording_id: Optional[int] = None
        self.recorder: Optional["AudioRecorder"] = None
        self._recorder_setup_worker: Optional[RecorderSetupWorker] = None
        self._start_after_recorder_ready = False
        self._stop_worker: Optional[StopRecordingWorker] = None
        self._close_after_stop = False
        self.trigger_manager: Optional["TriggerManager"] = None
        self._cleanup_done = False
        self._processing_watchdog_timer = QTimer(self)
        self._processing_watchdog_timer.setInterval(PROCESSING_WATCHDOG_INTERVAL_MS)
        self._processing_watchdog_timer.timeout.connect(self._run_processing_watchdog)

        # Connect signals for thread-safe updates
        self._audio_level_signal.connect(self._update_audio_level_ui)
        self._recording_state_signal.connect(self._update_recording_state_ui)
        self._meeting_detected_signal.connect(self._show_notification_safe)

        self._setup_ui()
        from src.ui.update_manager import UpdateManager

        self._update_manager = UpdateManager(self)

        # Notification manager for meeting detection (create after UI is ready)
        self._notification_manager = MeetingNotificationManager(parent=self)
        self._setup_connections()
        self._load_history()
        self._processing_watchdog_timer.start()
        QTimer.singleShot(100, self._setup_auto_trigger)
        QTimer.singleShot(2500, self._check_for_updates_silently)

    def _setup_ui(self):
        """Initialize the user interface."""
        from src.ui.theme import (
            BG_BASE, BG_SURFACE_1,
            TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
            SPACE_SM, SPACE_MD,
        )

        self.setWindowTitle("Meeting Note")
        self.setWindowIcon(get_app_icon())
        self.setMinimumSize(1000, 700)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 0)
        main_layout.setSpacing(0)

        # Splitter for left panel and content
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # Left panel - History
        left_panel = QWidget()
        left_panel.setStyleSheet(f"background-color: {BG_SURFACE_1}; border-radius: 12px;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)

        history_label = QLabel(tr("История записей"))
        history_label.setStyleSheet(f"font-weight: 600; font-size: 14px; color: {TEXT_PRIMARY}; background: transparent;")
        left_layout.addWidget(history_label)

        self.history_search_input = QLineEdit()
        self.history_search_input.setPlaceholderText(tr("Поиск по встречам..."))
        self.history_search_input.setFixedHeight(34)
        self.history_search_input.textChanged.connect(self._on_history_search_changed)
        left_layout.addWidget(self.history_search_input)

        self.history_search_status = QLabel("")
        self.history_search_status.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px; background: transparent;")
        self.history_search_status.setVisible(False)
        left_layout.addWidget(self.history_search_status)

        self.history_list = HistoryListWidget()
        left_layout.addWidget(self.history_list, stretch=1)

        self.feedback_button = QPushButton(tr("Поделиться отзывом"))
        self.feedback_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.feedback_button.setToolTip(tr("Предложить улучшение или сообщить о проблеме"))
        self.feedback_button.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {TEXT_SECONDARY};
                border: 1px solid {BG_SURFACE_1};
                border-radius: 8px;
                padding: 8px 10px;
                text-align: left;
            }}
            QPushButton:hover {{
                color: {TEXT_PRIMARY};
                border-color: {TEXT_TERTIARY};
                background-color: {BG_SURFACE_1};
            }}
        """)
        self.feedback_button.clicked.connect(self._open_feedback)
        left_layout.addWidget(self.feedback_button)

        splitter.addWidget(left_panel)

        # Right panel - Recording and Transcript
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(8)

        # Recording controls
        self.recording_widget = RecordingWidget()
        right_layout.addWidget(self.recording_widget)

        # Transcript view
        self.transcript_view = TranscriptViewWidget()
        right_layout.addWidget(self.transcript_view, stretch=1)

        splitter.addWidget(right_panel)

        # Set splitter proportions
        splitter.setSizes([280, 720])

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Progress bar in status bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)

        self.status_label = QLabel(tr("Готов к записи"))
        self.status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        self.status_bar.addWidget(self.status_label)
        self.status_bar.hide()

        # Menu bar
        self._setup_menu()

    def _setup_menu(self):
        """Setup menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu(tr("Файл"))

        settings_action = QAction(tr("Настройки"), self)
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        exit_action = QAction(tr("Выход"), self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Help menu
        help_menu = menubar.addMenu(tr("Помощь"))

        update_action = QAction(tr("Проверить обновления"), self)
        update_action.triggered.connect(self._check_for_updates)
        help_menu.addAction(update_action)

        help_menu.addSeparator()

        feedback_action = QAction(tr("Поделиться отзывом"), self)
        feedback_action.triggered.connect(self._open_feedback)
        help_menu.addAction(feedback_action)

        help_menu.addSeparator()

        about_action = QAction(tr("О программе"), self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_auto_trigger(self):
        """Initialize auto-trigger manager."""
        if self._cleanup_done or self.trigger_manager is not None:
            return

        try:
            from src.core.auto_trigger.trigger_manager import TriggerManager, TriggerMode
        except Exception as e:
            logger.error(f"Failed to load auto-trigger components: {e}")
            return

        mode_map = {
            "manual": TriggerMode.MANUAL,
            "notification": TriggerMode.NOTIFICATION,
            "process": TriggerMode.PROCESS,
            "vad": TriggerMode.VAD,
            "combined": TriggerMode.COMBINED,
        }
        mode = mode_map.get(self.settings.trigger_mode, TriggerMode.NOTIFICATION)

        self.trigger_manager = TriggerManager(
            on_start_recording=self._on_auto_trigger_start,
            on_stop_recording=self._on_auto_trigger_stop,
            on_meeting_detected=self._on_meeting_detected,
        )
        self.trigger_manager.set_mode(mode)

        if self.settings.auto_trigger_enabled and mode != TriggerMode.MANUAL:
            self.trigger_manager.start()
            logger.info(f"Auto-trigger started in {mode.value} mode")

    def _on_meeting_detected(self, app_name: str):
        """Handle meeting detection (for notification mode) - called from worker thread."""
        # Emit signal to safely call from main thread
        self._meeting_detected_signal.emit(app_name)

    def _show_notification_safe(self, app_name: str):
        """Show notification - called from main thread via signal."""
        self.recording_widget.set_detected_meeting(app_name)
        self._notification_manager.show_notification(
            app_name=app_name,
            on_start_recording=self._on_notification_start_recording,
            on_dismiss=lambda: self._notification_manager.mark_dismissed(app_name),
        )

    def _on_notification_start_recording(self, app_name: str):
        """Handle start recording from notification."""
        logger.info(f"Starting recording from notification for: {app_name}")
        self._start_recording()

    def _on_auto_trigger_start(self, reason: str):
        """Handle auto-trigger start recording."""
        logger.info(f"Auto-trigger start: {reason}")
        self._start_recording()

    def _on_auto_trigger_stop(self, reason: str):
        """Handle auto-trigger stop recording."""
        logger.info(f"Auto-trigger stop: {reason}")
        self._stop_recording()

    def _setup_connections(self):
        """Setup signal connections."""
        # Recording widget
        self.recording_widget.start_clicked.connect(self._start_recording)
        self.recording_widget.stop_clicked.connect(self._stop_recording)
        self.recording_widget.pause_clicked.connect(self._pause_recording)
        self.recording_widget.resume_clicked.connect(self._resume_recording)

        # History list
        self.history_list.recording_selected.connect(self._on_recording_selected)
        self.history_list.recording_deleted.connect(self._on_recording_deleted)

        # Transcript view
        self.transcript_view.export_requested.connect(self._export_transcript)
        self.transcript_view.retry_transcription_requested.connect(self._retry_transcription)
        self.transcript_view.summary_regeneration_requested.connect(self._retry_transcription)
        self.transcript_view.delete_requested.connect(self._on_delete_missing_requested)

    def _load_history(self):
        """Load recording history from database."""
        if hasattr(self, "history_search_input"):
            query = self.history_search_input.text().strip()
            if query:
                self._apply_history_search(query)
                return

        recordings = self.db.get_all_recordings(limit=100)
        self._backfill_semantic_history_titles(recordings)
        self.history_list.set_recordings(
            recordings,
            processing_text_by_id=self._build_processing_text_by_id(),
        )
        if hasattr(self, "history_search_status"):
            self.history_search_status.setVisible(False)

    def _backfill_semantic_history_titles(self, recordings: list[Recording]) -> None:
        """Upgrade date-only history entries from already stored summaries."""
        for recording in recordings:
            if recording.id is None or not is_auto_generated_title(recording.title):
                continue
            summary = self.db.get_summary(recording.id)
            title = semantic_title_from_summary(summary)
            if not title:
                continue
            if self.db.update_recording_title(recording.id, title):
                recording.title = title

    def _has_active_processing_worker(self) -> bool:
        return bool(
            (self._transcription_worker and self._transcription_worker.isRunning())
            or (self._summary_worker and self._summary_worker.isRunning())
        )

    def _set_active_recording_id(self, recording_id: Optional[int]) -> None:
        self._active_recording_id = recording_id
        self.history_list.set_active_recording_id(recording_id)

    def _set_active_processing_recording_id(
        self,
        recording_id: Optional[int],
    ) -> None:
        self._active_processing_recording_id = recording_id
        self.history_list.set_active_processing_recording_id(recording_id)

    def _processing_label(self, job_type: Optional[str]) -> str:
        if job_type == "summary":
            return tr("Саммари")
        return tr("Транскрибация")

    def _queued_recording_status_for_job(self, job: ProcessingJob) -> str:
        return "transcribed" if job.job_type == "summary" else "pending"

    def _processing_text_for_job(self, job: ProcessingJob) -> str:
        payload = job.payload or {}
        progress = payload.get("progress") if isinstance(payload, dict) else None
        progress = progress if isinstance(progress, dict) else {}
        message = str(progress.get("message") or "").strip()
        current = progress.get("current")
        total = progress.get("total")
        label = self._processing_label(job.job_type)

        if current is not None and total:
            return f"{label}: {current}/{total} - {message or job.status}"
        if message:
            return f"{label}: {message}"
        if job.status == "queued":
            return f"{label}: {tr('в очереди')}"
        if job.status == "running":
            return f"{label}: {tr('выполняется')}"
        return f"{label}: {job.status}"

    def _build_processing_text_by_id(self) -> dict[int, str]:
        result: dict[int, str] = {}
        for job in self.db.get_active_processing_jobs():
            result[job.recording_id] = self._processing_text_for_job(job)
        return result

    def _refresh_processing_texts(self) -> None:
        self.history_list.set_processing_texts(self._build_processing_text_by_id())

    def _touch_active_processing_job(
        self,
        message: str,
        current: Optional[int] = None,
        total: Optional[int] = None,
    ) -> None:
        if self._active_processing_job_id is None:
            return

        progress: dict[str, object] = {
            "message": message,
            "updated_unix": int(time.time()),
        }
        if current is not None:
            progress["current"] = current
        if total is not None:
            progress["total"] = total

        try:
            self.db.touch_processing_job(
                self._active_processing_job_id,
                {"progress": progress},
            )
            self._refresh_processing_texts()
        except Exception as e:
            logger.warning(f"Failed to update processing heartbeat: {e}")

    def _queue_processing_job(self, recording_id: int, job_type: str) -> int:
        """Queue durable processing and start it when possible."""
        job_id = self.db.create_processing_job(recording_id, job_type)
        if job_type == "transcription":
            self.db.update_recording_status(recording_id, "pending")
        elif job_type == "summary":
            self.db.update_recording_status(recording_id, "transcribed")
        self._load_history()
        QTimer.singleShot(0, self._process_next_processing_job)
        return job_id

    def _process_next_processing_job(self):
        """Start the next queued processing job if the UI is free."""
        if self._cleanup_done or self._has_active_processing_worker():
            return
        if self.is_recording_active() or self._is_stop_in_progress():
            return

        job = self.db.get_next_processing_job()
        if not job:
            self._active_processing_job_id = None
            self._active_processing_job_type = None
            self._set_active_processing_recording_id(None)
            return

        recording = self.db.get_recording(job.recording_id)
        if not recording:
            self.db.update_processing_job_status(
                job.id,
                "failed",
                "Recording no longer exists",
            )
            QTimer.singleShot(0, self._process_next_processing_job)
            return

        if job.job_type == "transcription":
            self._start_transcription_job(job, recording)
        elif job.job_type == "summary":
            self._start_summary_job(job, recording)
        else:
            self.db.update_processing_job_status(
                job.id,
                "failed",
                f"Unknown job type: {job.job_type}",
            )
            QTimer.singleShot(0, self._process_next_processing_job)

    def _start_transcription_job(self, job: ProcessingJob, recording: Recording):
        audio_path = Path(recording.audio_path)
        if not audio_path.exists():
            self.db.update_recording_status(recording.id, "error")
            self.db.update_processing_job_status(
                job.id,
                "failed",
                f"Audio file not found: {audio_path}",
            )
            self._load_history()
            QTimer.singleShot(0, self._process_next_processing_job)
            return

        self._active_processing_job_id = job.id
        self._active_processing_job_type = job.job_type
        self._set_active_processing_recording_id(recording.id)

        self.db.update_processing_job_status(job.id, "running")
        self.db.update_recording_status(recording.id, "transcribing")
        self.db.update_processing_job_payload(
            job.id,
            {
                "progress": {
                    "message": tr("Начинаю транскрибацию..."),
                    "current": 0,
                    "total": 0,
                    "updated_unix": int(time.time()),
                }
            },
        )
        self.status_label.setText(tr("Транскрибация в очереди запущена"))
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.transcript_view.show_progress(tr("Начинаю транскрибацию..."))

        self._transcription_worker = TranscriptionWorker(audio_path, recording.id)
        self._transcription_worker.progress.connect(self._on_transcription_progress)
        self._transcription_worker.detailed_progress.connect(
            self._on_transcription_detailed_progress
        )
        self._transcription_worker.finished.connect(self._on_transcription_finished)
        self._transcription_worker.start()
        self._load_history()

    def _start_summary_job(self, job: ProcessingJob, recording: Recording):
        transcript = self.db.get_transcript(recording.id)
        if not transcript or not transcript.full_text:
            self.db.update_recording_status(recording.id, "error")
            self.db.update_processing_job_status(
                job.id,
                "failed",
                "Transcript is missing",
            )
            self._load_history()
            QTimer.singleShot(0, self._process_next_processing_job)
            return

        from src.core.summarizer import format_summary_estimate

        segments = self.db.get_segments(transcript.id)
        estimate = format_summary_estimate(transcript.full_text)

        self._active_processing_job_id = job.id
        self._active_processing_job_type = job.job_type
        self._set_active_processing_recording_id(recording.id)

        self.db.update_processing_job_status(job.id, "running")
        self.db.update_recording_status(recording.id, "summarizing")
        self.db.update_processing_job_payload(
            job.id,
            {
                "progress": {
                    "message": tr("Генерация саммари: {estimate}", estimate=estimate),
                    "updated_unix": int(time.time()),
                }
            },
        )
        self.status_label.setText(tr("Генерация саммари: {estimate}", estimate=estimate))
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.transcript_view.show_progress(tr("Генерация саммари: {estimate}", estimate=estimate))

        self._summary_worker = SummaryWorker(recording.id, transcript.full_text, segments)
        self._summary_worker.progress.connect(self._on_transcription_progress)
        self._summary_worker.finished.connect(self._on_summary_finished)
        self._summary_worker.start()
        self._load_history()

    def _finish_active_processing_job(
        self,
        succeeded: bool,
        error: Optional[Exception] = None,
    ) -> None:
        if self._active_processing_job_id is not None:
            self.db.update_processing_job_status(
                self._active_processing_job_id,
                "completed" if succeeded else "failed",
                None if succeeded else str(error),
            )
        self._active_processing_job_id = None
        self._active_processing_job_type = None
        if not self._has_active_processing_worker():
            self._set_active_processing_recording_id(None)
            self._refresh_processing_texts()
        QTimer.singleShot(0, self._process_next_processing_job)

    def _on_history_search_changed(self, text: str):
        """Filter history by title or transcript text."""
        query = text.strip()
        if not query:
            self._load_history()
            return
        self._apply_history_search(query)

    def _apply_history_search(self, query: str):
        """Apply global meeting search to the history list."""
        try:
            recordings = self.db.search_recordings(query, limit=100)
            seen_ids = {recording.id for recording in recordings if recording.id is not None}
            match_text_by_id: dict[int, str] = {}

            for match in self.db.search_transcripts(query, limit=100):
                recording_id = match.get("recording_id")
                if recording_id is not None and recording_id not in match_text_by_id:
                    match_text_by_id[recording_id] = match.get("text") or ""
                if recording_id in seen_ids:
                    continue
                recording = self.db.get_recording(recording_id)
                if recording:
                    recordings.append(recording)
                    seen_ids.add(recording_id)

            self._backfill_semantic_history_titles(recordings)
            self.history_list.set_recordings(
                recordings,
                match_text_by_id=match_text_by_id,
                processing_text_by_id=self._build_processing_text_by_id(),
            )
            self.history_search_status.setText(tr("Найдено: {count}", count=len(recordings)))
            self.history_search_status.setVisible(True)
        except Exception as e:
            logger.error(f"History search failed: {e}")
            self.history_search_status.setText(tr("Поиск не удался"))
            self.history_search_status.setVisible(True)

    def check_interrupted_recordings(self):
        """Resume durable processing jobs left by a prior shutdown."""
        requeued = self.db.requeue_running_processing_jobs()

        legacy_interrupted = self.db.get_recordings_by_statuses(
            ["recording", "pending", "transcribing", "summarizing"]
        )
        queued_legacy = 0
        for recording in legacy_interrupted:
            if recording.id is None:
                continue
            transcript = self.db.get_transcript(recording.id)
            audio_path = Path(recording.audio_path) if recording.audio_path else None
            if transcript and transcript.full_text:
                self.db.create_processing_job(recording.id, "summary")
                self.db.update_recording_status(recording.id, "transcribed")
                queued_legacy += 1
            elif audio_path and audio_path.exists():
                self.db.create_processing_job(recording.id, "transcription")
                self.db.update_recording_status(recording.id, "pending")
                queued_legacy += 1
            else:
                self.db.update_recording_status(recording.id, "error")
                self.db.fail_processing_jobs_for_recording(
                    recording.id,
                    "Audio/transcript missing during startup recovery",
                )

        active_jobs = self.db.get_active_processing_jobs()
        if requeued or queued_legacy or active_jobs:
            self.status_label.setText(
                tr("Продолжаю очередь обработки: {count} задач", count=len(active_jobs))
            )
            self._load_history()
            QTimer.singleShot(0, self._process_next_processing_job)

    def _requeue_processing_job_for_later(
        self,
        job: ProcessingJob,
        reason: str,
    ) -> bool:
        if not job.id:
            return False

        requeued = self.db.requeue_processing_job(job.id, reason)
        if not requeued:
            return False

        self.db.update_recording_status(
            job.recording_id,
            self._queued_recording_status_for_job(job),
        )
        if job.id == self._active_processing_job_id:
            self._active_processing_job_id = None
            self._active_processing_job_type = None
            self._set_active_processing_recording_id(None)
        logger.warning(f"Requeued processing job {job.id}: {reason}")
        return True

    def _requeue_active_processing_job_for_later(self, reason: str) -> bool:
        if self._active_processing_job_id is None:
            return False

        job = self.db.get_processing_job(self._active_processing_job_id)
        if not job:
            self._active_processing_job_id = None
            self._active_processing_job_type = None
            self._set_active_processing_recording_id(None)
            return False

        return self._requeue_processing_job_for_later(job, reason)

    def _run_processing_watchdog(self) -> None:
        if self._cleanup_done:
            return

        requeued_count = 0
        for job in self.db.get_stale_running_processing_jobs(PROCESSING_STALE_SECONDS):
            if job.id == self._active_processing_job_id and self._has_active_processing_worker():
                logger.warning(
                    f"Processing job {job.id} has no recent progress but worker is still running"
                )
                continue

            reason = tr("Задача зависла без активного воркера, возвращена в очередь")
            if self._requeue_processing_job_for_later(job, reason):
                requeued_count += 1

        if requeued_count:
            self.status_label.setText(
                tr("Возвращено в очередь: {count} задач", count=requeued_count)
            )
            self._load_history()
            QTimer.singleShot(0, self._process_next_processing_job)

    def _has_active_recorder_setup_worker(self) -> bool:
        return bool(
            self._recorder_setup_worker and self._recorder_setup_worker.isRunning()
        )

    def _is_stop_in_progress(self) -> bool:
        return bool(
            (self._stop_worker and self._stop_worker.isRunning())
            or self._recorder_state_value() == "stopping"
        )

    def _ensure_recorder_ready(self, start_after_ready: bool = False) -> bool:
        """Initialize audio off the UI thread when recording is first needed."""
        if self.recorder is not None:
            return True

        if start_after_ready:
            self._start_after_recorder_ready = True

        if self._has_active_recorder_setup_worker():
            self.status_label.setText(tr("Подготовка аудио..."))
            return False

        self.status_label.setText(tr("Подготовка аудио..."))
        self._recording_state_signal.emit("preparing")
        self._recorder_setup_worker = RecorderSetupWorker(
            self.settings,
            self._on_audio_level_change,
            self._on_recording_state_change,
        )
        self._recorder_setup_worker.completed.connect(self._on_recorder_setup_finished)
        self._recorder_setup_worker.start()
        return False

    def _on_recorder_setup_finished(self, result):
        """Handle async audio initialization completion."""
        worker = self._recorder_setup_worker
        self._recorder_setup_worker = None
        if worker is not None:
            worker.deleteLater()

        should_start = self._start_after_recorder_ready
        self._start_after_recorder_ready = False

        if isinstance(result, Exception):
            self._recording_state_signal.emit("idle")
            self.status_label.setText(tr("Аудио не готово"))
            if should_start and not self._cleanup_done:
                QMessageBox.warning(
                    self,
                    tr("Ошибка"),
                    tr("Не удалось подготовить аудио. Проверьте настройки аудио устройства."),
                )
            return

        if self._cleanup_done:
            try:
                result.cleanup()
            except Exception:
                pass
            return

        self.recorder = result
        self.status_label.setText(tr("Готов к записи"))
        self._recording_state_signal.emit(self.recorder.state)

        if should_start:
            QTimer.singleShot(0, self._start_recording)

    def _recorder_state_value(self) -> str:
        if self.recorder is None:
            return "idle"
        return str(getattr(self.recorder.state, "value", self.recorder.state))

    def is_recording_active(self) -> bool:
        """Return whether the recorder is in a state that should stop on toggle/close."""
        return self._recorder_state_value() in {"recording", "paused"}

    def _start_recording(self):
        """Start audio recording."""
        if self._cleanup_done:
            return

        if self._is_stop_in_progress():
            self.status_label.setText(tr("Дождитесь сохранения текущей записи"))
            return

        if self.is_recording_active():
            self.status_label.setText(tr("Запись уже идёт"))
            logger.info("Start ignored: recording is already active")
            return

        if not self._ensure_recorder_ready(start_after_ready=True) or self.recorder is None:
            return

        title = format_recording_title()

        audio_path = self.recorder.start_recording(title=title)
        if audio_path:
            # Create database entry
            recording = Recording(
                title=title,
                audio_path=str(audio_path),
                status="recording",
            )
            try:
                recording_id = self.db.create_recording(recording)
            except Exception as e:
                logger.error(f"Failed to create recording row: {e}")
                capture_exception(e, "recording_database_create")
                self.status_label.setText(tr("Не удалось создать запись в базе"))
                QMessageBox.warning(
                    self,
                    tr("Ошибка"),
                    tr("Не удалось создать запись в базе:\n{error}", error=e),
                )
                return
            self._active_recording_id = recording_id

            # Refresh history and mark this recording as active
            self._load_history()
            self.history_list.set_active_recording_id(recording_id)

            self.status_label.setText(tr("Запись: {title}", title=title))
            logger.info(f"Recording started: {title}")
            track_event("recording_started")
        else:
            track_event("recording_start_failed", reason="audio_device")
            QMessageBox.warning(
                self,
                tr("Ошибка"),
                tr("Не удалось начать запись. Проверьте настройки аудио устройства."),
            )

    def _pause_recording(self):
        """Pause audio recording."""
        if self.recorder is None or self._is_stop_in_progress():
            return
        if self.recorder.pause_recording():
            self.status_label.setText(tr("Запись на паузе"))
            logger.info("Recording paused by user")

    def _resume_recording(self):
        """Resume audio recording."""
        if self.recorder is None or self._is_stop_in_progress():
            return
        if self.recorder.resume_recording():
            self.status_label.setText(tr("Запись") + "...")
            logger.info("Recording resumed by user")

    def _stop_recording(self, close_after_stop: bool = False):
        """Stop audio recording and save it without blocking the UI."""
        if self.recorder is None:
            if close_after_stop:
                QTimer.singleShot(0, self.close)
            return

        if self._is_stop_in_progress():
            self._close_after_stop = self._close_after_stop or close_after_stop
            self.status_label.setText(tr("Сохраняю запись..."))
            return

        if not self.is_recording_active():
            return

        self._close_after_stop = close_after_stop
        self.status_label.setText(tr("Сохраняю запись..."))
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.transcript_view.show_progress(tr("Сохраняю запись..."))
        self._recording_state_signal.emit("stopping")

        self._stop_worker = StopRecordingWorker(
            self.recorder,
            self.settings.silence_threshold,
        )
        self._stop_worker.completed.connect(self._on_stop_recording_finished)
        self._stop_worker.start()

    def _on_stop_recording_finished(self, result):
        """Finalize stopped recording after the worker has saved the WAV."""
        worker = self._stop_worker
        self._stop_worker = None
        if worker is not None:
            worker.deleteLater()

        close_after_stop = self._close_after_stop
        self._close_after_stop = False
        recording_id = self._active_recording_id

        self.progress_bar.setVisible(False)
        self.transcript_view.hide_progress()
        self._set_active_recording_id(None)

        if isinstance(result, Exception):
            capture_exception(result, "recording_save")
            track_event("recording_save_failed")
            if recording_id is not None:
                self.db.update_recording_status(recording_id, "error")
                self._load_history()
            self.status_label.setText(tr("Не удалось сохранить запись"))
            if not close_after_stop:
                QMessageBox.warning(
                    self,
                    tr("Ошибка"),
                    tr("Не удалось сохранить запись:\n{error}", error=result),
                )
        else:
            self._finalize_stopped_recording(
                result,
                recording_id=recording_id,
                start_processing=not close_after_stop,
                show_messages=not close_after_stop,
            )

        if close_after_stop:
            QTimer.singleShot(0, self.close)

    def _finalize_stopped_recording(
        self,
        result: StopRecordingResult,
        recording_id: Optional[int],
        start_processing: bool,
        show_messages: bool,
    ) -> None:
        """Update DB/UI after a recording has been saved."""
        audio_path = result.audio_path
        if not audio_path:
            track_event("recording_save_failed", reason="missing_audio_path")
            if recording_id is not None:
                self.db.update_recording_status(recording_id, "error")
                self._load_history()
            self.status_label.setText(tr("Не удалось сохранить запись"))
            return

        if recording_id is None:
            track_event("recording_saved", outcome="untracked")
            self.status_label.setText(tr("Запись сохранена"))
            return

        if result.duration_seconds is not None:
            self.db.update_recording_duration(
                recording_id,
                int(result.duration_seconds),
            )

        # Check minimum duration before transcription
        recording = self.db.get_recording(recording_id)
        if recording and recording.duration_seconds is not None:
            min_duration = self.settings.min_recording_duration
            if recording.duration_seconds < min_duration:
                logger.warning(
                    f"Recording too short ({recording.duration_seconds}s < {min_duration}s), "
                    "skipping transcription"
                )
                self.status_label.setText(
                    tr("Запись слишком короткая ({duration:.1f}s), транскрибация пропущена", duration=recording.duration_seconds)
                )
                self.db.update_recording_status(recording_id, "completed")
                self._load_history()
                track_event(
                    "recording_saved",
                    outcome="too_short",
                    duration=duration_bucket(recording.duration_seconds),
                )

                if show_messages:
                    QMessageBox.information(
                        self,
                        tr("Запись пропущена"),
                        (
                            f"{tr('Запись слишком короткая')}: {recording.duration_seconds:.1f} sec.\n"
                            + tr("Минимальная длительность для транскрибации: {min_duration} сек.", min_duration=min_duration)
                        ),
                    )
                return

        if result.is_silent:
            logger.warning("Recording is mostly silent, skipping transcription")
            self.status_label.setText(tr("Запись пустая (тишина), транскрибация пропущена"))
            self.db.update_recording_status(recording_id, "completed")
            self._load_history()
            track_event(
                "recording_saved",
                outcome="silent",
                duration=duration_bucket(result.duration_seconds),
            )

            if show_messages:
                QMessageBox.information(
                    self,
                    tr("Запись пропущена"),
                    "Recording contains no speech (silence only).\n"
                    + tr("Транскрибация пропущена."),
                )
            return

        if start_processing:
            self.status_label.setText(tr("Запись остановлена, начинаю транскрибацию..."))
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate

            self._queue_processing_job(recording_id, "transcription")
        else:
            self.db.update_recording_status(recording_id, "pending")
            self.db.create_processing_job(recording_id, "transcription")
            self.status_label.setText(tr("Запись сохранена"))

        # Refresh history
        self._load_history()
        track_event(
            "recording_saved",
            outcome="queued" if start_processing else "saved_for_later",
            duration=duration_bucket(result.duration_seconds),
        )

    def _on_transcription_progress(self, message: str):
        """Handle transcription progress updates."""
        self.status_label.setText(message)
        self._touch_active_processing_job(message)

    def _on_transcription_detailed_progress(self, current: int, total: int, message: str):
        """Handle detailed transcription progress updates."""
        self.transcript_view.update_progress(current, total, message)
        self.status_label.setText(message)
        self._touch_active_processing_job(message, current=current, total=total)

    def _is_recording_silent(self, audio_path: Path) -> bool:
        """
        Check if recording is mostly silent.

        Returns True if average RMS level is below threshold.
        """
        try:
            import numpy as np
            from pydub import AudioSegment

            # Load audio
            audio = AudioSegment.from_file(str(audio_path))

            # Get samples as numpy array
            samples = np.array(audio.get_array_of_samples(), dtype=np.float32)

            if len(samples) == 0:
                return True

            # Calculate RMS level
            rms = float(np.sqrt(np.mean(samples**2)))

            # Threshold for silence (configurable)
            silence_threshold = self.settings.silence_threshold

            is_silent = rms < silence_threshold

            logger.info(f"Audio silence check: RMS={rms:.1f}, threshold={silence_threshold}, silent={is_silent}")

            return is_silent

        except Exception as e:
            logger.error(f"Failed to check audio silence: {e}")
            # On error, don't skip transcription (false negative is better than false positive)
            return False

    def _on_transcription_finished(self, result):
        """Handle transcription completion."""
        if self._cleanup_done:
            return

        self.progress_bar.setVisible(False)
        self.transcript_view.hide_progress()

        if isinstance(result, Exception):
            capture_exception(result, "transcription")
            track_event("transcription_failed", error_type=type(result).__name__)
            message = self._format_processing_error(result, "transcription")
            self.status_label.setText(message)
            self._finish_active_processing_job(False, result)
            QMessageBox.warning(
                self,
                tr("Ошибка транскрибации"),
                message,
            )
        else:
            track_event("transcription_completed")
            self.status_label.setText(tr("Транскрипт готов, саммари добавлено в очередь"))

            # Show the new transcript
            if self._active_processing_recording_id is not None:
                recording = self.db.get_recording(self._active_processing_recording_id)
                if recording:
                    self._on_recording_selected(recording)
                    self._queue_processing_job(recording.id, "summary")
            self._finish_active_processing_job(True)

        # Refresh history
        self._load_history()

    def _on_audio_level_change(self, level: float):
        """Handle audio level updates from recording thread (emit signal)."""
        self._audio_level_signal.emit(level)

    def _update_audio_level_ui(self, level: float):
        """Update audio level UI (called in main thread via signal)."""
        self.recording_widget.set_audio_level(level)

    def _on_recording_state_change(self, state: object):
        """Handle recording state changes from recording thread (emit signal)."""
        self._recording_state_signal.emit(state)

    def _update_recording_state_ui(self, state: object):
        """Update recording state UI (called in main thread via signal)."""
        self.recording_widget.set_recording_state(state)

        state_value = str(getattr(state, "value", state))
        if state_value == "preparing":
            self.status_label.setText(tr("Подготовка аудио..."))
        elif state_value == "recording":
            self.status_label.setText(tr("Запись") + "...")
        elif state_value == "paused":
            self.status_label.setText(tr("Запись на паузе"))
        elif state_value == "stopping":
            self.status_label.setText(tr("Сохраняю запись..."))
        elif state_value == "idle":
            if not self.progress_bar.isVisible():
                self.status_label.setText(tr("Готов к записи"))

    def _on_recording_selected(self, recording: Recording):
        """Handle recording selection from history."""
        transcript = self.db.get_transcript(recording.id)
        segments = self.db.get_segments(transcript.id) if transcript else []
        summary = self.db.get_summary(recording.id)
        processing_job = self.db.get_latest_processing_job_for_recording(recording.id)

        audio_path = Path(recording.audio_path) if recording.audio_path else None
        if audio_path and not audio_path.is_absolute():
            audio_path = Path.cwd() / audio_path

        if audio_path and not audio_path.exists():
            self.transcript_view.show_file_missing(
                recording,
                transcript,
                segments,
                summary,
                processing_job=processing_job,
            )
        else:
            self.transcript_view.set_recording(
                recording,
                transcript,
                segments,
                summary,
                processing_job=processing_job,
            )

    def _on_delete_missing_requested(self, recording_id: int):
        """Handle delete request from transcript_view for recordings with missing files."""
        reply = QMessageBox.question(
            self,
            tr("Удалить запись"),
            tr("Удалить запись из истории?\n(Аудиофайл уже отсутствует, удалятся только данные в базе.)"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._on_recording_deleted(recording_id)

    def _is_recording_delete_blocked(self, recording_id: int) -> bool:
        """Return whether a recording is currently owned by an active worker."""
        if recording_id == self._active_recording_id:
            return self.is_recording_active() or self._is_stop_in_progress()

        if recording_id != self._active_processing_recording_id:
            return False

        if self._active_processing_job_id is not None:
            return True

        return bool(
            (self._transcription_worker and self._transcription_worker.isRunning())
            or (self._summary_worker and self._summary_worker.isRunning())
        )

    def _on_recording_deleted(self, recording_id: int):
        """Handle recording deletion (confirmation already done in history_list)."""
        try:
            if self._is_recording_delete_blocked(recording_id):
                logger.warning(f"Deletion blocked for active recording {recording_id}")
                self.status_label.setText(tr("Нельзя удалить активную запись"))
                QMessageBox.warning(
                    self,
                    tr("Запись активна"),
                    tr("Нельзя удалить запись, пока она записывается или обрабатывается."),
                )
                return

            recording = self.db.get_recording(recording_id)
            if not recording:
                logger.warning(f"Recording {recording_id} not found")
                return

            # Clear first to release QMediaPlayer file handle (prevents Windows lock)
            self.transcript_view.clear()
            QApplication.processEvents()

            self.db.delete_recording(recording_id)

            audio_path = Path(recording.audio_path)
            if audio_path.exists():
                try:
                    audio_path.unlink()
                except Exception as e:
                    logger.warning(f"Could not delete audio file {audio_path}: {e}")

            self._load_history()
            self.status_label.setText(tr("Запись удалена"))
            logger.info(f"Recording {recording_id} deleted")

        except Exception as e:
            logger.error(f"Failed to delete recording {recording_id}: {e}", exc_info=True)
            QMessageBox.critical(self, tr("Ошибка"), tr("Не удалось удалить:\n{error}", error=e))

    def _export_transcript(self, format_type: str, recording: Recording):
        """Export transcript to file."""
        from src.export import export_transcript

        transcript = self.db.get_transcript(recording.id)
        segments = []
        if transcript:
            segments = self.db.get_segments(transcript.id)
        summary = self.db.get_summary(recording.id)

        try:
            output_path = export_transcript(
                recording, transcript, segments, summary, format_type
            )
            self.status_label.setText(tr("Экспорт сохранён: {filename}", filename=output_path.name))

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(tr("Экспорт завершён"))
            msg_box.setText(tr("Файл сохранён:\n{output_path}", output_path=output_path))
            msg_box.setIcon(QMessageBox.Icon.Information)

            open_folder_btn = msg_box.addButton(tr("Открыть папку"), QMessageBox.ButtonRole.ActionRole)
            msg_box.addButton(QMessageBox.StandardButton.Ok)

            msg_box.exec()

            if msg_box.clickedButton() == open_folder_btn:
                subprocess.run(["explorer", "/select,", str(output_path)])
        except Exception as e:
            logger.error(f"Export failed: {e}")
            QMessageBox.warning(self, tr("Ошибка"), tr("Не удалось экспортировать:\n{error}", error=e))

    @staticmethod
    def _has_legacy_chunk_speaker_labels(
        segments: list[TranscriptSegment],
        duration_seconds: Optional[int] = None,
    ) -> bool:
        """Detect old diarized transcripts saved before chunk speaker remapping."""
        speaker_labels = {
            segment.speaker.strip()
            for segment in segments
            if segment.speaker and segment.speaker.strip()
        }
        if not speaker_labels:
            return False

        if any(not any(char.isalnum() for char in label) for label in speaker_labels):
            return True

        raw_letter_labels = [
            label for label in speaker_labels if re.fullmatch(r"[A-Z]", label)
        ]
        if len(raw_letter_labels) >= 3:
            return True

        return (
            bool(raw_letter_labels)
            and len(raw_letter_labels) == len(speaker_labels)
            and duration_seconds is not None
            and duration_seconds > 600
        )

    def _retry_transcription(self, recording: Recording):
        """Retry transcription or summary for a recording.

        Smart retry logic:
        - If transcript exists → only regenerate summary (faster, cheaper)
        - If transcript has old chunk-local speaker labels → full transcription
        - If no transcript → full transcription + summary
        """
        audio_path = Path(recording.audio_path)

        # Check if already processing
        if self._transcription_worker and self._transcription_worker.isRunning():
            QMessageBox.warning(
                self,
                tr("Подождите"),
                tr("Транскрибация уже выполняется. Дождитесь завершения."),
            )
            return

        if self._summary_worker and self._summary_worker.isRunning():
            QMessageBox.warning(
                self,
                tr("Подождите"),
                tr("Генерация саммари уже выполняется. Дождитесь завершения."),
            )
            return

        # Check if transcript already exists
        existing_transcript = self.db.get_transcript(recording.id)
        existing_segments: list[TranscriptSegment] = []
        needs_speaker_rebuild = False
        if existing_transcript:
            existing_segments = self.db.get_segments(existing_transcript.id)
            needs_speaker_rebuild = (
                self.settings.transcription_model == "gpt-4o-transcribe-diarize"
                and self._has_legacy_chunk_speaker_labels(
                    existing_segments,
                    recording.duration_seconds,
                )
            )

        if existing_transcript and existing_transcript.full_text and not needs_speaker_rebuild:
            # Transcript exists → only regenerate summary (skip expensive Whisper call)
            logger.info(f"Transcript exists for recording {recording.id}, regenerating summary only")

            self.status_label.setText(tr("Саммари добавлено в очередь..."))
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)

            self._queue_processing_job(recording.id, "summary")

        else:
            # No transcript → full transcription + summary
            if not audio_path.exists():
                QMessageBox.warning(
                    self,
                    tr("Ошибка"),
                    tr("Аудио файл не найден:\n{audio_path}", audio_path=audio_path),
                )
                return

            # Check minimum duration
            min_duration = self.settings.min_recording_duration
            if recording.duration_seconds is not None and recording.duration_seconds < min_duration:
                QMessageBox.warning(
                    self,
                    tr("Запись слишком короткая"),
                    (
                        f"Recording is {recording.duration_seconds:.1f} sec.\n"
                        + tr("Минимальная длительность для транскрибации: {min_duration} сек.", min_duration=min_duration)
                    ),
                )
                return

            # Check if recording is mostly silent
            if self._is_recording_silent(audio_path):
                QMessageBox.warning(
                    self,
                    tr("Запись пустая"),
                    "Recording contains no speech (silence only).\n"
                    + tr("Транскрибация невозможна."),
                )
                return

            if needs_speaker_rebuild:
                logger.info(
                    f"Legacy chunk speaker labels found for recording {recording.id}, "
                    "starting full retranscription"
                )
            else:
                logger.info(f"No transcript for recording {recording.id}, starting full transcription")

            self.status_label.setText(tr("Транскрибация добавлена в очередь..."))
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)

            if existing_transcript:
                self.db.delete_transcript(existing_transcript.id)

            old_summary = self.db.get_summary(recording.id)
            if old_summary:
                self.db.delete_summary(old_summary.id)

            self._queue_processing_job(recording.id, "transcription")

        # Refresh history
        self._load_history()

    def _on_summary_finished(self, result):
        """Handle summary-only completion."""
        if self._cleanup_done:
            return

        self.progress_bar.setVisible(False)
        self.transcript_view.hide_progress()

        if isinstance(result, Exception):
            capture_exception(result, "summary")
            track_event("summary_failed", error_type=type(result).__name__)
            message = self._format_processing_error(result, "summary")
            self.status_label.setText(message)
            self._finish_active_processing_job(False, result)
            QMessageBox.warning(
                self,
                tr("Ошибка генерации саммари"),
                message,
            )
        else:
            track_event("summary_completed")
            self.status_label.setText(tr("Саммари сгенерировано успешно"))
            active_recording_id = self._active_processing_recording_id
            self._finish_active_processing_job(True)
            # Refresh current view
            if active_recording_id is not None:
                recording = self.db.get_recording(active_recording_id)
                if recording:
                    self._on_recording_selected(recording)

        # Refresh history
        self._load_history()

    def _format_processing_error(self, error: Exception, kind: str) -> str:
        """Convert provider/API errors into actionable UI text."""
        raw = str(error)
        lower = raw.lower()
        if "openrouter" in lower:
            service = "OpenRouter"
        elif "openai" in lower:
            service = "OpenAI"
        elif "429" in lower or "rate limit" in lower:
            service = tr("провайдера API")
        else:
            service = "API"

        if "insufficient" in lower or "credits" in lower or "balance" in lower:
            return (
                tr("Недостаточно баланса {service}. Текст записи сохранён, саммари можно повторить после пополнения.", service=service)
                if kind == "summary"
                else tr("Недостаточно баланса {service}. Пополните баланс и повторите транскрибацию.", service=service)
            )
        if "429" in lower or "rate limit" in lower:
            return (
                f"{service} temporarily limited requests. "
                + tr("Повторить позже или выберите другую модель.")
            )
        if "json" in lower or "unterminated" in lower:
            return tr("Модель вернула неполный JSON. Текст записи сохранён; повторите саммари, приложение попробует chunked-обработку.")
        if "audio file not found" in lower or "audio" in lower and "not found" in lower:
            return tr("Аудиофайл не найден. Транскрибацию нельзя продолжить без исходной записи.")

        action = tr("саммари") if kind == "summary" else tr("транскрибацию")
        return tr("Не удалось выполнить {action}: {raw}", action=action, raw=raw)

    def _open_settings(self):
        """Open settings dialog."""
        from src.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self)
        if dialog.exec():
            # Reload settings
            from src.utils.config import reload_settings

            old_trigger_config = (
                self.settings.trigger_mode,
                self.settings.auto_trigger_enabled,
                self.settings.process_monitor_enabled,
                self.settings.vad_enabled,
                self.settings.vad_aggressiveness,
                self.settings.vad_speech_threshold_seconds,
                self.settings.vad_silence_threshold_seconds,
            )
            self.settings = reload_settings()
            from src.utils.telemetry import setup_telemetry

            setup_telemetry(self.settings)

            # Update recorder microphone settings
            from src.utils.security import get_microphone_settings

            mic_settings = get_microphone_settings()
            if self.is_recording_active():
                self.status_label.setText(tr("Настройки сохранены, аудио применится после записи"))
            elif self.recorder is not None:
                self.recorder.sample_rate = self.settings.sample_rate
                self.recorder.channels = self.settings.channels
                if self.settings.audio_device_index is not None:
                    self.recorder.set_device(self.settings.audio_device_index)
                else:
                    self.recorder.set_default_device()
                self.recorder.set_microphone(
                    device_index=mic_settings.get("device_index"),
                    enabled=mic_settings.get("enabled", True),
                    volume=mic_settings.get("volume", 1.0),
                )

            new_trigger_config = (
                self.settings.trigger_mode,
                self.settings.auto_trigger_enabled,
                self.settings.process_monitor_enabled,
                self.settings.vad_enabled,
                self.settings.vad_aggressiveness,
                self.settings.vad_speech_threshold_seconds,
                self.settings.vad_silence_threshold_seconds,
            )
            if old_trigger_config != new_trigger_config:
                self._restart_auto_trigger()

            if self.status_label.text() != tr("Настройки сохранены, аудио применится после записи"):
                self.status_label.setText(tr("Настройки сохранены"))

    def _open_feedback(self):
        """Open privacy-safe feedback routes."""
        from src.ui.feedback_dialog import FeedbackDialog

        track_event("feedback_opened")
        FeedbackDialog(self).exec()

    def _check_for_updates_silently(self) -> None:
        self._update_manager.check(silent=True)

    def _check_for_updates(self) -> None:
        self._update_manager.check(silent=False, force=True)

    def _restart_auto_trigger(self):
        """Restart auto-trigger with new settings."""
        try:
            from src.core.auto_trigger.trigger_manager import TriggerManager, TriggerMode
        except Exception as e:
            logger.error(f"Failed to load auto-trigger components: {e}")
            return

        if self.trigger_manager is not None:
            self.trigger_manager.stop()

        mode_map = {
            "manual": TriggerMode.MANUAL,
            "notification": TriggerMode.NOTIFICATION,
            "process": TriggerMode.PROCESS,
            "vad": TriggerMode.VAD,
            "combined": TriggerMode.COMBINED,
        }
        mode = mode_map.get(self.settings.trigger_mode, TriggerMode.NOTIFICATION)

        self.trigger_manager = TriggerManager(
            on_start_recording=self._on_auto_trigger_start,
            on_stop_recording=self._on_auto_trigger_stop,
            on_meeting_detected=self._on_meeting_detected,
        )
        self.trigger_manager.set_mode(mode)

        if self.settings.auto_trigger_enabled and mode != TriggerMode.MANUAL:
            self.trigger_manager.start()
            logger.info(f"Auto-trigger restarted in {mode.value} mode")

    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            tr("О программе"),
            f"Meeting Note v{__version__}\n\n"
            + tr("Приложение для записи и транскрибации онлайн-звонков.\n\n")
            + "Uses OpenAI speech-to-text models for transcription\n"
            + "and OpenRouter chat models for meeting summaries.",
        )

    def _confirm_close_during_processing(self) -> bool:
        job_label = self._processing_label(self._active_processing_job_type)
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(tr("Обработка идёт"))
        msg_box.setText(
            tr(
                "{job_label} ещё выполняется. Закрыть приложение и продолжить после следующего запуска?",
                job_label=job_label,
            )
        )
        msg_box.setIcon(QMessageBox.Icon.Question)
        wait_button = msg_box.addButton(tr("Дождаться"), QMessageBox.ButtonRole.RejectRole)
        close_button = msg_box.addButton(
            tr("Закрыть и продолжить позже"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        msg_box.setDefaultButton(wait_button)
        msg_box.exec()
        return msg_box.clickedButton() == close_button

    def closeEvent(self, event):
        """Handle window close."""
        if self._is_stop_in_progress():
            self._close_after_stop = True
            self.status_label.setText(tr("Закрываю после сохранения записи..."))
            event.ignore()
            return

        # Stop recording if active (including paused state)
        if self.is_recording_active() and self.recorder is not None:
            reply = QMessageBox.question(
                self,
                tr("Запись активна"),
                tr("Идёт запись. Остановить и выйти?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self._stop_recording(close_after_stop=True)
            event.ignore()
            return

        if self._has_active_processing_worker() and not self._confirm_close_during_processing():
            event.ignore()
            return

        self.cleanup_runtime_services()

        event.accept()

    def cleanup_runtime_services(self):
        """Stop background services and release audio resources."""
        if self._cleanup_done:
            return
        self._cleanup_done = True

        if self._processing_watchdog_timer.isActive():
            self._processing_watchdog_timer.stop()

        self._update_manager.cleanup()

        try:
            self._requeue_active_processing_job_for_later(
                tr("Приложение закрыто во время обработки")
            )
        except Exception as e:
            logger.warning(f"Failed to requeue active job on shutdown: {e}")
            self._active_processing_job_id = None
            self._active_processing_job_type = None
            self._set_active_processing_recording_id(None)

        if self.trigger_manager is not None:
            self.trigger_manager.stop()
            self.trigger_manager = None

        self._notification_manager.hide_notification()

        if self._recorder_setup_worker and self._recorder_setup_worker.isRunning():
            self._recorder_setup_worker.requestInterruption()
            if not self._recorder_setup_worker.wait(750):
                logger.warning("Recorder setup still running during shutdown")

        if self._stop_worker and self._stop_worker.isRunning():
            if not self._stop_worker.wait(750):
                logger.warning("Recording stop worker still running during shutdown")

        if self.recorder is not None:
            self.recorder.cleanup()
            self.recorder = None

        if self._transcription_worker and self._transcription_worker.isRunning():
            self._transcription_worker.requestInterruption()
            if not self._transcription_worker.wait(750):
                logger.warning("Transcription worker left running during shutdown")
        if self._summary_worker and self._summary_worker.isRunning():
            self._summary_worker.requestInterruption()
            if not self._summary_worker.wait(750):
                logger.warning("Summary worker left running during shutdown")
