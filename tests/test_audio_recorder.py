"""AudioRecorder tests with a fake PyAudioWPatch.

The fake mimics two PortAudio behaviours that matter here: the device list is
a snapshot taken when PyAudio() is created, and loopback streams deliver
frames in real time.
"""

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from scipy import signal
from scipy.io import wavfile

import src.core.audio_recorder as ar
from src.core.audio_recorder import (
    AudioRecorder,
    CaptureStatus,
    RecordingState,
    StreamingResampler,
    _Track,
)

RATE = 48000
WASAPI = 2
MME = 0


def tone(freq: float, amplitude: float = 8000.0, rate: int = RATE):
    return lambda start, n: amplitude * np.sin(2 * np.pi * freq * np.arange(start, start + n) / rate)


def loopback(index, name, sound=None, **extra):
    return {
        "index": index,
        "name": f"{name} [Loopback]",
        "maxInputChannels": 2,
        "maxOutputChannels": 0,
        "defaultSampleRate": float(RATE),
        "hostApi": WASAPI,
        "isLoopbackDevice": True,
        "sound": sound,
        **extra,
    }


def microphone(index, name, host=WASAPI, sound=None):
    return {
        "index": index,
        "name": name,
        "maxInputChannels": 2,
        "maxOutputChannels": 0,
        "defaultSampleRate": float(RATE),
        "hostApi": host,
        "isLoopbackDevice": False,
        "sound": sound,
    }


class FakeStream:
    def __init__(self, info, channels, rate):
        self.info = info
        self.channels = channels
        self.rate = rate
        self.started = time.monotonic()
        self.read_frames = 0

    def get_read_available(self):
        elapsed = time.monotonic() - self.started
        if elapsed < self.info.get("stall_until", 0.0):
            # A silent loopback delivers nothing and does not buffer the gap.
            self.read_frames = int(elapsed * self.rate)
            return 0
        return max(0, int(elapsed * self.rate) - self.read_frames)

    def read(self, frames, exception_on_overflow=True):
        sound = self.info.get("sound")
        mono = np.zeros(frames) if sound is None else sound(self.read_frames, frames)
        self.read_frames += frames
        samples = np.repeat(np.asarray(mono, dtype=np.float64)[:, None], self.channels, axis=1)
        return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()

    def stop_stream(self):
        pass

    def close(self):
        pass


class FakePyAudio:
    def __init__(self, system):
        self.system = system
        self.devices = [dict(d) for d in system.devices]  # snapshot, like PortAudio
        system.instances += 1

    def get_device_count(self):
        return len(self.devices)

    def get_device_info_by_index(self, i):
        return self.devices[i]

    def get_host_api_info_by_type(self, host_type):
        return {"index": WASAPI}

    def _by_name(self, name):
        for device in self.devices:
            if device["name"] == name:
                return device
        raise OSError("no default device")

    def get_default_wasapi_device(self, d_in=False, d_out=False):
        return self._by_name(self.system.default_mic)

    def get_default_input_device_info(self):
        return self._by_name(self.system.default_mic)

    def open(self, format, channels, rate, input, input_device_index, frames_per_buffer):
        info = next(d for d in self.devices if d["index"] == input_device_index)
        if info.get("open_error"):
            raise OSError("device busy")
        self.system.opened.append(info["name"])
        return FakeStream(info, channels, rate)

    def terminate(self):
        self.system.terminated += 1


class FakeAudioSystem:
    paInt16 = 8
    paWASAPI = 13

    def __init__(self, devices, default_mic=None):
        self.devices = devices
        self.default_mic = default_mic
        self.instances = 0
        self.terminated = 0
        self.opened = []

    def PyAudio(self):
        return FakePyAudio(self)


def rms(samples):
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


