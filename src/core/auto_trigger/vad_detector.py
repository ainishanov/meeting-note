"""Voice Activity Detection for automatic recording trigger."""

import collections
import threading
import time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
from loguru import logger

try:
    import webrtcvad

    HAS_WEBRTCVAD = True
except ImportError:
    HAS_WEBRTCVAD = False
    logger.warning("webrtcvad not installed, VAD detection disabled")


class VoiceActivityDetector:
    """
    Voice Activity Detection using WebRTC VAD.

    Monitors audio input and detects speech presence.
    Can trigger callbacks when speech starts/stops.
    """

    # WebRTC VAD only supports specific sample rates
    SUPPORTED_SAMPLE_RATES = [8000, 16000, 32000, 48000]
    # Frame duration in ms (WebRTC VAD supports 10, 20, 30 ms)
    FRAME_DURATION_MS = 30

    def __init__(
        self,
        sample_rate: int = 16000,
        aggressiveness: int = 2,
        speech_threshold_seconds: float = 10.0,
        silence_threshold_seconds: float = 30.0,
        on_speech_start: Optional[Callable[[], None]] = None,
        on_speech_end: Optional[Callable[[], None]] = None,
        device_index: Optional[int] = None,
    ):
        """
        Initialize VAD detector.

        Args:
            sample_rate: Audio sample rate (must be 8000, 16000, 32000, or 48000)
            aggressiveness: VAD aggressiveness (0-3, higher = more aggressive)
            speech_threshold_seconds: Seconds of speech before triggering start
            silence_threshold_seconds: Seconds of silence before triggering end
            on_speech_start: Callback when sustained speech detected
            on_speech_end: Callback when sustained silence detected
            device_index: Audio input device index
        """
        if sample_rate not in self.SUPPORTED_SAMPLE_RATES:
            logger.warning(
                f"Sample rate {sample_rate} not supported, using 16000"
            )
            sample_rate = 16000

        self.sample_rate = sample_rate
        self.aggressiveness = aggressiveness
        self.speech_threshold_seconds = speech_threshold_seconds
        self.silence_threshold_seconds = silence_threshold_seconds
        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end
        self.device_index = device_index

        self._vad = None
        self._running = False
        self._stream: Optional[sd.InputStream] = None
        self._thread: Optional[threading.Thread] = None

        # State tracking
        self._is_speaking = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._frames_per_second = 1000 // self.FRAME_DURATION_MS

        # Calculate frame size
        self._frame_size = int(sample_rate * self.FRAME_DURATION_MS / 1000)

        # Ring buffer for audio frames
        self._buffer = collections.deque(maxlen=100)

        if HAS_WEBRTCVAD:
            self._vad = webrtcvad.Vad(aggressiveness)

    def start(self) -> bool:
        """Start VAD monitoring."""
        if not HAS_WEBRTCVAD:
            logger.error("webrtcvad not available")
            return False

        if self._running:
            return True

        try:
            self._running = True
            self._speech_frames = 0
            self._silence_frames = 0
            self._is_speaking = False

            # Start audio stream
            self._stream = sd.InputStream(
                device=self.device_index,
                channels=1,
                samplerate=self.sample_rate,
                dtype=np.int16,
                blocksize=self._frame_size,
                callback=self._audio_callback,
            )
            self._stream.start()

            # Start processing thread
            self._thread = threading.Thread(target=self._process_loop, daemon=True)
            self._thread.start()

            logger.info("VAD detector started")
            return True

        except Exception as e:
            logger.error(f"Failed to start VAD: {e}")
            self._running = False
            return False

    def stop(self) -> None:
        """Stop VAD monitoring."""
        self._running = False

        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

        logger.info("VAD detector stopped")

    def _audio_callback(
        self, indata: np.ndarray, frames: int, time_info: dict, status: sd.CallbackFlags
    ) -> None:
        """Callback for audio stream."""
        if status:
            logger.debug(f"Audio callback status: {status}")

        if self._running:
            # Convert to bytes for WebRTC VAD
            audio_bytes = indata.tobytes()
            self._buffer.append(audio_bytes)

    def _process_loop(self) -> None:
        """Main VAD processing loop."""
        while self._running:
            if not self._buffer:
                time.sleep(0.01)
                continue

            try:
                # Get frame from buffer
                frame = self._buffer.popleft()

                # Check if frame contains speech
                is_speech = self._vad.is_speech(frame, self.sample_rate)

                if is_speech:
                    self._speech_frames += 1
                    self._silence_frames = 0

                    # Check if we've exceeded speech threshold
                    speech_seconds = self._speech_frames / self._frames_per_second
                    if (
                        not self._is_speaking
                        and speech_seconds >= self.speech_threshold_seconds
                    ):
                        self._is_speaking = True
                        logger.info(
                            f"Speech detected ({speech_seconds:.1f}s of speech)"
                        )
                        if self.on_speech_start:
                            self.on_speech_start()
                else:
                    self._silence_frames += 1

                    # Check if we've exceeded silence threshold
                    if self._is_speaking:
                        silence_seconds = self._silence_frames / self._frames_per_second
                        if silence_seconds >= self.silence_threshold_seconds:
                            self._is_speaking = False
                            self._speech_frames = 0
                            logger.info(
                                f"Silence detected ({silence_seconds:.1f}s of silence)"
                            )
                            if self.on_speech_end:
                                self.on_speech_end()

            except Exception as e:
                logger.error(f"VAD processing error: {e}")

    def is_speaking(self) -> bool:
        """Check if speech is currently detected."""
        return self._is_speaking

    def get_speech_duration(self) -> float:
        """Get current continuous speech duration in seconds."""
        return self._speech_frames / self._frames_per_second

    def get_silence_duration(self) -> float:
        """Get current continuous silence duration in seconds."""
        return self._silence_frames / self._frames_per_second
