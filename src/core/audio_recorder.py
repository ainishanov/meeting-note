"""Audio recording using WASAPI loopback for system audio capture."""

import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from loguru import logger
from scipy.io import wavfile

try:
    import pyaudiowpatch as pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    logger.warning("PyAudioWPatch not installed. Install with: pip install PyAudioWPatch")


class RecordingState(Enum):
    """Recording state enum."""

    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"
    STOPPING = "stopping"


@dataclass
class AudioDevice:
    """Audio device information."""

    index: int
    name: str
    channels: int
    sample_rate: float
    is_loopback: bool = False


class AudioRecorder:
    """
    Audio recorder using WASAPI loopback for system audio capture.

    Captures all system audio output (from any application) using
    Windows Audio Session API (WASAPI) loopback mode via PyAudioWPatch.
    Optionally also captures microphone input and mixes both streams.
    """

    def __init__(
        self,
        output_dir: Path,
        sample_rate: int = 16000,
        channels: int = 1,
        on_level_change: Optional[Callable[[float], None]] = None,
        on_state_change: Optional[Callable[[RecordingState], None]] = None,
        microphone_enabled: bool = False,
        microphone_device_index: Optional[int] = None,
        microphone_volume: float = 1.0,
    ):
        """
        Initialize audio recorder.

        Args:
            output_dir: Directory for saving recordings
            sample_rate: Audio sample rate (16000 recommended for transcription)
            channels: Number of audio channels (1=mono, 2=stereo)
            on_level_change: Callback for audio level updates (0.0-1.0)
            on_state_change: Callback for recording state changes
            microphone_enabled: Enable microphone recording in addition to system audio
            microphone_device_index: Microphone device index (None for default)
            microphone_volume: Microphone volume multiplier for mixing (0.0-2.0)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.sample_rate = sample_rate
        self.channels = channels
        self.on_level_change = on_level_change
        self.on_state_change = on_state_change

        # Microphone settings
        self.microphone_enabled = microphone_enabled
        self.microphone_device_index = microphone_device_index
        self.microphone_volume = microphone_volume

        self._state = RecordingState.IDLE
        self._stream = None
        self._pyaudio: Optional[pyaudio.PyAudio] = None
        self._audio_buffer: list[bytes] = []  # System audio buffer
        self._mic_buffer: list[bytes] = []  # Microphone audio buffer
        self._current_file: Optional[Path] = None
        self._recording_start_time: Optional[float] = None
        self._lock = threading.Lock()
        self._mic_lock = threading.Lock()  # Separate lock for microphone buffer
        self._recording_thread: Optional[threading.Thread] = None
        self._mic_thread: Optional[threading.Thread] = None  # Microphone recording thread
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()  # For pause functionality
        self._paused_duration: float = 0.0  # Track total paused time

        # Device info
        self._loopback_device: Optional[AudioDevice] = None
        self._mic_device: Optional[AudioDevice] = None
        self._device_sample_rate: int = 48000
        self._device_channels: int = 2
        self._mic_sample_rate: int = 48000
        self._mic_channels: int = 1

        # Initialize PyAudio and find loopback device
        self._init_pyaudio()

    def _init_pyaudio(self) -> None:
        """Initialize PyAudio and find loopback device."""
        if not PYAUDIO_AVAILABLE:
            logger.error("PyAudioWPatch is not available")
            return

        try:
            self._pyaudio = pyaudio.PyAudio()
            self._loopback_device = self._find_loopback_device()
            if self.microphone_enabled:
                self._mic_device = self._find_microphone_device()
        except Exception as e:
            logger.error(f"Failed to initialize PyAudio: {e}")

    def _find_microphone_device(self) -> Optional[AudioDevice]:
        """Find microphone device for recording."""
        if not self._pyaudio:
            return None

        try:
            # If specific device index is set, use it
            if self.microphone_device_index is not None:
                device = self._pyaudio.get_device_info_by_index(self.microphone_device_index)
                if device["maxInputChannels"] > 0:
                    self._mic_sample_rate = int(device["defaultSampleRate"])
                    self._mic_channels = device["maxInputChannels"]
                    logger.info(f"Using specified microphone: {device['name']} (index {self.microphone_device_index})")
                    return AudioDevice(
                        index=self.microphone_device_index,
                        name=device["name"],
                        channels=device["maxInputChannels"],
                        sample_rate=device["defaultSampleRate"],
                        is_loopback=False,
                    )

            # Use default input device
            default_input = self._pyaudio.get_default_input_device_info()
            self._mic_sample_rate = int(default_input["defaultSampleRate"])
            self._mic_channels = default_input["maxInputChannels"]
            logger.info(f"Using default microphone: {default_input['name']} (index {default_input['index']})")
            return AudioDevice(
                index=default_input["index"],
                name=default_input["name"],
                channels=default_input["maxInputChannels"],
                sample_rate=default_input["defaultSampleRate"],
                is_loopback=False,
            )

        except Exception as e:
            logger.error(f"Error finding microphone device: {e}")
            return None

    @property
    def state(self) -> RecordingState:
        """Get current recording state."""
        return self._state

    @state.setter
    def state(self, value: RecordingState) -> None:
        """Set recording state and notify callback."""
        self._state = value
        if self.on_state_change:
            self.on_state_change(value)

    @property
    def duration(self) -> float:
        """Get current recording duration in seconds."""
        if self._recording_start_time is None:
            return 0.0
        return time.time() - self._recording_start_time

    def _find_loopback_device(self) -> Optional[AudioDevice]:
        """Find WASAPI loopback device for system audio capture."""
        if not self._pyaudio:
            return None

        try:
            # Try to get WASAPI info - this is the key to loopback
            wasapi_info = self._pyaudio.get_host_api_info_by_type(pyaudio.paWASAPI)

            # Get default output device (speakers) - we'll capture its loopback
            default_speakers = self._pyaudio.get_device_info_by_index(
                wasapi_info["defaultOutputDevice"]
            )

            # Check if loopback is supported
            if not default_speakers.get("isLoopbackDevice", False):
                # Try to find loopback device for default speakers
                for i in range(self._pyaudio.get_device_count()):
                    device = self._pyaudio.get_device_info_by_index(i)
                    # Loopback devices have isLoopbackDevice flag
                    if device.get("isLoopbackDevice", False):
                        logger.info(f"Found loopback device: {device['name']} (index {i})")
                        self._device_sample_rate = int(device["defaultSampleRate"])
                        self._device_channels = device["maxInputChannels"]
                        return AudioDevice(
                            index=i,
                            name=device["name"],
                            channels=device["maxInputChannels"],
                            sample_rate=device["defaultSampleRate"],
                            is_loopback=True,
                        )

            # Use default speakers as loopback source
            logger.info(f"Using default speakers for loopback: {default_speakers['name']}")
            self._device_sample_rate = int(default_speakers["defaultSampleRate"])
            self._device_channels = max(default_speakers["maxInputChannels"],
                                        default_speakers["maxOutputChannels"])
            if self._device_channels == 0:
                self._device_channels = 2

            return AudioDevice(
                index=default_speakers["index"],
                name=default_speakers["name"] + " (Loopback)",
                channels=self._device_channels,
                sample_rate=default_speakers["defaultSampleRate"],
                is_loopback=True,
            )

        except Exception as e:
            logger.error(f"Error finding loopback device: {e}")
            # Fall back to default input
            try:
                default_input = self._pyaudio.get_default_input_device_info()
                logger.warning(f"Falling back to default input: {default_input['name']}")
                self._device_sample_rate = int(default_input["defaultSampleRate"])
                self._device_channels = default_input["maxInputChannels"]
                return AudioDevice(
                    index=default_input["index"],
                    name=default_input["name"],
                    channels=default_input["maxInputChannels"],
                    sample_rate=default_input["defaultSampleRate"],
                    is_loopback=False,
                )
            except Exception as e2:
                logger.error(f"Error finding any input device: {e2}")
                return None

    def get_available_devices(self) -> list[AudioDevice]:
        """Get list of available audio input devices including loopback."""
        devices = []
        if not self._pyaudio:
            return devices

        try:
            for i in range(self._pyaudio.get_device_count()):
                device = self._pyaudio.get_device_info_by_index(i)
                # Include devices that can be used for input or are loopback
                is_loopback = device.get("isLoopbackDevice", False)
                if device["maxInputChannels"] > 0 or is_loopback:
                    devices.append(
                        AudioDevice(
                            index=i,
                            name=device["name"] + (" (Loopback)" if is_loopback else ""),
                            channels=max(device["maxInputChannels"], device["maxOutputChannels"]),
                            sample_rate=device["defaultSampleRate"],
                            is_loopback=is_loopback,
                        )
                    )
        except Exception as e:
            logger.error(f"Error listing devices: {e}")
        return devices

    def get_microphone_devices(self) -> list[AudioDevice]:
        """Get list of available microphone devices (non-loopback input devices)."""
        devices = []
        if not self._pyaudio:
            return devices

        try:
            for i in range(self._pyaudio.get_device_count()):
                device = self._pyaudio.get_device_info_by_index(i)
                is_loopback = device.get("isLoopbackDevice", False)
                # Only include non-loopback input devices (real microphones)
                if device["maxInputChannels"] > 0 and not is_loopback:
                    devices.append(
                        AudioDevice(
                            index=i,
                            name=device["name"],
                            channels=device["maxInputChannels"],
                            sample_rate=device["defaultSampleRate"],
                            is_loopback=False,
                        )
                    )
        except Exception as e:
            logger.error(f"Error listing microphone devices: {e}")
        return devices

    def set_microphone(self, device_index: Optional[int], enabled: bool = True, volume: float = 1.0) -> bool:
        """
        Set microphone settings.

        Args:
            device_index: Microphone device index (None for default)
            enabled: Enable microphone recording
            volume: Microphone volume multiplier (0.0-2.0)

        Returns:
            True if settings were applied successfully
        """
        if self._state == RecordingState.RECORDING:
            logger.warning("Cannot change microphone while recording")
            return False

        self.microphone_enabled = enabled
        self.microphone_device_index = device_index
        self.microphone_volume = max(0.0, min(2.0, volume))

        if enabled:
            self._mic_device = self._find_microphone_device()
            if self._mic_device:
                logger.info(f"Microphone set to: {self._mic_device.name} (volume: {self.microphone_volume})")
                return True
            else:
                logger.error("Failed to find microphone device")
                return False
        else:
            self._mic_device = None
            logger.info("Microphone recording disabled")
            return True

    def set_device(self, device_index: int) -> bool:
        """
        Set the audio input device.

        Args:
            device_index: Device index from get_available_devices()

        Returns:
            True if device was set successfully
        """
        if self._state in (RecordingState.RECORDING, RecordingState.PAUSED):
            logger.warning("Cannot change device while recording")
            return False

        if not self._pyaudio:
            return False

        try:
            device = self._pyaudio.get_device_info_by_index(device_index)
            is_loopback = device.get("isLoopbackDevice", False)
            self._device_sample_rate = int(device["defaultSampleRate"])
            self._device_channels = max(device["maxInputChannels"], device["maxOutputChannels"])
            if self._device_channels == 0:
                self._device_channels = 2

            self._loopback_device = AudioDevice(
                index=device_index,
                name=device["name"],
                channels=self._device_channels,
                sample_rate=device["defaultSampleRate"],
                is_loopback=is_loopback,
            )
            logger.info(f"Audio device set to: {device['name']} (loopback: {is_loopback})")
            return True
        except Exception as e:
            logger.error(f"Error setting device: {e}")
            return False

    def set_default_device(self) -> bool:
        """Reset audio input device to the default loopback device."""
        if self._state in (RecordingState.RECORDING, RecordingState.PAUSED):
            logger.warning("Cannot change device while recording")
            return False

        self._loopback_device = self._find_loopback_device()
        if self._loopback_device is None:
            logger.error("Failed to find default audio device")
            return False

        logger.info(f"Audio device reset to default: {self._loopback_device.name}")
        return True

    def _recording_loop(self) -> None:
        """Recording thread main loop for system audio (loopback)."""
        if not self._pyaudio or not self._loopback_device:
            return

        try:
            # Open stream with WASAPI loopback
            # Note: For loopback devices in PyAudioWPatch, we don't need
            # as_loopback flag - just use the loopback device index directly
            stream = self._pyaudio.open(
                format=pyaudio.paInt16,
                channels=self._device_channels,
                rate=self._device_sample_rate,
                input=True,
                input_device_index=self._loopback_device.index,
                frames_per_buffer=1024,
            )

            logger.info(f"Recording stream opened (loopback: {self._loopback_device.is_loopback})")

            while not self._stop_event.is_set() and self._state in (RecordingState.RECORDING, RecordingState.PAUSED):
                try:
                    data = stream.read(1024, exception_on_overflow=False)

                    # Only save audio when not paused
                    if not self._pause_event.is_set():
                        with self._lock:
                            self._audio_buffer.append(data)

                        # Calculate audio level (combine both sources if mic enabled)
                        if self.on_level_change:
                            audio_array = np.frombuffer(data, dtype=np.int16)
                            rms = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
                            level = min(1.0, rms / 10000)
                            self.on_level_change(level)
                    else:
                        # Show zero level when paused
                        if self.on_level_change:
                            self.on_level_change(0.0)

                except Exception as e:
                    if not self._stop_event.is_set():
                        logger.warning(f"Error reading system audio: {e}")

            stream.stop_stream()
            stream.close()

        except Exception as e:
            logger.error(f"Recording loop error: {e}")
            self.state = RecordingState.IDLE

    def _microphone_loop(self) -> None:
        """Recording thread for microphone input."""
        if not self._pyaudio or not self._mic_device:
            return

        try:
            stream = self._pyaudio.open(
                format=pyaudio.paInt16,
                channels=self._mic_channels,
                rate=self._mic_sample_rate,
                input=True,
                input_device_index=self._mic_device.index,
                frames_per_buffer=1024,
            )

            logger.info(f"Microphone stream opened: {self._mic_device.name}")

            while not self._stop_event.is_set() and self._state in (RecordingState.RECORDING, RecordingState.PAUSED):
                try:
                    data = stream.read(1024, exception_on_overflow=False)

                    # Only save audio when not paused
                    if not self._pause_event.is_set():
                        with self._mic_lock:
                            self._mic_buffer.append(data)

                except Exception as e:
                    if not self._stop_event.is_set():
                        logger.warning(f"Error reading microphone: {e}")

            stream.stop_stream()
            stream.close()

        except Exception as e:
            logger.error(f"Microphone loop error: {e}")

    def test_levels(self, duration_seconds: float = 3.0) -> dict[str, Optional[float]]:
        """Probe selected audio devices and return max normalized levels."""
        if not PYAUDIO_AVAILABLE:
            raise RuntimeError("PyAudioWPatch is not available")
        if not self._pyaudio or not self._loopback_device:
            raise RuntimeError("System audio device is not available")

        system_stream = None
        mic_stream = None
        system_level = 0.0
        mic_level: Optional[float] = None

        try:
            system_stream = self._pyaudio.open(
                format=pyaudio.paInt16,
                channels=self._device_channels,
                rate=self._device_sample_rate,
                input=True,
                input_device_index=self._loopback_device.index,
                frames_per_buffer=1024,
            )

            if self.microphone_enabled and self._mic_device:
                mic_level = 0.0
                mic_stream = self._pyaudio.open(
                    format=pyaudio.paInt16,
                    channels=self._mic_channels,
                    rate=self._mic_sample_rate,
                    input=True,
                    input_device_index=self._mic_device.index,
                    frames_per_buffer=1024,
                )

            deadline = time.time() + max(0.5, duration_seconds)
            while time.time() < deadline:
                system_data = system_stream.read(1024, exception_on_overflow=False)
                system_level = max(system_level, self._data_level(system_data))

                if mic_stream is not None:
                    mic_data = mic_stream.read(1024, exception_on_overflow=False)
                    mic_level = max(mic_level or 0.0, self._data_level(mic_data))

            return {
                "system": system_level,
                "microphone": mic_level,
            }
        finally:
            for stream in (system_stream, mic_stream):
                if stream is None:
                    continue
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception as e:
                    logger.warning(f"Failed to close audio test stream: {e}")

    @staticmethod
    def _data_level(data: bytes) -> float:
        """Calculate a normalized 0..1 level from int16 PCM bytes."""
        audio_array = np.frombuffer(data, dtype=np.int16)
        if audio_array.size == 0:
            return 0.0
        rms = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
        return min(1.0, float(rms) / 10000)

    def start_recording(self, title: Optional[str] = None) -> Optional[Path]:
        """
        Start recording audio.

        Args:
            title: Optional title for the recording (used in filename)

        Returns:
            Path to the recording file, or None if failed
        """
        if self._state == RecordingState.RECORDING:
            logger.warning("Already recording")
            return self._current_file

        if not PYAUDIO_AVAILABLE:
            logger.error("PyAudioWPatch not available. Install with: pip install PyAudioWPatch")
            return None

        if self._loopback_device is None:
            logger.error("No audio device available")
            return None

        try:
            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = ""
            if title:
                # Sanitize title for filename
                safe_title = "_" + "".join(
                    c if c.isalnum() or c in "- " else "_" for c in title
                )[:50]
            filename = f"recording_{timestamp}{safe_title}.wav"
            self._current_file = self.output_dir / filename

            # Clear buffers
            with self._lock:
                self._audio_buffer = []
            with self._mic_lock:
                self._mic_buffer = []

            # Start recording threads
            self._stop_event.clear()
            self._pause_event.clear()
            self._paused_duration = 0.0
            self._pause_start_time = None
            self._recording_start_time = time.time()
            self.state = RecordingState.RECORDING

            # Start system audio (loopback) recording thread
            self._recording_thread = threading.Thread(target=self._recording_loop, daemon=True)
            self._recording_thread.start()

            # Start microphone recording thread if enabled
            if self.microphone_enabled and self._mic_device:
                self._mic_thread = threading.Thread(target=self._microphone_loop, daemon=True)
                self._mic_thread.start()
                logger.info(f"Microphone recording enabled: {self._mic_device.name}")

            logger.info(
                f"Recording started: {self._current_file} "
                f"(device: {self._loopback_device.name}, "
                f"sr: {self._device_sample_rate}, channels: {self._device_channels}, "
                f"loopback: {self._loopback_device.is_loopback}, "
                f"mic: {self.microphone_enabled})"
            )

            return self._current_file

        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            self.state = RecordingState.IDLE
            return None

    def stop_recording(self) -> Optional[Path]:
        """
        Stop recording and save audio file.

        Returns:
            Path to the saved recording file, or None if failed
        """
        if self._state not in (RecordingState.RECORDING, RecordingState.PAUSED):
            logger.warning("Not recording")
            return None

        self.state = RecordingState.STOPPING
        self._stop_event.set()

        try:
            # Wait for recording threads to finish
            if self._recording_thread:
                self._recording_thread.join(timeout=2.0)
                self._recording_thread = None

            if self._mic_thread:
                self._mic_thread.join(timeout=2.0)
                self._mic_thread = None

            # Process system audio
            with self._lock:
                if not self._audio_buffer:
                    logger.warning("No audio data recorded")
                    self.state = RecordingState.IDLE
                    return None

                # Concatenate all audio chunks
                audio_bytes = b"".join(self._audio_buffer)
                system_audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)

                # Convert to mono if needed
                if self._device_channels > 1:
                    system_audio = system_audio.reshape(-1, self._device_channels)
                    system_audio = np.mean(system_audio, axis=1)

                # Resample if needed (to target sample rate)
                if self._device_sample_rate != self.sample_rate:
                    from scipy import signal
                    num_samples = int(len(system_audio) * self.sample_rate / self._device_sample_rate)
                    system_audio = signal.resample(system_audio, num_samples)

            # Process microphone audio if enabled
            mic_audio = None
            if self.microphone_enabled:
                with self._mic_lock:
                    if self._mic_buffer:
                        mic_bytes = b"".join(self._mic_buffer)
                        mic_audio = np.frombuffer(mic_bytes, dtype=np.int16).astype(np.float32)

                        # Convert to mono if needed
                        if self._mic_channels > 1:
                            mic_audio = mic_audio.reshape(-1, self._mic_channels)
                            mic_audio = np.mean(mic_audio, axis=1)

                        # Resample if needed
                        if self._mic_sample_rate != self.sample_rate:
                            from scipy import signal
                            num_samples = int(len(mic_audio) * self.sample_rate / self._mic_sample_rate)
                            mic_audio = signal.resample(mic_audio, num_samples)

                        # Apply volume multiplier
                        mic_audio = mic_audio * self.microphone_volume

            # Mix audio streams
            if mic_audio is not None and len(mic_audio) > 0:
                # Make both arrays same length
                min_len = min(len(system_audio), len(mic_audio))
                if min_len > 0:
                    system_audio = system_audio[:min_len]
                    mic_audio = mic_audio[:min_len]
                    # Mix: add both streams
                    mixed_audio = system_audio + mic_audio
                    logger.info(f"Mixed system audio ({len(system_audio)} samples) with microphone ({len(mic_audio)} samples)")
                else:
                    mixed_audio = system_audio
            else:
                mixed_audio = system_audio

            # Normalize and convert to int16
            max_val = np.max(np.abs(mixed_audio))
            if max_val > 0:
                mixed_audio = mixed_audio / max_val
            audio_int16 = (mixed_audio * 32767).astype(np.int16)

            # Save as WAV
            wavfile.write(str(self._current_file), self.sample_rate, audio_int16)

            duration = len(audio_int16) / self.sample_rate
            logger.info(
                f"Recording saved: {self._current_file} "
                f"(duration: {duration:.1f}s, mic_mixed: {mic_audio is not None})"
            )

            self.state = RecordingState.IDLE
            self._recording_start_time = None

            return self._current_file

        except Exception as e:
            logger.error(f"Failed to save recording: {e}")
            self.state = RecordingState.IDLE
            return None

    def pause_recording(self) -> bool:
        """Pause recording - stops saving audio but keeps stream open."""
        if self._state != RecordingState.RECORDING:
            logger.warning("Cannot pause: not recording")
            return False

        self._pause_event.set()
        self._pause_start_time = time.time()
        self.state = RecordingState.PAUSED
        logger.info("Recording paused")
        return True

    def resume_recording(self) -> bool:
        """Resume recording from paused state."""
        if self._state != RecordingState.PAUSED:
            logger.warning("Cannot resume: not paused")
            return False

        # Track total paused duration
        if hasattr(self, '_pause_start_time') and self._pause_start_time:
            self._paused_duration += time.time() - self._pause_start_time
            self._pause_start_time = None

        self._pause_event.clear()
        self.state = RecordingState.RECORDING
        logger.info("Recording resumed")
        return True

    def get_audio_level(self) -> float:
        """Get current audio input level (0.0-1.0)."""
        if self._state != RecordingState.RECORDING:
            return 0.0
        return 0.0

    def cleanup(self) -> None:
        """Clean up resources."""
        self._stop_event.set()
        if self._recording_thread:
            self._recording_thread.join(timeout=2.0)
            self._recording_thread = None
        if self._mic_thread:
            self._mic_thread.join(timeout=2.0)
            self._mic_thread = None
        if self._pyaudio:
            try:
                self._pyaudio.terminate()
            except Exception:
                pass
            self._pyaudio = None
        self.state = RecordingState.IDLE
