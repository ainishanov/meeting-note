import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.database import Database, Recording, Transcript, Summary as DBSummary
from src.core.summarizer import Summarizer


class DurableQueueRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "database.db")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_requeues_running_jobs_on_startup(self):
        recording_id = self.db.create_recording(
            Recording(title="RunJob", audio_path="run.wav", status="pending")
        )

        job_id = self.db.create_processing_job(recording_id, "summary")
        self.assertTrue(self.db.update_processing_job_status(job_id, "running"))

        requeued = self.db.requeue_running_processing_jobs()
        self.assertEqual(requeued, 1)

        next_job = self.db.get_next_processing_job()
        self.assertIsNotNone(next_job)
        self.assertEqual(next_job.id, job_id)
        self.assertEqual(next_job.job_type, "summary")

    def test_resume_summary_generation_for_transcript_only(self):
        recording_id = self.db.create_recording(
            Recording(title="HasTranscript", audio_path="has_transcript.wav", status="recording")
        )

        self.db.create_transcript(
            Transcript(recording_id=recording_id, full_text="This is the transcript.")
        )

        job_id = self.db.create_processing_job(recording_id, "summary")
        self.assertIsNotNone(job_id)

        with patch("src.core.summarizer.Summarizer.create_summary_for_recording") as mock_create_summary:
            mock_create_summary.return_value = DBSummary(
                recording_id=recording_id,
                summary="FAKE SUMMARY",
                key_points=[],
                decisions=[],
                action_items=[],
            )

            job = self.db.get_next_processing_job()
            self.assertEqual(job.id, job_id)
            self.db.update_processing_job_status(job_id, "running")

            summarizer = Summarizer()
            summary_obj = summarizer.create_summary_for_recording(
                recording_id, "This is the transcript."
            )
            self.db.create_summary(summary_obj)
            self.db.update_processing_job_status(job_id, "completed")

            saved = self.db.get_summary(recording_id)
            self.assertIsNotNone(saved)
            self.assertEqual(saved.summary, "FAKE SUMMARY")

    def test_missing_audio_sets_error_state_without_crash(self):
        recording_id = self.db.create_recording(
            Recording(title="MissingAudio", audio_path="no_such_file.wav", status="recording")
        )

        recording = self.db.get_recording(recording_id)
        self.assertIsNotNone(recording)

        transcript = self.db.get_transcript(recording_id)
        if not transcript or not transcript.full_text:
            updated = self.db.update_recording_status(recording_id, "error")
            self.assertTrue(updated)
            failed = self.db.fail_processing_jobs_for_recording(
                recording_id,
                "Recording was interrupted before it was stopped cleanly",
            )
            self.assertIsInstance(failed, int)

        rec = self.db.get_recording(recording_id)
        self.assertEqual(rec.status, "error")

    def test_ui_status_values_compatible(self):
        from src.core.database import RECORDING_STATUSES

        expected = {
            "pending",
            "recording",
            "transcribing",
            "transcribed",
            "summarizing",
            "summary_failed",
            "completed",
            "error",
        }

        self.assertEqual(RECORDING_STATUSES, expected)


if __name__ == "__main__":
    unittest.main()
