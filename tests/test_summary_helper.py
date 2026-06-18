import unittest

from src.core.database import TranscriptSegment
from src.core.summarizer import create_speaker_aware_summary


class FakeSummarizer:
    def __init__(self):
        self.used_segments = False

    def summarize_with_segments(self, segments, max_tokens=2000):
        self.used_segments = True
        self.segments = segments
        return type(
            "Result",
            (),
            {
                "summary": "speaker summary",
                "key_points": ["point"],
                "decisions": ["decision"],
                "action_items": ["task"],
            },
        )()

    def create_summary_for_recording(self, recording_id, transcript_text):
        return type(
            "Summary",
            (),
            {
                "recording_id": recording_id,
                "summary": "plain summary",
                "key_points": [],
                "decisions": [],
                "action_items": [],
            },
        )()


class SpeakerAwareSummaryTest(unittest.TestCase):
    def test_uses_segments_when_speakers_are_available(self):
        summarizer = FakeSummarizer()
        segments = [
            TranscriptSegment(
                transcript_id=1,
                speaker="Speaker 1",
                speaker_name="Ольга",
                start_time=0.0,
                end_time=1.0,
                text="Нужно подготовить договор",
            )
        ]

        summary = create_speaker_aware_summary(
            summarizer, 10, "Нужно подготовить договор", segments
        )

        self.assertTrue(summarizer.used_segments)
        self.assertEqual(summarizer.segments[0]["speaker"], "Ольга")
        self.assertEqual(summary.summary, "speaker summary")


if __name__ == "__main__":
    unittest.main()
