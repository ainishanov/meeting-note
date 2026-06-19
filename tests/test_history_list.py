import unittest

from src.core.database import Recording
from src.ui.history_list import (
    _is_active_recording_or_processing,
    _shows_recording_badge,
)


class HistoryListStatusBadgeTest(unittest.TestCase):
    def test_only_active_recording_status_shows_recording_badge(self):
        recording = Recording(
            id=107,
            title="Meeting",
            audio_path="meeting.wav",
            status="recording",
        )

        self.assertTrue(_shows_recording_badge(recording, 107))

    def test_active_transcription_keeps_transcribing_badge(self):
        recording = Recording(
            id=107,
            title="Meeting",
            audio_path="meeting.wav",
            status="transcribing",
        )

        self.assertFalse(_shows_recording_badge(recording, 107))

    def test_other_recording_does_not_show_recording_badge(self):
        recording = Recording(
            id=107,
            title="Meeting",
            audio_path="meeting.wav",
            status="recording",
        )

        self.assertFalse(_shows_recording_badge(recording, 108))

    def test_active_processing_blocks_delete_without_recording_badge(self):
        recording = Recording(
            id=107,
            title="Meeting",
            audio_path="meeting.wav",
            status="transcribing",
        )

        self.assertFalse(_shows_recording_badge(recording, None))
        self.assertTrue(_is_active_recording_or_processing(107, None, 107))


if __name__ == "__main__":
    unittest.main()
