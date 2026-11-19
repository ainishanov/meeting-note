import base64
import io
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from pydub import AudioSegment

from src.core.database import TranscriptSegment
from src.core.transcriber import Transcriber
from src.ui.main_window import MainWindow


def segment(speaker, start, end, text):
    return TranscriptSegment(
        transcript_id=1,
        speaker=speaker,
        start_time=start,
        end_time=end,
        text=text,
    )


class TranscriberSpeakerNormalizationTest(unittest.TestCase):
    def setUp(self):
        self.transcriber = Transcriber(api_key="test")

    def test_sanitizes_invalid_speaker_labels(self):
        self.assertIsNone(self.transcriber._sanitize_speaker_label("@"))
        self.assertIsNone(self.transcriber._sanitize_speaker_label("   "))
        self.assertEqual(self.transcriber._sanitize_speaker_label(" A "), "A")
        self.assertEqual(
            self.transcriber._sanitize_speaker_label("Speaker   1"),
            "Speaker 1",
        )

    def test_assigns_stable_labels_for_whole_recording(self):
        segments = [
            segment("A", 0.0, 2.0, "Начинаем встречу"),
            segment("B", 3.0, 5.0, "Подтверждаю план"),
            segment("A", 6.0, 8.0, "Тогда идем дальше"),
        ]

        self.transcriber._normalize_global_speaker_labels(segments)

        self.assertEqual([item.speaker for item in segments], [
            "Speaker 1",
            "Speaker 2",
            "Speaker 1",
        ])

    def test_builds_api_compatible_speaker_reference(self):
        segments = [
            segment("A", 0.0, 1.0, "Короткая реплика"),
        ]
        audio = AudioSegment.silent(duration=3000, frame_rate=16000)

        reference = self.transcriber._build_speaker_reference(
            audio,
            segments,
            "A",
            chunk_start_seconds=0.0,
        )

        prefix = "data:audio/wav;base64,"
        self.assertTrue(reference.startswith(prefix))
        with wave.open(io.BytesIO(base64.b64decode(reference[len(prefix) :]))) as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getframerate(), 16000)
            self.assertGreaterEqual(wav.getnframes() / wav.getframerate(), 2.0)
            self.assertLessEqual(wav.getnframes() / wav.getframerate(), 10.0)

    def test_enrolls_local_labels_and_maps_known_voice_names(self):
        segments = [segment("A", 123.0, 126.0, "Новый голос")]
        audio = AudioSegment.silent(duration=10000, frame_rate=16000)
        speaker_references = {"speaker_1": "data:audio/wav;base64,known"}

        enrolled_name = self.transcriber._enroll_next_speaker(
            segments,
            audio,
            chunk_start_seconds=120.0,
            speaker_references=speaker_references,
        )

        classified_segments = [
            segment("speaker_1", 120.0, 123.0, "Уже известный голос"),
            segment("speaker_2", 123.0, 126.0, "Новый голос"),
        ]
        self.transcriber._map_known_speaker_labels(
            classified_segments,
            speaker_references,
        )

        self.assertEqual(enrolled_name, "speaker_2")
        self.assertEqual(
            [item.speaker for item in classified_segments],
            ["Speaker 1", "Speaker 2"],
        )
        self.assertEqual(list(speaker_references), ["speaker_1", "speaker_2"])

    def test_enrollment_respects_provider_reference_limit(self):
        segments = [segment("A", 0.0, 3.0, "Неизвестный голос")]
        audio = AudioSegment.silent(duration=3000, frame_rate=16000)
        speaker_references = {
            f"speaker_{index}": "data:audio/wav;base64,known"
            for index in range(1, 5)
        }

        with self.assertRaisesRegex(RuntimeError, "unrecognized voice"):
            self.transcriber._enroll_next_speaker(
                segments,
                audio,
                chunk_start_seconds=0.0,
                speaker_references=speaker_references,
            )

    def test_resolves_only_subsecond_unknown_label_to_nearest_known_turn(self):
        segments = [
            segment("speaker_1", 10.0, 12.0, "До"),
            segment("A", 12.0, 12.05, "и"),
            segment("speaker_2", 12.2, 14.0, "После"),
        ]
        speaker_references = {
            f"speaker_{index}": "data:audio/wav;base64,known"
            for index in range(1, 5)
        }

        self.transcriber._resolve_short_unknown_segments(
            segments,
            speaker_references,
        )

        self.assertEqual(segments[1].speaker, "speaker_1")

    def test_resolves_unknown_label_below_reference_minimum(self):
        segments = [
            segment("speaker_1", 10.0, 12.0, "До"),
            segment("A", 12.0, 13.7, "Слишком коротко для эталона"),
            segment("speaker_2", 14.0, 16.0, "После"),
        ]
        speaker_references = {
            f"speaker_{index}": "data:audio/wav;base64,known"
            for index in range(1, 5)
        }

        self.transcriber._resolve_short_unknown_segments(
            segments,
            speaker_references,
        )

        self.assertEqual(segments[1].speaker, "speaker_1")

    def test_preserves_meaningful_unknown_turn_for_profile_refresh(self):
        segments = [
            segment("speaker_1", 10.0, 12.0, "До"),
            segment("A", 12.0, 15.0, "Полноценная реплика"),
        ]
        speaker_references = {
            f"speaker_{index}": "data:audio/wav;base64,known"
            for index in range(1, 5)
        }

        self.transcriber._resolve_short_unknown_segments(
            segments,
            speaker_references,
        )

        self.assertEqual(segments[1].speaker, "A")

    def test_uses_two_minute_bounded_chunks(self):
        self.assertEqual(self.transcriber.MAX_CHUNK_DURATION, 120)

    def test_preserves_unmatched_speech_alongside_four_known_voices(self):
        references = {
            f"speaker_{index}": "data:audio/wav;base64,known"
            for index in range(1, 5)
        }
        response = {
            "text": "Known turns. An unmatched voice still needs to be saved.",
            "segments": [
                {"speaker": f"speaker_{index}", "start": (index - 1) * 3,
                 "end": index * 3, "text": f"Known turn {index}."}
                for index in range(1, 5)
            ] + [
                {"speaker": "A", "start": 12.0, "end": 35.9,
                 "text": "An unmatched voice still needs to be saved."},
            ],
        }
        with patch.object(
            self.transcriber, "_request_chunk_transcription", return_value=response,
        ) as request:
            text, _, segments = self.transcriber._transcribe_diarized_chunk(
                io.BytesIO(),
                AudioSegment.silent(duration=40000, frame_rate=16000),
                "en", 1680.0, 15, references, {},
            )

        request.assert_called_once()
        self.assertEqual(text, response["text"])
        self.assertEqual([s.speaker for s in segments], [
            "Speaker 1", "Speaker 2", "Speaker 3", "Speaker 4", None,
        ])
        self.assertEqual(segments[-1].start_time, 1692.0)
        self.assertEqual(segments[-1].text, response["segments"][-1]["text"])
        self.assertEqual(segments[-1].display_speaker, "Unidentified speaker")
        self.assertEqual(len(references), 4)

    def test_unmatched_voice_does_not_replace_an_existing_speaker_identity(self):
        references = {
            f"speaker_{index}": f"original-reference-{index}"
            for index in range(1, 5)
        }
        response = {
            "text": "A new or unmatched voice.",
            "segments": [{"speaker": "A", "start": 0.0, "end": 3.0,
                          "text": "A new or unmatched voice."}],
        }
        original_references = references.copy()
        with patch.object(
            self.transcriber, "_request_chunk_transcription", return_value=response,
        ) as request:
            _, _, segments = self.transcriber._transcribe_diarized_chunk(
                io.BytesIO(),
                AudioSegment.silent(duration=4000, frame_rate=16000),
                "en", 0.0, 15, references, {},
            )

        request.assert_called_once()
        self.assertEqual(references, original_references)
        self.assertIsNone(segments[0].speaker)
        self.assertIsNone(segments[0].speaker_name)

    def test_nonconverging_enrollment_preserves_text_after_bounded_attempts(self):
        response = {
            "text": "Keep this speech even if recognition does not converge.",
            "segments": [{"speaker": "A", "start": 0.0, "end": 3.0,
                          "text": "Keep this speech even if recognition does not converge."}],
        }
        references = {}
        with patch.object(
            self.transcriber, "_request_chunk_transcription", return_value=response,
        ) as request:
            text, _, segments = self.transcriber._transcribe_diarized_chunk(
                io.BytesIO(),
                AudioSegment.silent(duration=4000, frame_rate=16000),
                "en", 0.0, 1, references, {},
            )

        self.assertEqual(request.call_count, self.transcriber.MAX_KNOWN_SPEAKERS * 3)
        self.assertEqual(text, response["text"])
        self.assertIsNone(segments[0].speaker)
        self.assertEqual(segments[0].text, response["text"])

    def test_routes_long_diarization_to_chunked_pipeline(self):
        expected = object()
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio_file:
            with patch(
                "scipy.io.wavfile.read",
                return_value=(16000, np.zeros(16000 * 121, dtype=np.int16)),
            ), patch.object(
                self.transcriber,
                "_transcribe_chunked",
                return_value=expected,
            ) as chunked:
                result = self.transcriber.transcribe(
                    Path(audio_file.name),
                    language="ru",
                    model=self.transcriber.DIARIZE_MODEL,
                    resume_key="recording-1",
                )

        self.assertIs(result, expected)
        chunked.assert_called_once()

    def test_chunked_diarization_passes_enrolled_voices_to_next_request(self):
        responses = [
            SimpleNamespace(
                text="Первый Второй",
                language="ru",
                segments=[
                    SimpleNamespace(speaker="A", start=0.0, end=1.0, text="Первый"),
                    SimpleNamespace(speaker="B", start=1.0, end=2.0, text="Второй"),
                ],
            ),
            SimpleNamespace(
                text="Первый Второй",
                language="ru",
                segments=[
                    SimpleNamespace(
                        speaker="speaker_1", start=0.0, end=1.0, text="Первый"
                    ),
                    SimpleNamespace(speaker="B", start=1.0, end=2.0, text="Второй"),
                ],
            ),
            SimpleNamespace(
                text="Первый Второй",
                language="ru",
                segments=[
                    SimpleNamespace(
                        speaker="speaker_1", start=0.0, end=1.0, text="Первый"
                    ),
                    SimpleNamespace(
                        speaker="speaker_2", start=1.0, end=2.0, text="Второй"
                    ),
                ],
            ),
            SimpleNamespace(
                text="Снова первый и второй",
                language="ru",
                segments=[
                    SimpleNamespace(
                        speaker="speaker_1", start=0.0, end=1.0, text="Снова первый"
                    ),
                    SimpleNamespace(
                        speaker="speaker_2", start=1.0, end=2.0, text="и второй"
                    ),
                ],
            ),
        ]
        requests = []

        def create(**kwargs):
            requests.append(kwargs)
            return responses[len(requests) - 1]

        client = SimpleNamespace(
            audio=SimpleNamespace(
                transcriptions=SimpleNamespace(create=create),
            )
        )
        self.transcriber.MAX_CHUNK_DURATION = 2
        audio = AudioSegment.silent(duration=4000, frame_rate=16000)

        with patch("src.core.transcriber.AudioSegment.from_file", return_value=audio), patch.object(
            self.transcriber, "_is_silent_chunk", return_value=False
        ), patch.object(self.transcriber, "_get_client", return_value=client):
            result = self.transcriber._transcribe_chunked(
                Path(__file__),
                language="ru",
                duration_seconds=4.0,
                model=self.transcriber.DIARIZE_MODEL,
            )

        self.assertNotIn("known_speaker_names", requests[0])
        self.assertEqual(
            requests[1]["known_speaker_names"], ["speaker_1"]
        )
        self.assertEqual(
            requests[2]["known_speaker_names"],
            ["speaker_1", "speaker_2"],
        )
        self.assertEqual(
            requests[3]["known_speaker_names"],
            ["speaker_1", "speaker_2"],
        )
        self.assertEqual(len(requests[3]["known_speaker_references"]), 2)
        self.assertEqual(
            [item.speaker for item in result.segments],
            ["Speaker 1", "Speaker 2", "Speaker 1", "Speaker 2"],
        )

    def test_disables_nested_sdk_retries(self):
        self.assertEqual(self.transcriber._get_client().max_retries, 0)


