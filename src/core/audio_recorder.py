"""Meeting audio capture: every Windows output (WASAPI loopback) plus the microphone.

Why every output: the other side of a call can play through speakers, wired
headphones or a headset, and Windows switches endpoints when a jack is plugged
in. Capturing every active loopback and mixing them means the recording always
contains the call, whichever output the meeting app uses.

Why re-scanning: PortAudio enumerates devices only when the *last* PyAudio
instance is terminated and a new one is created. The recorder therefore holds a
PyAudio instance only while recording or probing, re-creates it on every start,
and watches the Windows endpoint registry (~3 ms per check) to re-scan when
headphones are plugged in or unplugged mid-meeting.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Union

import numpy as np
from loguru import logger
from scipy import signal
from scipy.io import wavfile

try:
    import pyaudiowpatch as pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    pyaudio = None
    PYAUDIO_AVAILABLE = False
    logger.warning("PyAudioWPatch not installed. Install with: pip install PyAudioWPatch")


LOOPBACK_SUFFIX = "[Loopback]"
READ_FRAMES = 1024

POLL_SLEEP_SECONDS = 0.01
LEVEL_INTERVAL_SECONDS = 0.05
SOURCE_INTERVAL_SECONDS = 1.0
MONITOR_INTERVAL_SECONDS = 0.5
STREAM_ERROR_RESTART_SECONDS = 1.0
RETRY_RESTART_SECONDS = 2.0
STARTUP_TIMEOUT_SECONDS = 15.0
# A loopback that stops delivering frames during silence is padded with zeros
# once it lags the wall clock by more than this, so sources stay aligned.
# Kept well above poll jitter; device clock drift reaches it only after an hour+.
GAP_FILL_SECONDS = 0.25
# Minimum level (rms / 10000) to call an output "the one with meeting sound".
SOURCE_ACTIVE_LEVEL = 0.002


class RecordingState(Enum):
    """Recording state enum."""

    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"
    STOPPING = "stopping"


def clean_device_name(name: str) -> str:
    """Return a user-facing device name without the PyAudioWPatch loopback suffix."""
    cleaned = name.strip()
    if cleaned.endswith(LOOPBACK_SUFFIX):
        cleaned = cleaned[: -len(LOOPBACK_SUFFIX)].strip()
    return cleaned


@dataclass
class AudioDevice:
    """Audio device information."""

    index: int
    name: str
    channels: int
    sample_rate: float
    is_loopback: bool = False

    @property
    def display_name(self) -> str:
        return clean_device_name(self.name)


@dataclass(frozen=True)
class CaptureStatus:
    """What the recorder is listening to right now (sent to the UI)."""

    system_sources: tuple[str, ...] = ()
    active_system_source: Optional[str] = None
    microphone: Optional[str] = None


def endpoint_signature() -> Optional[frozenset]:
    """Return the set of active Windows audio endpoints, or None off Windows.

    Windows keeps endpoint state in the registry (DeviceState & 0xF == 1 means
    active). Reading it is cheap, so it is polled during recording to notice
    headphones being plugged in or unplugged.
    """
    try:
        import winreg
    except ImportError:
        return None

    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
    active: set[tuple[str, str]] = set()
    for flow in ("Render", "Capture"):
        try:
            root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{base}\\{flow}")
        except OSError:
            continue
        with root:
            index = 0
            while True:
                try:
                    guid = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(root, guid) as endpoint:
                        state, _ = winreg.QueryValueEx(endpoint, "DeviceState")
                except OSError:
                    continue
                if int(state) & 0xF == 1:
                    active.add((flow, guid))
    return frozenset(active)


class StreamingResampler:
    """Polyphase resampler for a live stream.

    Processes fixed blocks with filter context on both sides, so the output
    matches one-shot ``scipy.signal.resample_poly`` on the whole signal while
    only keeping a fraction of a second in memory.
    """

    def __init__(self, src_rate: int, dst_rate: int, block_seconds: float = 0.5):
        src_rate = int(src_rate)
        dst_rate = int(dst_rate)
        gcd = math.gcd(src_rate, dst_rate)
        self.up = dst_rate // gcd
        self.down = src_rate // gcd
        self.passthrough = self.up == self.down
        # resample_poly's default filter spans 10 * max(up, down) taps per side
        # at the upsampled rate; convert to input samples and round up to a
        # multiple of `down` so block boundaries map to whole output samples.
        half_len_in = math.ceil(10 * max(self.up, self.down) / self.up) + 1
        self._pad = self.down * math.ceil(max(half_len_in, 64) / self.down)
        self._block = self.down * max(1, round(src_rate * block_seconds / self.down))
        self._trim = self._pad * self.up // self.down
        self._block_out = self._block * self.up // self.down
        self._buffer = np.zeros(self._pad, dtype=np.float32)

    def process(self, samples: np.ndarray) -> np.ndarray:
        samples = np.asarray(samples, dtype=np.float32)
        if self.passthrough:
            return samples
        if samples.size:
            self._buffer = np.concatenate((self._buffer, samples))

        outputs = []
        window = self._block + 2 * self._pad
        while self._buffer.size >= window:
            resampled = signal.resample_poly(self._buffer[:window], self.up, self.down)
            outputs.append(resampled[self._trim : self._trim + self._block_out])
            self._buffer = self._buffer[self._block :]
        if not outputs:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(outputs).astype(np.float32, copy=False)

    def flush(self) -> np.ndarray:
        if self.passthrough:
            return np.zeros(0, dtype=np.float32)
        pending = self._buffer.size - self._pad
        if pending <= 0:
            return np.zeros(0, dtype=np.float32)
        tail = np.concatenate((self._buffer, np.zeros(self._pad, dtype=np.float32)))
        resampled = signal.resample_poly(tail, self.up, self.down)
        out_len = -(-pending * self.up // self.down)
        self._buffer = np.zeros(self._pad, dtype=np.float32)
        return resampled[self._trim : self._trim + out_len].astype(np.float32, copy=False)


class _Track:
    """Mono int16 audio on the recording timeline; silence kept as run lengths."""

    SILENCE_PEAK = 1

    def __init__(self) -> None:
        self.parts: list[Union[np.ndarray, int]] = []
        self.length = 0
        self.has_sound = False

    def append(self, samples: np.ndarray) -> None:
        if samples.size == 0:
            return
        pcm = np.clip(np.rint(samples), -32768, 32767).astype(np.int16)
        if int(np.max(np.abs(pcm.astype(np.int32)))) <= self.SILENCE_PEAK:
            self.append_silence(pcm.size)
            return
        self.parts.append(pcm)
        self.length += pcm.size
        self.has_sound = True

    def append_silence(self, count: int) -> None:
        if count <= 0:
            return
        if self.parts and isinstance(self.parts[-1], int):
            self.parts[-1] += count
        else:
            self.parts.append(count)
        self.length += count

    def mix_into(self, out: np.ndarray, gain: float = 1.0) -> None:
        position = 0
        for part in self.parts:
            if isinstance(part, int):
                position += part
                continue
            end = min(position + part.size, out.size)
            if end > position:
                out[position:end] += part[: end - position].astype(np.float32) * gain
            position += part.size


class _Capture:
    """One open input stream feeding a track."""

    def __init__(
        self,
        key: str,
        kind: str,
        device: AudioDevice,
        stream,
        start_active: float,
        target_rate: int,
    ):
        self.key = key
        self.kind = kind
        self.device = device
        self.stream = stream
        self.channels = max(1, int(device.channels))
        self.rate = int(device.sample_rate)
        self.resampler = StreamingResampler(self.rate, target_rate)
        self.start_active = start_active
        self.received = 0
        self.skip_out = 0
        self.level = 0.0
        self.peak = 0.0
        # Set after a read error; the stream is skipped until the next re-scan.
        self.failed = False


def _to_mono(data: bytes, channels: int) -> np.ndarray:
    samples = np.frombuffer(data, dtype=np.int16)
    if channels <= 1:
        return samples.astype(np.float32)
    frames = samples.size // channels
    if frames == 0:
        return np.zeros(0, dtype=np.float32)
    return samples[: frames * channels].reshape(frames, channels).mean(axis=1, dtype=np.float32)


def _mono_level(mono: np.ndarray) -> float:
    if mono.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float32))))
    return min(1.0, rms / 10000)


class AudioRecorder:
    """
    Records the meeting: all Windows outputs (WASAPI loopback) plus a microphone.

    By default every active output is captured and mixed, so the recording works
    with speakers, wired headphones or a headset without any setup. A specific
    output or microphone can still be pinned by name in settings.
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
        microphone_device_name: Optional[str] = None,
        on_source_change: Optional[Callable[[CaptureStatus], None]] = None,
    ):
        """
        Initialize audio recorder.

        Args:
            output_dir: Directory for saving recordings
            sample_rate: Output sample rate (16000 recommended for transcription)
            channels: Kept for compatibility; recordings are always mono
            on_level_change: Callback for audio level updates (0.0-1.0)
            on_state_change: Callback for recording state changes
            microphone_enabled: Also record the microphone
            microphone_device_index: Pinned microphone index (legacy; name wins)
            microphone_volume: Microphone volume multiplier for mixing (0.0-2.0)
            microphone_device_name: Pinned microphone name (None = Windows default)
            on_source_change: Callback with CaptureStatus when sources change
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.sample_rate = sample_rate
        self.channels = channels
        self.on_level_change = on_level_change
        self.on_state_change = on_state_change
        self.on_source_change = on_source_change

        # None/None = capture every output automatically.
        self.system_device_index: Optional[int] = None
        self.system_device_name: Optional[str] = None

        self.microphone_enabled = microphone_enabled
        self.microphone_device_index = microphone_device_index
        self.microphone_device_name = microphone_device_name
        self.microphone_volume = max(0.0, min(2.0, microphone_volume))

        self._state = RecordingState.IDLE
        self._current_file: Optional[Path] = None
        self._recording_start_time: Optional[float] = None

        self._pa = None
        self._captures: list[_Capture] = []
        self._tracks: dict[str, _Track] = {}
        self._track_kinds: dict[str, str] = {}
        self._tracks_lock = threading.Lock()

        self._capture_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._startup_event = threading.Event()
        self._startup_ok = False

        self._active_origin: Optional[float] = None
        self._paused_total = 0.0
        self._pause_started: Optional[float] = None

        self._endpoint_sig: Optional[frozenset] = None
        self._active_system: Optional[str] = None
        self._last_status: Optional[CaptureStatus] = None

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

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

    @property
    def capture_status(self) -> Optional[CaptureStatus]:
        """Last reported capture status (None when not recording)."""
        return self._last_status

    def _active_seconds(self) -> float:
        """Recording time so far, excluding pauses (the timeline position)."""
        if self._active_origin is None:
            return 0.0
        now = time.monotonic()
        paused = self._paused_total
        if self._pause_started is not None:
            paused += now - self._pause_started
        return max(0.0, now - self._active_origin - paused)

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _create_pyaudio():
        return pyaudio.PyAudio()

    @staticmethod
    def _terminate_pyaudio(pa) -> None:
        if pa is None:
            return
        try:
            pa.terminate()
        except Exception as e:
            logger.debug(f"PyAudio terminate failed: {e}")

    @staticmethod
    def _enumerate(pa) -> list[dict]:
        devices = []
        for i in range(pa.get_device_count()):
            try:
                info = dict(pa.get_device_info_by_index(i))
            except Exception:
                continue
            info.setdefault("index", i)
            devices.append(info)
        return devices

    @staticmethod
    def _wasapi_index(pa) -> Optional[int]:
        try:
            return int(pa.get_host_api_info_by_type(pyaudio.paWASAPI)["index"])
        except Exception:
            return None

    @staticmethod
    def _to_device(info: dict) -> AudioDevice:
        is_loopback = bool(info.get("isLoopbackDevice", False))
        channels = int(info.get("maxInputChannels") or 0)
        if channels <= 0:
            channels = int(info.get("maxOutputChannels") or 0) or 2
        return AudioDevice(
            index=int(info["index"]),
            name=str(info["name"]),
            channels=channels,
            sample_rate=float(info.get("defaultSampleRate") or 48000),
            is_loopback=is_loopback,
        )

    def _split_devices(self, pa) -> tuple[list[dict], list[dict], list[dict]]:
        """Return (loopbacks, WASAPI microphones, all microphones)."""
        devices = self._enumerate(pa)
        wasapi = self._wasapi_index(pa)
        loopbacks = [d for d in devices if d.get("isLoopbackDevice")]
        microphones = [
            d for d in devices
            if not d.get("isLoopbackDevice") and int(d.get("maxInputChannels") or 0) > 0
        ]
        wasapi_microphones = [d for d in microphones if wasapi is not None and d.get("hostApi") == wasapi]
        return loopbacks, wasapi_microphones, microphones

    def _resolve_system_devices(self, pa) -> list[AudioDevice]:
        """Pick outputs to capture: the pinned one if present, otherwise all."""
        loopbacks, _, microphones = self._split_devices(pa)
        name = self.system_device_name
        index = self.system_device_index

        if name or index is not None:
            match = None
            if name:
                match = next((d for d in loopbacks if d["name"] == name), None)
                if match is None:
                    match = next((d for d in microphones if d["name"] == name), None)
            elif index is not None:
                # Legacy setting without a name: indices shift when devices
                # are plugged in, so only trust it if it is still capturable.
                match = next(
                    (
                        d for d in loopbacks + microphones
                        if int(d["index"]) == index
                    ),
                    None,
                )
            if match is not None:
                return [self._to_device(match)]
            logger.warning(
                f"Selected output not found (name={name!r}, index={index}); capturing all outputs"
            )

        return [self._to_device(d) for d in loopbacks]

    def _resolve_microphone(self, pa) -> Optional[AudioDevice]:
        """Pick the microphone: pinned by name if present, else Windows default."""
        if not self.microphone_enabled:
            return None

        _, wasapi_microphones, microphones = self._split_devices(pa)
        name = self.microphone_device_name
        if not name and self.microphone_device_index is not None:
            legacy = next(
                (d for d in microphones if int(d["index"]) == self.microphone_device_index),
                None,
            )
            if legacy is not None:
                name = str(legacy["name"])

        if name:
            # MME names are cut to 31 characters, so also accept a prefix match.
            match = next((d for d in wasapi_microphones if d["name"] == name), None)
            if match is None:
                match = next((d for d in wasapi_microphones if str(d["name"]).startswith(name)), None)
            if match is None:
                match = next((d for d in microphones if d["name"] == name), None)
            if match is not None:
                return self._to_device(match)
            logger.warning(f"Selected microphone not found ({name!r}); using Windows default")

        for getter in (
            lambda: pa.get_default_wasapi_device(d_in=True),
            pa.get_default_input_device_info,
        ):
            try:
                info = dict(getter())
                if int(info.get("maxInputChannels") or 0) > 0:
                    return self._to_device(info)
            except Exception:
                continue
        return None

    def get_capture_devices(self) -> tuple[list[AudioDevice], list[AudioDevice]]:
        """Return (outputs, microphones) for settings, freshly enumerated."""
        if not PYAUDIO_AVAILABLE:
            return [], []
        pa = None
        try:
            pa = self._create_pyaudio()
            loopbacks, wasapi_microphones, microphones = self._split_devices(pa)
            mics = wasapi_microphones or microphones
            return (
                [self._to_device(d) for d in loopbacks],
                [self._to_device(d) for d in mics],
            )
        except Exception as e:
            logger.error(f"Error listing audio devices: {e}")
            return [], []
        finally:
            self._terminate_pyaudio(pa)

    def get_available_devices(self) -> list[AudioDevice]:
        """Return outputs that can be recorded (WASAPI loopback devices)."""
        return self.get_capture_devices()[0]

    def get_microphone_devices(self) -> list[AudioDevice]:
        """Return microphones (WASAPI inputs, falling back to all inputs)."""
        return self.get_capture_devices()[1]

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def set_microphone(
        self,
        device_index: Optional[int],
        enabled: bool = True,
        volume: float = 1.0,
        device_name: Optional[str] = None,
    ) -> bool:
        """Set microphone settings (applied at the next recording start)."""
        if self._state in (RecordingState.RECORDING, RecordingState.PAUSED):
            logger.warning("Cannot change microphone while recording")
            return False

        self.microphone_enabled = enabled
        self.microphone_device_index = device_index
        self.microphone_device_name = device_name
        self.microphone_volume = max(0.0, min(2.0, volume))
        logger.info(
            f"Microphone settings: enabled={enabled}, device={device_name or device_index or 'default'}, "
            f"volume={self.microphone_volume}"
        )
        return True

    def set_device(self, device_index: Optional[int], device_name: Optional[str] = None) -> bool:
        """Pin one output to record (None/None = all outputs)."""
        if self._state in (RecordingState.RECORDING, RecordingState.PAUSED):
            logger.warning("Cannot change device while recording")
            return False

        self.system_device_index = device_index
        self.system_device_name = device_name
        logger.info(f"Audio output set to: {device_name or device_index or 'all outputs'}")
        return True

    def set_default_device(self) -> bool:
        """Record every output automatically."""
        return self.set_device(None, None)

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def _open_capture(self, pa, kind: str, key: str, device: AudioDevice, start_active: float) -> Optional[_Capture]:
        try:
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=max(1, int(device.channels)),
                rate=int(device.sample_rate),
                input=True,
                input_device_index=device.index,
                frames_per_buffer=READ_FRAMES,
            )
        except Exception as e:
            logger.warning(f"Cannot open {kind} device {device.name!r} (index {device.index}): {e}")
            return None

        capture = _Capture(key, kind, device, stream, start_active, self.sample_rate)
        with self._tracks_lock:
            track = self._tracks.setdefault(key, _Track())
            self._track_kinds[key] = kind
            target = int(round(start_active * self.sample_rate))
            if track.length < target:
                track.append_silence(target - track.length)
            else:
                capture.skip_out = track.length - target
        return capture

    def _open_captures(self, pa) -> list[_Capture]:
        start_active = self._active_seconds()
        captures: list[_Capture] = []
        for device in self._resolve_system_devices(pa):
            capture = self._open_capture(pa, "system", f"system:{device.name}", device, start_active)
            if capture:
                captures.append(capture)
        microphone = self._resolve_microphone(pa)
        if microphone is not None:
            capture = self._open_capture(pa, "mic", "mic", microphone, start_active)
            if capture:
                captures.append(capture)

        systems = [c.device.display_name for c in captures if c.kind == "system"]
        mic = next((c.device.display_name for c in captures if c.kind == "mic"), None)
        logger.info(f"Capturing outputs: {systems or 'none'}; microphone: {mic or 'off'}")
        return captures

    def _write(self, capture: _Capture, samples: np.ndarray) -> None:
        if samples.size == 0:
            return
        if capture.skip_out:
            drop = min(capture.skip_out, samples.size)
            samples = samples[drop:]
            capture.skip_out -= drop
            if samples.size == 0:
                return
        with self._tracks_lock:
            track = self._tracks.get(capture.key)
            if track is not None:
                track.append(samples)

    def _accept(self, capture: _Capture, data: bytes) -> None:
        mono = _to_mono(data, capture.channels)
        if mono.size == 0:
            return
        level = _mono_level(mono)
        if self._pause_event.is_set():
            return

        capture.level = max(capture.level, level)
        capture.peak = max(capture.peak, level)

        expected = (self._active_seconds() - capture.start_active) * capture.rate
        gap = int(expected) - capture.received - mono.size
        if gap > capture.rate * GAP_FILL_SECONDS:
            self._write(capture, capture.resampler.process(np.zeros(gap, dtype=np.float32)))
            capture.received += gap

        self._write(capture, capture.resampler.process(mono))
        capture.received += mono.size

    def _close_captures(self) -> None:
        for capture in self._captures:
            try:
                capture.stream.stop_stream()
                capture.stream.close()
            except Exception as e:
                logger.debug(f"Failed to close stream {capture.device.name!r}: {e}")
            try:
                self._write(capture, capture.resampler.flush())
            except Exception as e:
                logger.warning(f"Failed to flush {capture.device.name!r}: {e}")
        self._captures = []

    def _reopen(self, reason: str) -> bool:
        logger.info(f"Re-scanning audio devices: {reason}")
        self._close_captures()
        self._terminate_pyaudio(self._pa)
        self._pa = None
        try:
            self._pa = self._create_pyaudio()
            self._captures = self._open_captures(self._pa)
        except Exception as e:
            logger.error(f"Failed to re-open audio devices: {e}")
            self._captures = []
        self._endpoint_sig = endpoint_signature()

        names = {c.device.display_name for c in self._captures if c.kind == "system"}
        if self._active_system not in names:
            self._active_system = None
        self._emit_status()
        return bool(self._captures)

    def _poll_captures(self) -> tuple[bool, bool]:
        """Read whatever each stream has. Returns (got_data, had_error)."""
        got_data = False
        had_error = False
        for capture in self._captures:
            if capture.failed:
                continue
            try:
                available = capture.stream.get_read_available()
                if available <= 0:
                    continue
                data = capture.stream.read(available, exception_on_overflow=False)
            except Exception as e:
                logger.warning(f"Audio read failed on {capture.device.name!r}: {e}")
                capture.failed = True
                had_error = True
                continue
            got_data = True
            self._accept(capture, data)
        return got_data, had_error

    def _emit_status(self) -> None:
        status = CaptureStatus(
            system_sources=tuple(c.device.display_name for c in self._captures if c.kind == "system"),
            active_system_source=self._active_system,
            microphone=next((c.device.display_name for c in self._captures if c.kind == "mic"), None),
        )
        if status == self._last_status:
            return
        self._last_status = status
        if self.on_source_change:
            try:
                self.on_source_change(status)
            except Exception as e:
                logger.warning(f"Source change callback failed: {e}")

    def _update_active_source(self) -> None:
        systems = [(c.peak, c.device.display_name) for c in self._captures if c.kind == "system"]
        for capture in self._captures:
            capture.peak = 0.0
        loudest = max(systems, key=lambda item: item[0], default=None)
        if loudest is None or loudest[0] < SOURCE_ACTIVE_LEVEL:
            return
        name = loudest[1]
        if name != self._active_system:
            logger.info(f"Meeting sound detected on: {name}")
            self._active_system = name
            self._emit_status()

    def _capture_main(self) -> None:
        """Capture thread: owns PyAudio for the whole recording."""
        try:
            self._pa = self._create_pyaudio()
            self._captures = self._open_captures(self._pa)
        except Exception as e:
            logger.error(f"Failed to open audio devices: {e}")
            self._captures = []

        self._startup_ok = bool(self._captures)
        self._startup_event.set()
        if not self._startup_ok:
            self._terminate_pyaudio(self._pa)
            self._pa = None
            return

        self._endpoint_sig = endpoint_signature()
        self._emit_status()
        try:
            self._capture_loop()
        except Exception as e:
            logger.exception(f"Capture loop crashed: {e}")
        finally:
            self._close_captures()
            self._terminate_pyaudio(self._pa)
            self._pa = None

    def _capture_loop(self) -> None:
        now = time.monotonic()
        next_level = now
        next_source = now + SOURCE_INTERVAL_SECONDS
        next_monitor = now + MONITOR_INTERVAL_SECONDS
        pending_sig: Optional[frozenset] = None
        restart_at: Optional[float] = None
        restart_reason = ""

        while not self._stop_event.is_set():
            got_data, had_error = self._poll_captures()
            now = time.monotonic()

            if had_error and restart_at is None:
                restart_at = now + STREAM_ERROR_RESTART_SECONDS
                restart_reason = "audio stream error"

            if now >= next_monitor:
                next_monitor = now + MONITOR_INTERVAL_SECONDS
                signature = endpoint_signature()
                if signature is not None and signature != self._endpoint_sig:
                    # Act once the change has been stable for one interval:
                    # Windows flips several endpoints when a jack is plugged.
                    if signature == pending_sig and restart_at is None:
                        restart_at = now
                        restart_reason = "audio devices changed"
                    pending_sig = signature
                else:
                    pending_sig = None

            if restart_at is not None and now >= restart_at:
                restart_at = None
                pending_sig = None
                if not self._reopen(restart_reason):
                    restart_at = time.monotonic() + RETRY_RESTART_SECONDS
                    restart_reason = "no audio devices yet"

            if now >= next_level:
                next_level = now + LEVEL_INTERVAL_SECONDS
                level = 0.0
                if not self._pause_event.is_set():
                    level = max((c.level for c in self._captures), default=0.0)
                for capture in self._captures:
                    capture.level = 0.0
                if self.on_level_change:
                    try:
                        self.on_level_change(level)
                    except Exception as e:
                        logger.debug(f"Level callback failed: {e}")

            if now >= next_source:
                next_source = now + SOURCE_INTERVAL_SECONDS
                self._update_active_source()

            if not got_data:
                self._stop_event.wait(POLL_SLEEP_SECONDS)

    def _mix_tracks(self) -> Optional[np.ndarray]:
        with self._tracks_lock:
            if not self._tracks:
                return None
            tracks = self._tracks
            kinds = self._track_kinds
            self._tracks = {}
            self._track_kinds = {}

        total = max(track.length for track in tracks.values())
        if total <= 0:
            return None
        mixed = np.zeros(total, dtype=np.float32)
        sources = {}
        for key in list(tracks):
            track = tracks.pop(key)  # free each track as soon as it is mixed
            gain = self.microphone_volume if kinds.get(key) == "mic" else 1.0
            track.mix_into(mixed, gain)
            sources[key] = track.has_sound
        logger.info(f"Mixed {len(sources)} sources (has sound): {sources}")
        return mixed

    # ------------------------------------------------------------------
    # Probe
    # ------------------------------------------------------------------

    def test_levels(self, duration_seconds: float = 3.0) -> dict[str, object]:
        """Listen to the devices a recording would use and report max levels.

        Returns {"system": float, "microphone": float | None,
        "system_source": loudest output name or None,
        "system_sources": [output names], "microphone_source": name or None}.
        """
        if not PYAUDIO_AVAILABLE:
            raise RuntimeError("PyAudioWPatch is not available")
        if self._state in (RecordingState.RECORDING, RecordingState.PAUSED):
            raise RuntimeError("Recorder is busy")

        pa = self._create_pyaudio()
        opened: list[tuple[str, AudioDevice, object]] = []
        try:
            for device in self._resolve_system_devices(pa):
                stream = self._open_probe(pa, device)
                if stream is not None:
                    opened.append(("system", device, stream))
            microphone = self._resolve_microphone(pa)
            if microphone is not None:
                stream = self._open_probe(pa, microphone)
                if stream is not None:
                    opened.append(("mic", microphone, stream))
            if not opened:
                raise RuntimeError("System audio device is not available")

            levels = [0.0] * len(opened)
            deadline = time.monotonic() + max(0.5, duration_seconds)
            while time.monotonic() < deadline:
                got_data = False
                for i, (_, device, stream) in enumerate(opened):
                    available = stream.get_read_available()
                    if available <= 0:
                        continue
                    data = stream.read(available, exception_on_overflow=False)
                    levels[i] = max(levels[i], _mono_level(_to_mono(data, device.channels)))
                    got_data = True
                if not got_data:
                    time.sleep(POLL_SLEEP_SECONDS)

            systems = [(levels[i], dev) for i, (kind, dev, _) in enumerate(opened) if kind == "system"]
            mic = [(levels[i], dev) for i, (kind, dev, _) in enumerate(opened) if kind == "mic"]
            system_level = max((lvl for lvl, _ in systems), default=0.0)
            loudest = max(systems, key=lambda item: item[0], default=None)
            return {
                "system": system_level,
                "microphone": mic[0][0] if mic else None,
                "system_source": (
                    loudest[1].display_name
                    if loudest is not None and loudest[0] >= SOURCE_ACTIVE_LEVEL
                    else None
                ),
                "system_sources": [dev.display_name for _, dev in systems],
                "microphone_source": mic[0][1].display_name if mic else None,
            }
        finally:
            for _, _, stream in opened:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception as e:
                    logger.warning(f"Failed to close audio test stream: {e}")
            self._terminate_pyaudio(pa)

    @staticmethod
    def _open_probe(pa, device: AudioDevice):
        try:
            return pa.open(
                format=pyaudio.paInt16,
                channels=max(1, int(device.channels)),
                rate=int(device.sample_rate),
                input=True,
                input_device_index=device.index,
                frames_per_buffer=READ_FRAMES,
            )
        except Exception as e:
            logger.warning(f"Cannot open {device.name!r} for audio test: {e}")
            return None

    @staticmethod
    def _data_level(data: bytes) -> float:
        """Calculate a normalized 0..1 level from int16 PCM bytes."""
        audio_array = np.frombuffer(data, dtype=np.int16)
        if audio_array.size == 0:
            return 0.0
        rms = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
        return min(1.0, float(rms) / 10000)

    # ------------------------------------------------------------------
    # Recording control
    # ------------------------------------------------------------------

    def start_recording(self, title: Optional[str] = None) -> Optional[Path]:
        """
        Start recording audio.

        Args:
            title: Optional title for the recording (used in filename)

        Returns:
            Path to the recording file, or None if failed
        """
        if self._state in (RecordingState.RECORDING, RecordingState.PAUSED):
            logger.warning("Already recording")
            return self._current_file

        if not PYAUDIO_AVAILABLE:
            logger.error("PyAudioWPatch not available. Install with: pip install PyAudioWPatch")
            return None

        if self._capture_thread is not None and self._capture_thread.is_alive():
            logger.error("Previous capture thread is still running")
            return None

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = ""
            if title:
                safe_title = "_" + "".join(
                    c if c.isalnum() or c in "- " else "_" for c in title
                )[:50]
            self._current_file = self.output_dir / f"recording_{timestamp}{safe_title}.wav"

            with self._tracks_lock:
                self._tracks = {}
                self._track_kinds = {}
            self._captures = []
            self._active_system = None
            self._last_status = None
            self._stop_event.clear()
            self._pause_event.clear()
            self._startup_event.clear()
            self._startup_ok = False
            self._paused_total = 0.0
            self._pause_started = None
            self._active_origin = time.monotonic()

            self._capture_thread = threading.Thread(
                target=self._capture_main, name="audio-capture", daemon=True
            )
            self._capture_thread.start()

            if not self._startup_event.wait(STARTUP_TIMEOUT_SECONDS) or not self._startup_ok:
                logger.error("No audio device could be opened for recording")
                self._stop_event.set()
                self._capture_thread.join(timeout=2.0)
                self._capture_thread = None
                self._active_origin = None
                return None

            self._recording_start_time = time.time()
            self.state = RecordingState.RECORDING
            logger.info(
                f"Recording started: {self._current_file} "
                f"(outputs: {self.system_device_name or self.system_device_index or 'all'}, "
                f"mic: {self.microphone_enabled})"
            )
            return self._current_file

        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            self._stop_event.set()
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
            if self._capture_thread:
                self._capture_thread.join(timeout=5.0)
                if self._capture_thread.is_alive():
                    logger.warning("Capture thread did not stop in time; saving what was captured")
                self._capture_thread = None

            mixed = self._mix_tracks()
            if mixed is None:
                logger.warning("No audio data recorded")
                self._finish_stop()
                return None

            peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
            if peak > 0:
                mixed *= 1.0 / peak
            audio_int16 = (mixed * 32767).astype(np.int16)
            del mixed

            wavfile.write(str(self._current_file), self.sample_rate, audio_int16)
            logger.info(
                f"Recording saved: {self._current_file} "
                f"(duration: {audio_int16.size / self.sample_rate:.1f}s)"
            )
            self._finish_stop()
            return self._current_file

        except Exception as e:
            logger.error(f"Failed to save recording: {e}")
            self._finish_stop()
            return None

    def _finish_stop(self) -> None:
        self._recording_start_time = None
        self._active_origin = None
        self._pause_started = None
        self._last_status = None
        self.state = RecordingState.IDLE

    def pause_recording(self) -> bool:
        """Pause recording - streams stay open but audio is not saved."""
        if self._state != RecordingState.RECORDING:
            logger.warning("Cannot pause: not recording")
            return False

        self._pause_started = time.monotonic()
        self._pause_event.set()
        self.state = RecordingState.PAUSED
        logger.info("Recording paused")
        return True

    def resume_recording(self) -> bool:
        """Resume recording from paused state."""
        if self._state != RecordingState.PAUSED:
            logger.warning("Cannot resume: not paused")
            return False

        if self._pause_started is not None:
            self._paused_total += time.monotonic() - self._pause_started
            self._pause_started = None
        self._pause_event.clear()
        self.state = RecordingState.RECORDING
        logger.info("Recording resumed")
        return True

    def get_audio_level(self) -> float:
        """Get current audio input level (0.0-1.0)."""
        return 0.0

    def cleanup(self) -> None:
        """Stop capture and release audio resources."""
        self._stop_event.set()
        if self._capture_thread:
            self._capture_thread.join(timeout=5.0)
            self._capture_thread = None
        self.state = RecordingState.IDLE
