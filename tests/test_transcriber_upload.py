import io
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
from pydub import AudioSegment

from src.core.transcriber import Transcriber, encode_speech_for_upload
from tests.mp3_frames import MPEG2_LAYER3_SAMPLES_PER_FRAME, mp3_frame_headers


def speech_like(seconds: float, frame_rate: int = 48000, channels: int = 2) -> AudioSegment:
    """A voiced tone with noise, in the capture format of a real recording."""
    rng = np.random.default_rng(7)
    t = np.arange(int(seconds * frame_rate)) / frame_rate
    signal = 0.3 * np.sin(2 * np.pi * 180 * t) + 0.05 * rng.standard_normal(t.size)
    samples = (signal * 32767).astype(np.int16)
    if channels == 2:
        samples = np.repeat(samples, 2)
    return AudioSegment(
        samples.tobytes(), frame_rate=frame_rate, sample_width=2, channels=channels,
    )


class EncodeSpeechForUploadTest(unittest.TestCase):
    def test_two_minute_chunk_is_mono_16k_mp3_a_quarter_of_wav_size(self):
        chunk = speech_like(120)

        upload = encode_speech_for_upload(chunk, "chunk")

        self.assertEqual(upload.filename, "chunk.mp3")
        self.assertEqual(upload.mime_type, "audio/mpeg")
        frames = mp3_frame_headers(upload.getvalue())
        self.assertEqual({frame.sample_rate for frame in frames}, {16000})
        self.assertTrue(all(frame.mono for frame in frames))
        duration = len(frames) * MPEG2_LAYER3_SAMPLES_PER_FRAME / 16000
        self.assertAlmostEqual(duration, 120, delta=0.5)
        wav_size = 120 * 16000 * 2
        self.assertLess(len(upload.getvalue()), wav_size / 3.5)

    def test_falls_back_to_wav_when_mp3_encoder_is_missing(self):
        with patch.dict(sys.modules, {"lameenc": None}):
            upload = encode_speech_for_upload(speech_like(3), "chunk")

        self.assertEqual(upload.filename, "chunk.wav")
        self.assertEqual(upload.mime_type, "audio/wav")
        with wave.open(io.BytesIO(upload.getvalue())) as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getframerate(), 16000)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertAlmostEqual(wav.getnframes() / 16000, 3, delta=0.01)


class TranscriptionUploadRequestTest(unittest.TestCase):
    def setUp(self):
        self.transcriber = Transcriber(api_key="offline-test")
        self.create = MagicMock(return_value={"text": "ok", "language": "ru"})
        self.transcriber._client = SimpleNamespace(
            audio=SimpleNamespace(
                transcriptions=SimpleNamespace(create=self.create),
            ),
        )

    def test_chunk_request_sends_encoded_filename_and_mime_type(self):
        upload = encode_speech_for_upload(speech_like(2), "chunk")

        self.transcriber._request_chunk_transcription(
            upload, self.transcriber.DEFAULT_MODEL, "ru", 1,
        )

        filename, body, mime_type = self.create.call_args.kwargs["file"]
        self.assertEqual((filename, mime_type), ("chunk.mp3", "audio/mpeg"))
        self.assertIs(body, upload)

    def test_plain_buffer_is_still_sent_as_wav(self):
        buffer = io.BytesIO(b"RIFF")

        self.transcriber._request_chunk_transcription(
            buffer, self.transcriber.DEFAULT_MODEL, "ru", 1,
        )

        filename, _, mime_type = self.create.call_args.kwargs["file"]
        self.assertEqual((filename, mime_type), ("chunk.wav", "audio/wav"))

    def test_short_wav_recording_is_uploaded_as_mp3(self):
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "recording 19_11_2026 21_02.wav"
            speech_like(5, frame_rate=16000, channels=1).export(
                audio_path, format="wav",
            ).close()

            self.transcriber._transcribe_single(
                audio_path, "ru", 5.0, self.transcriber.DEFAULT_MODEL,
            )

        filename, body, mime_type = self.create.call_args.kwargs["file"]
        self.assertEqual((filename, mime_type), ("recording.mp3", "audio/mpeg"))
        self.assertLess(len(body.getvalue()), 5 * 16000 * 2 / 3.5)

    def test_non_wav_recording_is_uploaded_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "imported.m4a"
            audio_path.write_bytes(b"not decoded locally")

            self.transcriber._transcribe_single(
                audio_path, "ru", 5.0, self.transcriber.DEFAULT_MODEL,
            )

            uploaded = self.create.call_args.kwargs["file"]
            self.assertEqual(Path(uploaded.name), audio_path)


if __name__ == "__main__":
    unittest.main()
