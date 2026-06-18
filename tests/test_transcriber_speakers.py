import unittest

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

    def test_assigns_stable_labels_inside_first_diarized_chunk(self):
        segments = [
            segment("A", 0.0, 2.0, "Начинаем встречу"),
            segment("B", 3.0, 5.0, "Подтверждаю план"),
            segment("A", 6.0, 8.0, "Тогда идем дальше"),
        ]

        next_speaker = self.transcriber._normalize_diarized_chunk_speakers(
            segments,
            previous_segments=[],
            chunk_output_start=0.0,
            next_speaker_number=1,
        )

        self.assertEqual([item.speaker for item in segments], [
            "Speaker 1",
            "Speaker 2",
            "Speaker 1",
        ])
        self.assertEqual(next_speaker, 3)

    def test_maps_next_chunk_speaker_when_overlap_matches(self):
        previous_segments = [
            segment("Speaker 1", 586.0, 590.0, "обсуждаем договор поставки"),
        ]
        chunk_segments = [
            segment("A", 586.0, 590.0, "обсуждаем договор поставки"),
            segment("A", 602.0, 606.0, "продолжаю про договор"),
            segment("B", 607.0, 610.0, "добавлю по срокам"),
        ]

        next_speaker = self.transcriber._normalize_diarized_chunk_speakers(
            chunk_segments,
            previous_segments=previous_segments,
            chunk_output_start=600.0,
            next_speaker_number=2,
        )

        self.assertEqual([item.speaker for item in chunk_segments], [
            "Speaker 1",
            "Speaker 1",
            "Speaker 2",
        ])
        self.assertEqual(next_speaker, 3)

    def test_does_not_merge_same_raw_label_without_overlap_evidence(self):
        previous_segments = [
            segment("Speaker 1", 10.0, 12.0, "начали обсуждение"),
        ]
        chunk_segments = [
            segment("A", 620.0, 623.0, "совсем другая часть разговора"),
        ]

        next_speaker = self.transcriber._normalize_diarized_chunk_speakers(
            chunk_segments,
            previous_segments=previous_segments,
            chunk_output_start=600.0,
            next_speaker_number=2,
        )

        self.assertEqual(chunk_segments[0].speaker, "Speaker 2")
        self.assertEqual(next_speaker, 3)


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


if __name__ == "__main__":
    unittest.main()
