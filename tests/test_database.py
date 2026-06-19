import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from src.core.database import (
    CURRENT_SCHEMA_VERSION,
    Database,
    Recording,
    Summary,
    Transcript,
    TranscriptSegment,
)


class DatabaseSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "database.db")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_get_recordings_by_statuses(self):
        pending_id = self.db.create_recording(
            Recording(title="Pending", audio_path="pending.wav", status="pending")
        )
        self.db.create_recording(
            Recording(title="Done", audio_path="done.wav", status="completed")
        )

        result = self.db.get_recordings_by_statuses(["pending", "transcribing"])

        self.assertEqual([recording.id for recording in result], [pending_id])

    def test_new_database_sets_schema_version_without_backup(self):
        db_path = Path(self.tmpdir.name) / "database.db"

        self.assertEqual(self._schema_version(db_path), CURRENT_SCHEMA_VERSION)
        self.assertFalse((db_path.parent / "backups").exists())

    def test_search_recordings_and_transcript_segments(self):
        recording_id = self.db.create_recording(
            Recording(
                title="План запуска",
                audio_path="launch.wav",
                status="completed",
            )
        )
        transcript_id = self.db.create_transcript(
            Transcript(
                recording_id=recording_id,
                full_text="Обсудили альфа запуск продукта",
                language="ru",
            )
        )
        self.db.add_segments(
            [
                TranscriptSegment(
                    transcript_id=transcript_id,
                    speaker="Speaker 1",
                    speaker_name="Ольга",
                    start_time=0.0,
                    end_time=2.0,
                    text="Обсудили альфа запуск продукта",
                )
            ]
        )
        segments = self.db.get_segments(transcript_id)

        title_results = self.db.search_recordings("План")
        transcript_results = self.db.search_transcripts("альфа")

        self.assertEqual(segments[0].speaker_name, "Ольга")
        self.assertEqual(segments[0].display_speaker, "Ольга")
        self.assertEqual(title_results[0].id, recording_id)
        self.assertEqual(transcript_results[0]["recording_id"], recording_id)
        self.assertEqual(transcript_results[0]["speaker"], "Ольга")

    def test_update_segment_speaker_names(self):
        recording_id = self.db.create_recording(
            Recording(title="Встреча", audio_path="names.wav", status="completed")
        )
        transcript_id = self.db.create_transcript(
            Transcript(
                recording_id=recording_id,
                full_text="Текст встречи",
                language="ru",
            )
        )
        self.db.add_segments(
            [
                TranscriptSegment(
                    transcript_id=transcript_id,
                    speaker="Speaker 1",
                    start_time=0.0,
                    end_time=1.0,
                    text="Я возьму задачу",
                ),
                TranscriptSegment(
                    transcript_id=transcript_id,
                    speaker="Speaker 2",
                    start_time=2.0,
                    end_time=3.0,
                    text="Подтверждаю",
                ),
            ]
        )

        updated = self.db.update_segment_speaker_names(
            transcript_id,
            {"Speaker 1": "Ольга"},
        )
        segments = self.db.get_segments(transcript_id)

        self.assertEqual(updated, 1)
        self.assertEqual(segments[0].display_speaker, "Ольга")
        self.assertEqual(segments[1].display_speaker, "Speaker 2")

    def test_new_recording_statuses_and_processing_queue(self):
        recording_id = self.db.create_recording(
            Recording(title="Queue", audio_path="queue.wav", status="recording")
        )

        self.assertTrue(self.db.update_recording_status(recording_id, "transcribed"))
        self.assertTrue(self.db.update_recording_status(recording_id, "summary_failed"))

        job_id = self.db.create_processing_job(
            recording_id,
            "summary",
            {"reason": "manual"},
        )
        duplicate_id = self.db.create_processing_job(recording_id, "summary")
        next_job = self.db.get_next_processing_job()

        self.assertEqual(job_id, duplicate_id)
        self.assertIsNotNone(next_job)
        self.assertEqual(next_job.recording_id, recording_id)
        self.assertEqual(next_job.job_type, "summary")
        self.assertEqual(next_job.payload, {"reason": "manual"})

        self.assertTrue(self.db.update_processing_job_status(job_id, "running"))
        self.assertEqual(len(self.db.get_active_processing_jobs()), 1)
        self.assertEqual(self.db.requeue_running_processing_jobs(), 1)
        self.assertTrue(self.db.update_processing_job_status(job_id, "completed"))
        self.assertEqual(self.db.get_active_processing_jobs(), [])

    def test_processing_job_payload_heartbeat_and_stale_requeue(self):
        recording_id = self.db.create_recording(
            Recording(title="Queue", audio_path="queue.wav", status="pending")
        )
        job_id = self.db.create_processing_job(recording_id, "transcription")

        self.assertTrue(self.db.update_processing_job_status(job_id, "running"))
        self.assertTrue(
            self.db.touch_processing_job(
                job_id,
                {
                    "progress": {
                        "current": 1,
                        "total": 3,
                        "message": "Фрагмент 1/3 готов",
                    }
                },
            )
        )
        job = self.db.get_processing_job(job_id)
        latest = self.db.get_latest_processing_job_for_recording(recording_id)

        self.assertEqual(job.payload["progress"]["current"], 1)
        self.assertEqual(latest.id, job_id)

        with closing(sqlite3.connect(self.db.db_path)) as conn:
            conn.execute(
                """
                UPDATE processing_jobs
                SET updated_at = datetime('now', '-20 minutes')
                WHERE id = ?
                """,
                (job_id,),
            )
            conn.commit()

        stale_jobs = self.db.get_stale_running_processing_jobs(15 * 60)

        self.assertEqual([job.id for job in stale_jobs], [job_id])
        self.assertTrue(self.db.requeue_processing_job(job_id, "stale"))
        requeued = self.db.get_processing_job(job_id)
        self.assertEqual(requeued.status, "queued")
        self.assertEqual(requeued.error_message, "stale")
        self.assertIsNone(requeued.started_at)

    def test_status_constraint_migration_keeps_child_foreign_keys(self):
        db_path = Path(self.tmpdir.name) / "legacy_status.db"
        with closing(sqlite3.connect(db_path)) as conn:
            conn.executescript(
                """
                CREATE TABLE recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    audio_path TEXT NOT NULL UNIQUE,
                    duration_seconds INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'transcribing', 'completed', 'error'))
                );
                CREATE TABLE transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id INTEGER NOT NULL UNIQUE REFERENCES recordings(id) ON DELETE CASCADE,
                    full_text TEXT,
                    language TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id INTEGER NOT NULL UNIQUE REFERENCES recordings(id) ON DELETE CASCADE,
                    summary TEXT,
                    key_points TEXT,
                    action_items TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE transcript_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transcript_id INTEGER NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
                    speaker TEXT,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    text TEXT NOT NULL
                );
                INSERT INTO recordings (id, title, audio_path, status)
                VALUES (1, 'Legacy', 'legacy.wav', 'completed');
                INSERT INTO transcripts (id, recording_id, full_text, language)
                VALUES (1, 1, 'legacy transcript', 'ru');
                INSERT INTO summaries (id, recording_id, summary)
                VALUES (1, 1, 'legacy summary');
                INSERT INTO transcript_segments (
                    id,
                    transcript_id,
                    speaker,
                    start_time,
                    end_time,
                    text
                )
                VALUES (1, 1, 'Speaker 1', 0, 1, 'legacy transcript');
                """
            )

        db = Database(db_path)

        self.assertTrue(db.update_recording_status(1, "summary_failed"))
        self.assertEqual(self._schema_version(db_path), CURRENT_SCHEMA_VERSION)
        backups = list(
            (db_path.parent / "backups").glob(
                "legacy_status.recording_status_constraint.*.db"
            )
        )
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as backup_conn:
            backup_sql = backup_conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'recordings'"
            ).fetchone()[0]
            self.assertNotIn("summary_failed", backup_sql)

        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            self.assertEqual(self._foreign_key_parent(conn, "transcripts"), "recordings")
            self.assertEqual(self._foreign_key_parent(conn, "summaries"), "recordings")
            self.assertEqual(
                self._foreign_key_parent(conn, "transcript_segments"),
                "transcripts",
            )
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_repairs_child_foreign_keys_that_reference_recordings_old(self):
        db_path = Path(self.tmpdir.name) / "broken_recordings_old.db"
        with closing(sqlite3.connect(db_path)) as conn:
            conn.executescript(
                """
                CREATE TABLE recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    audio_path TEXT NOT NULL UNIQUE,
                    duration_seconds INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'recording', 'transcribing', 'transcribed', 'summarizing', 'summary_failed', 'completed', 'error'))
                );
                CREATE TABLE transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id INTEGER NOT NULL UNIQUE REFERENCES "recordings_old"(id) ON DELETE CASCADE,
                    full_text TEXT,
                    language TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id INTEGER NOT NULL UNIQUE REFERENCES "recordings_old"(id) ON DELETE CASCADE,
                    summary TEXT,
                    key_points TEXT,
                    action_items TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE transcript_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transcript_id INTEGER NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
                    speaker TEXT,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    text TEXT NOT NULL
                );
                INSERT INTO recordings (id, title, audio_path, status)
                VALUES (1, 'Broken', 'broken.wav', 'completed');
                INSERT INTO transcripts (id, recording_id, full_text, language)
                VALUES (1, 1, 'broken transcript', 'ru');
                INSERT INTO summaries (id, recording_id, summary)
                VALUES (1, 1, 'broken summary');
                INSERT INTO transcript_segments (
                    id,
                    transcript_id,
                    speaker,
                    start_time,
                    end_time,
                    text
                )
                VALUES (1, 1, 'Speaker 1', 0, 1, 'broken transcript');
                """
            )

        db = Database(db_path)

        self.assertEqual(db.get_transcript(1).full_text, "broken transcript")
        db.create_summary(Summary(recording_id=1, summary="repaired summary"))
        self.assertEqual(db.get_summary(1).summary, "repaired summary")
        self.assertEqual(self._schema_version(db_path), CURRENT_SCHEMA_VERSION)
        backups = list(
            (db_path.parent / "backups").glob(
                "broken_recordings_old.recordings_old_foreign_keys.*.db"
            )
        )
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as backup_conn:
            backup_conn.row_factory = sqlite3.Row
            self.assertEqual(
                self._foreign_key_parent(backup_conn, "transcripts"),
                "recordings_old",
            )

        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            self.assertEqual(self._foreign_key_parent(conn, "transcripts"), "recordings")
            self.assertEqual(self._foreign_key_parent(conn, "summaries"), "recordings")
            self.assertEqual(
                self._foreign_key_parent(conn, "transcript_segments"),
                "transcripts",
            )
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_health_check_rejects_leftover_recordings_old_table(self):
        db_path = Path(self.tmpdir.name) / "leftover_recordings_old.db"
        Database(db_path)
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute("CREATE TABLE recordings_old (id INTEGER PRIMARY KEY)")
            conn.commit()

        with self.assertRaisesRegex(RuntimeError, "recordings_old"):
            Database(db_path)

    @staticmethod
    def _foreign_key_parent(conn: sqlite3.Connection, table_name: str) -> str:
        row = conn.execute(f"PRAGMA foreign_key_list({table_name})").fetchone()
        return row["table"]

    @staticmethod
    def _schema_version(db_path: Path) -> int:
        with closing(sqlite3.connect(db_path)) as conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
