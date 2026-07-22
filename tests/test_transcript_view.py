import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.core.database import Recording, Summary, Transcript
from src.ui.transcript_view import TranscriptViewWidget


class TranscriptViewMissingFileNoticeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = TranscriptViewWidget()

    def tearDown(self):
        self.widget.deleteLater()

    def test_normal_recording_hides_previous_missing_file_notice(self):
        missing = Recording(
            id=1,
            title="Missing",
            audio_path="missing.wav",
            status="completed",
        )
        recording = Recording(
            id=2,
            title="Recovered",
            audio_path="recovered.wav",
            status="completed",
        )
        transcript = Transcript(
            recording_id=2,
            full_text="Transcript text",
            language="en",
        )

        self.widget.show_file_missing(missing, None, [], None)

        self.assertFalse(self.widget.progress_frame.isHidden())
        self.assertFalse(self.widget._delete_missing_button.isHidden())

        self.widget.set_recording(recording, transcript, [], None)

        self.assertTrue(self.widget.progress_frame.isHidden())
        self.assertTrue(self.widget._delete_missing_button.isHidden())

    def test_normal_recording_keeps_active_processing_progress_visible(self):
        recording = Recording(
            id=2,
            title="Processing",
            audio_path="processing.wav",
            status="transcribing",
        )

        self.widget.show_progress("Working...")
        self.widget.set_recording(recording, None, [], None)

        self.assertFalse(self.widget.progress_frame.isHidden())
        self.assertFalse(self.widget.progress_bar.isHidden())
        self.assertTrue(self.widget._delete_missing_button.isHidden())
        self.assertEqual(self.widget.progress_label.text(), "Working...")

    def test_processed_recording_opens_summary_and_renders_transcript_lazily(self):
        recording = Recording(
            id=3,
            title="Launch plan",
            audio_path="missing.wav",
            status="completed",
        )
        transcript = Transcript(recording_id=3, full_text="Transcript text", language="en")
        summary = Summary(
            recording_id=3,
            summary="A short summary",
            decisions=["Ship in August"],
            action_items=["Prepare the release"],
        )

        self.widget.set_recording(recording, transcript, [], summary)

        self.assertIs(self.widget.tab_widget.currentWidget(), self.widget.summary_tab)
        self.assertFalse(self.widget._transcript_rendered)
        self.assertEqual(self.widget.decisions_count_label.text(), "1")
        self.assertEqual(self.widget.actions_count_label.text(), "1")

        self.widget.tab_widget.setCurrentWidget(self.widget.transcript_tab)
        self.widget._render_transcript_if_needed()

        self.assertTrue(self.widget._transcript_rendered)
        self.assertIn("Transcript text", self.widget.transcript_text.toPlainText())

    def test_selecting_recording_does_not_initialize_audio_player(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "meeting.wav"
            audio_path.touch()
            recording = Recording(
                id=4,
                title="Audio meeting",
                audio_path=str(audio_path),
                duration_seconds=20,
                status="completed",
            )

            with patch.object(self.widget, "_ensure_player") as ensure_player:
                self.widget.set_recording(recording, None, [], None)

            ensure_player.assert_not_called()
            self.assertIsNone(self.widget._audio_source_path)
            self.assertFalse(self.widget.player_frame.isHidden())


if __name__ == "__main__":
    unittest.main()