class LegacySpeakerLabelDetectionTest(unittest.TestCase):
    def test_detects_long_recordings_with_raw_letter_labels(self):
        segments = [
            segment("A", 0.0, 2.0, "Первый говорит"),
            segment("B", 3.0, 5.0, "Второй отвечает"),
        ]

        self.assertTrue(
            MainWindow._has_legacy_chunk_speaker_labels(
                segments,
                duration_seconds=1200,
            )
        )

    def test_keeps_existing_global_speaker_labels_on_retry(self):
        segments = [
            segment("Speaker 1", 0.0, 2.0, "Первый говорит"),
            segment("Speaker 2", 3.0, 5.0, "Второй отвечает"),
        ]

        self.assertFalse(
            MainWindow._has_legacy_chunk_speaker_labels(
                segments,
                duration_seconds=1200,
            )
        )


class ProcessingErrorFormattingTest(unittest.TestCase):
    def test_connection_error_preserves_recording_and_gives_next_action(self):
        with patch("src.ui.i18n.current_language", return_value="ru"):
            message = MainWindow._format_processing_error(
                None,
                Exception("Connection error."),
                "transcription",
            )

        self.assertIn("Запись сохранена", message)
        self.assertIn("Повторите транскрибацию", message)
        self.assertIn("VPN", message)


if __name__ == "__main__":
    unittest.main()
