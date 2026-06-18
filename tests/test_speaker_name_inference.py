import unittest

from src.core.database import TranscriptSegment
from src.core.summarizer import Summarizer, apply_speaker_names


def segment(speaker, text):
    return TranscriptSegment(
        transcript_id=1,
        speaker=speaker,
        start_time=0.0,
        end_time=1.0,
        text=text,
    )


class SpeakerNameInferenceParsingTest(unittest.TestCase):
    def test_accepts_only_high_confidence_names(self):
        summarizer = Summarizer(api_key="test")

        result = summarizer._parse_speaker_name_map(
            {
                "speakers": [
                    {
                        "speaker": "Speaker 1",
                        "name": "Ольга",
                        "confidence": "high",
                    },
                    {
                        "speaker": "Speaker 2",
                        "name": "Мария",
                        "confidence": "medium",
                    },
                ]
            }
        )

        self.assertEqual(result, {"Speaker 1": "Ольга"})

    def test_drops_duplicate_names_for_different_speakers(self):
        summarizer = Summarizer(api_key="test")

        result = summarizer._parse_speaker_name_map(
            {
                "speakers": [
                    {
                        "speaker": "Speaker 1",
                        "name": "Ольга",
                        "confidence": "high",
                    },
                    {
                        "speaker": "Speaker 2",
                        "name": "ольга",
                        "confidence": "high",
                    },
                ]
            }
        )

        self.assertEqual(result, {})

    def test_rejects_placeholder_and_too_short_names(self):
        summarizer = Summarizer(api_key="test")

        self.assertIsNone(summarizer._clean_speaker_name("Speaker 1"))
        self.assertIsNone(summarizer._clean_speaker_name("А"))
        self.assertEqual(summarizer._clean_speaker_name(" Ольга "), "Ольга")

    def test_apply_speaker_names_sets_display_name_only(self):
        segments = [segment("Speaker 1", "Я возьму задачу")]

        apply_speaker_names(segments, {"Speaker 1": "Ольга"})

        self.assertEqual(segments[0].speaker, "Speaker 1")
        self.assertEqual(segments[0].speaker_name, "Ольга")
        self.assertEqual(segments[0].display_speaker, "Ольга")


if __name__ == "__main__":
    unittest.main()