class BuildingBlocksTest(unittest.TestCase):
    def test_streaming_resampler_matches_one_shot(self):
        for src_rate in (48000, 44100):
            with self.subTest(src_rate=src_rate):
                rng = np.random.default_rng(1)
                x = (rng.standard_normal(src_rate * 2) * 3000).astype(np.float32)
                expected = signal.resample_poly(x, 16000, src_rate)

                resampler = StreamingResampler(src_rate, 16000)
                parts = []
                position = 0
                while position < x.size:
                    size = int(rng.integers(100, 5000))
                    parts.append(resampler.process(x[position : position + size]))
                    position += size
                parts.append(resampler.flush())
                actual = np.concatenate(parts)

                self.assertEqual(actual.size, expected.size)
                self.assertLess(float(np.max(np.abs(actual - expected))), 0.5)  # int16 scale

    def test_streaming_resampler_passthrough_at_target_rate(self):
        resampler = StreamingResampler(16000, 16000)
        x = np.arange(10, dtype=np.float32)
        self.assertTrue(np.array_equal(resampler.process(x), x))
        self.assertEqual(resampler.flush().size, 0)

    def test_track_keeps_silence_as_length_and_mixes_with_gain(self):
        track = _Track()
        track.append(np.zeros(1000, dtype=np.float32))
        track.append(np.full(10, 100.0, dtype=np.float32))
        track.append_silence(5)

        self.assertEqual(track.length, 1015)
        self.assertEqual(track.parts[0], 1000)  # silence stored as a run length
        out = np.zeros(1020, dtype=np.float32)
        track.mix_into(out, gain=0.5)
        self.assertTrue(np.all(out[:1000] == 0))
        self.assertTrue(np.allclose(out[1000:1010], 50.0))
        self.assertTrue(np.all(out[1010:] == 0))

    def test_capture_status_is_comparable(self):
        a = CaptureStatus(("Наушники",), "Наушники", None)
        b = CaptureStatus(("Наушники",), "Наушники", None)
        self.assertEqual(a, b)
        self.assertEqual(len({a, b}), 1)


class RecorderTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.signature = frozenset({("Render", "a")})
        self.system = None
        patches = [
            mock.patch.object(ar, "PYAUDIO_AVAILABLE", True),
            mock.patch.object(ar, "endpoint_signature", lambda: self.signature),
            mock.patch.object(ar, "SOURCE_INTERVAL_SECONDS", 0.2),
            mock.patch.object(ar, "MONITOR_INTERVAL_SECONDS", 0.05),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def install(self, devices, default_mic=None):
        self.system = FakeAudioSystem(devices, default_mic)
        patch = mock.patch.object(ar, "pyaudio", self.system)
        patch.start()
        self.addCleanup(patch.stop)
        return self.system

    def read_wav(self, path):
        self.assertIsNotNone(path)
        rate, data = wavfile.read(str(path))
        self.assertEqual(rate, 16000)
        return data


class RecordingTest(RecorderTestCase):
    def test_records_every_output_and_reports_where_the_call_is(self):
        system = self.install(
            [
                loopback(0, "Динамики (Senary Audio)"),
                loopback(1, "Наушники (Senary Audio)", sound=tone(440)),
                microphone(2, "Микрофон (Senary Audio)", sound=tone(1000, 3000)),
            ],
            default_mic="Микрофон (Senary Audio)",
        )
        statuses = []
        recorder = AudioRecorder(
            self.tmp_path, microphone_enabled=True, on_source_change=statuses.append
        )

        self.assertEqual(system.instances, 0)  # nothing is held while idle
        path = recorder.start_recording("Встреча")
        self.assertIsNotNone(path)
        self.assertEqual(recorder.state, RecordingState.RECORDING)
        time.sleep(1.0)
        saved = recorder.stop_recording()

        self.assertEqual(saved, path)
        self.assertEqual(
            sorted(system.opened),
            [
                "Динамики (Senary Audio) [Loopback]",
                "Микрофон (Senary Audio)",
                "Наушники (Senary Audio) [Loopback]",
            ],
        )
        self.assertEqual(system.terminated, system.instances)  # audio system released
        self.assertEqual(
            statuses[0].system_sources, ("Динамики (Senary Audio)", "Наушники (Senary Audio)")
        )
        self.assertEqual(statuses[0].microphone, "Микрофон (Senary Audio)")
        self.assertEqual(statuses[-1].active_system_source, "Наушники (Senary Audio)")

        data = self.read_wav(saved)
        self.assertTrue(0.8 < data.size / 16000 < 1.3, data.size / 16000)
        self.assertGreater(rms(data[1600:-1600]), 5000)

    def test_replugged_headphones_are_picked_up_mid_recording(self):
        system = self.install([loopback(0, "Динамики (Senary Audio)")])
        statuses = []
        recorder = AudioRecorder(
            self.tmp_path, microphone_enabled=False, on_source_change=statuses.append
        )

        started = time.monotonic()
        self.assertIsNotNone(recorder.start_recording())
        time.sleep(0.6)

        # Headphones plugged in: Windows adds an endpoint, indices shift.
        system.devices = [
            loopback(0, "Наушники (Senary Audio)", sound=tone(440)),
            loopback(1, "Динамики (Senary Audio)"),
        ]
        self.signature = frozenset({("Render", "a"), ("Render", "b")})
        time.sleep(0.9)
        saved = recorder.stop_recording()
        elapsed = time.monotonic() - started

        self.assertGreaterEqual(system.instances, 2)  # re-created to see the new device
        self.assertIn("Наушники (Senary Audio) [Loopback]", system.opened)
        self.assertEqual(
            statuses[-1].system_sources, ("Наушники (Senary Audio)", "Динамики (Senary Audio)")
        )
        self.assertEqual(statuses[-1].active_system_source, "Наушники (Senary Audio)")

        data = self.read_wav(saved)
        self.assertLess(abs(data.size / 16000 - elapsed), 0.35)  # timeline kept
        self.assertLess(rms(data[: int(0.5 * 16000)]), 50)  # before the plug: silence
        self.assertGreater(rms(data[-int(0.4 * 16000) :]), 5000)  # after: the call

    def test_output_that_wakes_up_late_stays_in_place(self):
        self.install([loopback(0, "Наушники", sound=tone(440), stall_until=0.6)])
        recorder = AudioRecorder(self.tmp_path, microphone_enabled=False)

        self.assertIsNotNone(recorder.start_recording())
        time.sleep(1.2)
        data = self.read_wav(recorder.stop_recording())

        self.assertGreater(data.size / 16000, 1.0)
        self.assertLess(rms(data[: int(0.45 * 16000)]), 50)
        self.assertGreater(rms(data[-int(0.4 * 16000) :]), 5000)

    def test_pause_is_left_out_of_the_file(self):
        self.install([loopback(0, "Наушники", sound=tone(440))])
        recorder = AudioRecorder(self.tmp_path, microphone_enabled=False)

        self.assertIsNotNone(recorder.start_recording())
        time.sleep(0.5)
        self.assertTrue(recorder.pause_recording())
        time.sleep(0.6)
        self.assertTrue(recorder.resume_recording())
        time.sleep(0.5)
        data = self.read_wav(recorder.stop_recording())

        self.assertTrue(0.8 < data.size / 16000 < 1.3, data.size / 16000)

    def test_start_fails_cleanly_when_nothing_can_be_opened(self):
        system = self.install([loopback(0, "Наушники", open_error=True)])
        recorder = AudioRecorder(self.tmp_path, microphone_enabled=False)

        self.assertIsNone(recorder.start_recording())
        self.assertEqual(recorder.state, RecordingState.IDLE)
        self.assertEqual(system.terminated, system.instances)

    def test_settings_cannot_change_while_recording(self):
        self.install([loopback(0, "Наушники")])
        recorder = AudioRecorder(self.tmp_path, microphone_enabled=False)
        self.assertIsNotNone(recorder.start_recording())
        try:
            self.assertFalse(recorder.set_device(1, "Другое"))
            self.assertFalse(recorder.set_microphone(None, enabled=True))
            with self.assertRaises(RuntimeError):
                recorder.test_levels(0.1)
        finally:
            recorder.stop_recording()
        self.assertTrue(recorder.set_default_device())

    def test_no_capture_thread_left_after_stop(self):
        self.install([loopback(0, "Наушники")])
        recorder = AudioRecorder(self.tmp_path, microphone_enabled=False)
        recorder.start_recording()
        time.sleep(0.2)
        recorder.stop_recording()
        self.assertFalse(any(t.name == "audio-capture" for t in threading.enumerate()))


class DeviceChoiceTest(RecorderTestCase):
    def test_pinned_output_is_found_by_name_after_index_shift(self):
        self.install(
            [
                loopback(0, "Динамики (Senary Audio)"),
                loopback(1, "USB Headset"),
                loopback(2, "Наушники (Senary Audio)", sound=tone(440)),
            ]
        )
        recorder = AudioRecorder(self.tmp_path, microphone_enabled=False)
        recorder.set_device(0, "Наушники (Senary Audio) [Loopback]")  # saved as index 0

        levels = recorder.test_levels(duration_seconds=0.5)

        self.assertEqual(levels["system_sources"], ["Наушники (Senary Audio)"])
        self.assertEqual(levels["system_source"], "Наушники (Senary Audio)")
        self.assertGreater(levels["system"], 0.3)
        self.assertIsNone(levels["microphone"])

    def test_missing_pinned_output_falls_back_to_all_outputs(self):
        self.install([loopback(0, "Динамики"), loopback(1, "Наушники")])
        recorder = AudioRecorder(self.tmp_path, microphone_enabled=False)
        recorder.set_device(None, "Bluetooth [Loopback]")

        levels = recorder.test_levels(duration_seconds=0.5)

        self.assertEqual(levels["system_sources"], ["Динамики", "Наушники"])
        self.assertIsNone(levels["system_source"])

    def test_legacy_microphone_index_maps_to_wasapi_device(self):
        system = self.install(
            [
                microphone(0, "Microphone Array (AMD Audio Dev", host=MME),  # MME cuts names
                microphone(1, "Микрофон (Senary Audio)", host=MME),
                loopback(2, "Наушники"),
                microphone(3, "Микрофон (Senary Audio)", sound=tone(1000)),
                microphone(4, "Microphone Array (AMD Audio Device)", sound=tone(700)),
            ],
            default_mic="Микрофон (Senary Audio)",
        )
        recorder = AudioRecorder(self.tmp_path, microphone_enabled=True, microphone_device_index=0)

        levels = recorder.test_levels(duration_seconds=0.3)

        self.assertEqual(levels["microphone_source"], "Microphone Array (AMD Audio Device)")
        self.assertIn("Microphone Array (AMD Audio Device)", system.opened)

        outputs, microphones = recorder.get_capture_devices()
        self.assertEqual([d.display_name for d in outputs], ["Наушники"])
        self.assertEqual(
            [d.name for d in microphones],
            ["Микрофон (Senary Audio)", "Microphone Array (AMD Audio Device)"],
        )

    def test_default_microphone_follows_windows(self):
        self.install(
            [
                loopback(0, "Наушники"),
                microphone(1, "Микрофон (Senary Audio)"),
                microphone(2, "Microphone Array (AMD Audio Device)"),
            ],
            default_mic="Microphone Array (AMD Audio Device)",
        )
        recorder = AudioRecorder(self.tmp_path, microphone_enabled=True)

        levels = recorder.test_levels(duration_seconds=0.3)

        self.assertEqual(levels["microphone_source"], "Microphone Array (AMD Audio Device)")


if __name__ == "__main__":
    unittest.main()
