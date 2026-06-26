import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.core.database import Recording, Transcript
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


if __name__ == "__main__":
    unittest.main()
