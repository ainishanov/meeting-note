import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src.core.database import Recording, Transcript
from src.core.recording_titles import (
    display_recording_title,
    format_recording_title,
    is_auto_generated_title,
    recording_file_stem,
)
from src.export import export_transcript


class RecordingTitlesTest(unittest.TestCase):
    def test_detects_legacy_and_ai_generated_titles(self):
        self.assertTrue(is_auto_generated_title("Запись 19.05.2026 12:12"))
        self.assertTrue(is_auto_generated_title("19.05.2026 12:12 — Обсуждение"))
        self.assertFalse(is_auto_generated_title("План запуска"))

    def test_display_title_uses_recording_datetime_for_generated_titles(self):
        recording = Recording(
            id=88,
            title="19.05.2026 12:12 — Обсуждение",
            audio_path="meeting.wav",
            created_at=datetime(2026, 5, 19, 12, 12, 6),
        )

        self.assertEqual(display_recording_title(recording), "19.05.2026 12:12")
        self.assertEqual(format_recording_title(recording.created_at), "19.05.2026 12:12")

    def test_file_stem_uses_only_id_and_datetime(self):
        recording = Recording(
            id=88,
            title="19.05.2026 12:12 — Обсуждение",
            audio_path="meeting.wav",
            created_at=datetime(2026, 5, 19, 12, 12, 6),
        )

        self.assertEqual(recording_file_stem(recording), "88_19_05_2026 12_12")

    def test_export_file_name_and_header_ignore_ai_generated_title(self):
        recording = Recording(
            id=88,
            title="19.05.2026 12:12 — Обсуждение",
            audio_path="meeting.wav",
            created_at=datetime(2026, 5, 19, 12, 12, 6),
        )
        transcript = Transcript(
            recording_id=88,
            full_text="Текст встречи",
            language="ru",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = export_transcript(
                recording,
                transcript,
                [],
                None,
                "txt",
                Path(tmpdir),
            )
            text = output_path.read_text(encoding="utf-8")

        self.assertEqual(output_path.name, "88_19_05_2026 12_12.txt")
        self.assertIn("ЗАПИСЬ: 19.05.2026 12:12", text)
        self.assertNotIn("Обсуждение", text)


if __name__ == "__main__":
    unittest.main()
