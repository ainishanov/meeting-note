"""Auto-trigger manager combining process monitoring and VAD."""

from enum import Enum
from typing import Callable, Optional

from loguru import logger

from src.core.auto_trigger.process_monitor import ProcessMonitor
from src.core.auto_trigger.vad_detector import VoiceActivityDetector
from src.utils.config import get_settings


class TriggerMode(Enum):
    """Recording trigger mode."""

    MANUAL = "manual"
    PROCESS = "process"
    VAD = "vad"
    COMBINED = "combined"
    NOTIFICATION = "notification"  # Show popup instead of auto-start


class TriggerManager:
    """
    Manages automatic recording triggers.

    Combines process monitoring and voice activity detection
    to automatically start/stop recordings.
    """

    def __init__(
        self,
        on_start_recording: Optional[Callable[[str], None]] = None,
        on_stop_recording: Optional[Callable[[str], None]] = None,
        on_meeting_detected: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize trigger manager.

        Args:
            on_start_recording: Callback to start recording (receives trigger reason)
            on_stop_recording: Callback to stop recording (receives trigger reason)
            on_meeting_detected: Callback when meeting detected (for notification mode)
        """
        self.on_start_recording = on_start_recording
        self.on_stop_recording = on_stop_recording
        self.on_meeting_detected = on_meeting_detected

        self.settings = get_settings()

        self._mode = TriggerMode.COMBINED
        self._process_monitor: Optional[ProcessMonitor] = None
        self._vad_detector: Optional[VoiceActivityDetector] = None

        self._is_recording = False
        self._recording_started_by: Optional[str] = None
        self._notification_shown_for: Optional[str] = None

    def set_mode(self, mode: TriggerMode) -> None:
        """Set the trigger mode."""
        self._mode = mode
        logger.info(f"Trigger mode set to: {mode.value}")

    def start(self) -> None:
        """Start auto-trigger monitoring."""
        if self._mode == TriggerMode.MANUAL:
            logger.info("Manual mode - auto-triggers disabled")
            return

        # Start process monitor (for PROCESS, COMBINED, and NOTIFICATION modes)
        if self._mode in (TriggerMode.PROCESS, TriggerMode.COMBINED, TriggerMode.NOTIFICATION):
            if self.settings.process_monitor_enabled:
                self._process_monitor = ProcessMonitor(
                    on_meeting_start=self._on_meeting_start,
                    on_meeting_end=self._on_meeting_end,
                )
                self._process_monitor.start()

        # Start VAD (only for VAD and COMBINED modes)
        if self._mode in (TriggerMode.VAD, TriggerMode.COMBINED):
            if self.settings.vad_enabled:
                self._vad_detector = VoiceActivityDetector(
                    sample_rate=self.settings.sample_rate,
                    aggressiveness=self.settings.vad_aggressiveness,
                    speech_threshold_seconds=self.settings.vad_speech_threshold_seconds,
                    silence_threshold_seconds=self.settings.vad_silence_threshold_seconds,
                    on_speech_start=self._on_speech_start,
                    on_speech_end=self._on_speech_end,
                )
                self._vad_detector.start()

        logger.info(f"Auto-trigger started in {self._mode.value} mode")

    def stop(self) -> None:
        """Stop auto-trigger monitoring."""
        if self._process_monitor:
            self._process_monitor.stop()
            self._process_monitor = None

        if self._vad_detector:
            self._vad_detector.stop()
            self._vad_detector = None

        logger.info("Auto-trigger stopped")

    def _on_meeting_start(self, app_name: str) -> None:
        """Handle meeting app detected."""
        logger.info(f"Meeting app started: {app_name}")

        if self._mode == TriggerMode.PROCESS:
            # In process-only mode, start recording immediately
            self._trigger_start(f"process:{app_name}")
        elif self._mode == TriggerMode.COMBINED:
            # In combined mode, just note that meeting is active
            # VAD will trigger actual recording
            logger.info(
                "Meeting detected, waiting for voice activity to start recording"
            )
        elif self._mode == TriggerMode.NOTIFICATION:
            # In notification mode, show popup instead of auto-starting
            if not self._is_recording and self._notification_shown_for != app_name:
                self._notification_shown_for = app_name
                if self.on_meeting_detected:
                    self.on_meeting_detected(app_name)
                logger.info(f"Notification shown for: {app_name}")

    def _on_meeting_end(self, app_name: str) -> None:
        """Handle meeting app closed."""
        logger.info(f"Meeting app ended: {app_name}")

        # Reset notification state when meeting ends
        if self._notification_shown_for == app_name:
            self._notification_shown_for = None

        if self._is_recording and self._recording_started_by:
            if self._recording_started_by.startswith("process:"):
                self._trigger_stop(f"process:{app_name} closed")

    def _on_speech_start(self) -> None:
        """Handle speech detection start."""
        logger.info("Speech activity detected")

        if self._mode == TriggerMode.VAD:
            # In VAD-only mode, start recording on speech
            self._trigger_start("vad:speech")
        elif self._mode == TriggerMode.COMBINED:
            # In combined mode, only start if meeting is active
            if self._process_monitor and self._process_monitor.is_meeting_active():
                self._trigger_start("vad:speech (meeting active)")
            else:
                logger.info("Speech detected but no meeting active, ignoring")

    def _on_speech_end(self) -> None:
        """Handle speech detection end (prolonged silence)."""
        logger.info("Prolonged silence detected")

        if self._is_recording and self._recording_started_by:
            if self._recording_started_by.startswith("vad:"):
                self._trigger_stop("vad:silence")

    def _trigger_start(self, reason: str) -> None:
        """Trigger recording start."""
        if self._is_recording:
            logger.debug(f"Already recording, ignoring start trigger: {reason}")
            return

        self._is_recording = True
        self._recording_started_by = reason

        # Hide notification if showing
        self._notification_shown_for = None

        logger.info(f"Auto-triggering recording start: {reason}")

        if self.on_start_recording:
            self.on_start_recording(reason)

    def _trigger_stop(self, reason: str) -> None:
        """Trigger recording stop."""
        if not self._is_recording:
            logger.debug(f"Not recording, ignoring stop trigger: {reason}")
            return

        self._is_recording = False
        self._recording_started_by = None
        self._notification_shown_for = None

        logger.info(f"Auto-triggering recording stop: {reason}")

        if self.on_stop_recording:
            self.on_stop_recording(reason)

    def is_monitoring(self) -> bool:
        """Check if monitoring is active."""
        process_active = self._process_monitor is not None
        vad_active = self._vad_detector is not None
        return process_active or vad_active

    def get_status(self) -> dict:
        """Get current trigger status."""
        status = {
            "mode": self._mode.value,
            "is_recording": self._is_recording,
            "started_by": self._recording_started_by,
        }

        if self._process_monitor:
            status["active_meetings"] = list(
                self._process_monitor.get_active_meetings()
            )
        else:
            status["active_meetings"] = []

        if self._vad_detector:
            status["is_speaking"] = self._vad_detector.is_speaking()
            status["speech_duration"] = self._vad_detector.get_speech_duration()
            status["silence_duration"] = self._vad_detector.get_silence_duration()

        return status
