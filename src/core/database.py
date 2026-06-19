"""SQLite database operations for Meeting Note."""

import json
import re
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional

from loguru import logger
from pydantic import BaseModel


RECORDING_STATUSES = {
    "pending",
    "recording",
    "transcribing",
    "transcribed",
    "summarizing",
    "summary_failed",
    "completed",
    "error",
}

PROCESSING_JOB_TYPES = {"transcription", "summary"}
PROCESSING_JOB_STATUSES = {"queued", "running", "completed", "failed"}
CURRENT_SCHEMA_VERSION = 3


class Recording(BaseModel):
    """Recording data model."""

    id: Optional[int] = None
    title: str
    audio_path: str
    duration_seconds: Optional[int] = None
    created_at: Optional[datetime] = None
    status: str = "pending"


class Transcript(BaseModel):
    """Transcript data model."""

    id: Optional[int] = None
    recording_id: int
    full_text: Optional[str] = None
    language: Optional[str] = None
    created_at: Optional[datetime] = None


class TranscriptSegment(BaseModel):
    """Transcript segment with speaker info."""

    id: Optional[int] = None
    transcript_id: int
    speaker: Optional[str] = None
    speaker_name: Optional[str] = None
    start_time: float
    end_time: float
    text: str

    @property
    def display_speaker(self) -> str:
        return self.speaker_name or self.speaker or "Speaker"


class Summary(BaseModel):
    """Meeting summary data model."""

    id: Optional[int] = None
    recording_id: int
    summary: Optional[str] = None
    key_points: Optional[list[str]] = None
    decisions: Optional[list[str]] = None
    action_items: Optional[list[str]] = None
    created_at: Optional[datetime] = None


class ProcessingJob(BaseModel):
    """Durable processing task for transcription and summary generation."""

    id: Optional[int] = None
    recording_id: int
    job_type: str
    status: str = "queued"
    payload: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    attempts: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


SCHEMA_SQL = """
-- Recordings table
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    audio_path TEXT NOT NULL UNIQUE,
    duration_seconds INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'recording', 'transcribing', 'transcribed', 'summarizing', 'summary_failed', 'completed', 'error'))
);

-- Transcripts table
CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL UNIQUE REFERENCES recordings(id) ON DELETE CASCADE,
    full_text TEXT,
    language TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Transcript segments with speaker diarization
CREATE TABLE IF NOT EXISTS transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transcript_id INTEGER NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    speaker TEXT,
    speaker_name TEXT,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    text TEXT NOT NULL
);

-- Summaries table
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL UNIQUE REFERENCES recordings(id) ON DELETE CASCADE,
    summary TEXT,
    key_points TEXT,  -- JSON array
    decisions TEXT,  -- JSON array
    action_items TEXT,  -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Durable background processing queue
CREATE TABLE IF NOT EXISTS processing_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL CHECK(job_type IN ('transcription', 'summary')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued', 'running', 'completed', 'failed')),
    payload TEXT,
    error_message TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

-- Full-text search index for transcripts
CREATE VIRTUAL TABLE IF NOT EXISTS transcript_fts USING fts5(
    text,
    content='transcript_segments',
    content_rowid='id'
);

-- Triggers to keep FTS index in sync
CREATE TRIGGER IF NOT EXISTS transcript_segments_ai AFTER INSERT ON transcript_segments BEGIN
    INSERT INTO transcript_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS transcript_segments_ad AFTER DELETE ON transcript_segments BEGIN
    INSERT INTO transcript_fts(transcript_fts, rowid, text) VALUES('delete', old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS transcript_segments_au AFTER UPDATE ON transcript_segments BEGIN
    INSERT INTO transcript_fts(transcript_fts, rowid, text) VALUES('delete', old.id, old.text);
    INSERT INTO transcript_fts(rowid, text) VALUES (new.id, new.text);
END;

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_recordings_status ON recordings(status);
CREATE INDEX IF NOT EXISTS idx_recordings_created ON recordings(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_segments_transcript ON transcript_segments(transcript_id);
CREATE INDEX IF NOT EXISTS idx_segments_speaker ON transcript_segments(speaker);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_status ON processing_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_recording ON processing_jobs(recording_id, status);
"""


class Database:
    """SQLite database manager for Meeting Note."""

    def __init__(self, db_path: Path):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._migration_backups: list[Path] = []
        self._ensure_database()

    def _ensure_database(self) -> None:
        """Create database and tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            self._run_schema_migrations(conn)
            conn.executescript(SCHEMA_SQL)
            self._validate_schema_health(conn)
            logger.info(f"Database initialized at {self.db_path}")

    def _run_schema_migrations(self, conn: sqlite3.Connection) -> None:
        """Run idempotent SQLite migrations and mark the schema version."""
        version = self._get_schema_version(conn)
        if version > CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {version} is newer than supported "
                f"version {CURRENT_SCHEMA_VERSION}"
            )

        migrations = (
            (1, "recording_status_constraint", self._migrate_recording_status_constraint),
            (2, "summary_decisions_and_speaker_names", self._migrate_missing_columns),
            (3, "recordings_old_foreign_keys", self._repair_recordings_old_foreign_keys),
        )
        for target_version, name, migration in migrations:
            if version >= target_version:
                continue

            logger.info(f"Running database migration {target_version}: {name}")
            migration(conn)
            self._set_schema_version(conn, target_version)
            version = target_version

    @staticmethod
    def _get_schema_version(conn: sqlite3.Connection) -> int:
        row = conn.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
        conn.execute(f"PRAGMA user_version = {version}")

    def _migrate_recording_status_constraint(self, conn: sqlite3.Connection) -> None:
        """Rebuild old recordings table if its CHECK lacks new statuses."""
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'recordings'"
        ).fetchone()
        table_sql = (row["sql"] or "") if row else ""
        if "summary_failed" in table_sql and "transcribed" in table_sql:
            return

        logger.info("Migrating recordings status constraint")
        self._create_migration_backup(conn, "recording_status_constraint")
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA legacy_alter_table = ON")
        try:
            conn.execute("ALTER TABLE recordings RENAME TO recordings_old")
            conn.execute(
                """
                CREATE TABLE recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    audio_path TEXT NOT NULL UNIQUE,
                    duration_seconds INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending' CHECK(status IN (
                        'pending',
                        'recording',
                        'transcribing',
                        'transcribed',
                        'summarizing',
                        'summary_failed',
                        'completed',
                        'error'
                    ))
                )
                """
            )
            conn.execute(
                """
                INSERT INTO recordings (
                    id,
                    title,
                    audio_path,
                    duration_seconds,
                    created_at,
                    status
                )
                SELECT
                    id,
                    title,
                    audio_path,
                    duration_seconds,
                    created_at,
                    CASE
                        WHEN status IN (
                            'pending',
                            'recording',
                            'transcribing',
                            'transcribed',
                            'summarizing',
                            'summary_failed',
                            'completed',
                            'error'
                        )
                        THEN status
                        ELSE 'error'
                    END
                FROM recordings_old
                """
            )
            conn.execute("DROP TABLE recordings_old")
        finally:
            conn.execute("PRAGMA legacy_alter_table = OFF")
            conn.execute("PRAGMA foreign_keys = ON")

    def _migrate_missing_columns(self, conn: sqlite3.Connection) -> None:
        """Add columns introduced after the initial schema."""
        self._add_column_if_missing(conn, "summaries", "decisions", "TEXT")
        self._add_column_if_missing(conn, "transcript_segments", "speaker_name", "TEXT")

    def _add_column_if_missing(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_definition: str,
    ) -> None:
        if column_name in self._table_columns(conn, table_name):
            return

        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
        logger.info(f"Added '{column_name}' column to {table_name} table")

    def _repair_recordings_old_foreign_keys(self, conn: sqlite3.Connection) -> None:
        """Repair child tables left referencing recordings_old by an older migration."""
        broken_tables = [
            table
            for table in ("transcripts", "summaries", "processing_jobs")
            if self._table_references_parent(conn, table, "recordings_old")
        ]
        if not broken_tables:
            return

        logger.info(f"Repairing recordings_old foreign keys in {broken_tables}")
        self._create_migration_backup(conn, "recordings_old_foreign_keys")
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA legacy_alter_table = ON")
        try:
            if "transcripts" in broken_tables:
                self._rebuild_transcripts_table(conn)
            if "summaries" in broken_tables:
                self._rebuild_summaries_table(conn)
            if "processing_jobs" in broken_tables:
                self._rebuild_processing_jobs_table(conn)
            conn.executescript(SCHEMA_SQL)
        finally:
            conn.execute("PRAGMA legacy_alter_table = OFF")
            conn.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _table_references_parent(
        conn: sqlite3.Connection,
        table_name: str,
        parent_name: str,
    ) -> bool:
        rows = conn.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
        return any(row["table"] == parent_name for row in rows)

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row["name"] for row in rows}

    def _create_migration_backup(
        self,
        conn: sqlite3.Connection,
        reason: str,
    ) -> Optional[Path]:
        """Create a consistent SQLite backup before a table rebuild."""
        if self.db_path.name in {":memory:", ""}:
            return None

        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = (
            backup_dir
            / f"{self.db_path.stem}.{reason}.{timestamp}{self.db_path.suffix}"
        )

        with closing(sqlite3.connect(str(backup_path))) as backup_conn:
            conn.backup(backup_conn)

        self._migration_backups.append(backup_path)
        logger.info(f"Created database migration backup at {backup_path}")
        return backup_path

    def _rebuild_transcripts_table(self, conn: sqlite3.Connection) -> None:
        self._rebuild_table(
            conn,
            table_name="transcripts",
            create_sql="""
                CREATE TABLE transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id INTEGER NOT NULL UNIQUE REFERENCES recordings(id) ON DELETE CASCADE,
                    full_text TEXT,
                    language TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            copy_columns=("id", "recording_id", "full_text", "language", "created_at"),
        )

    def _rebuild_summaries_table(self, conn: sqlite3.Connection) -> None:
        self._rebuild_table(
            conn,
            table_name="summaries",
            create_sql="""
                CREATE TABLE summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id INTEGER NOT NULL UNIQUE REFERENCES recordings(id) ON DELETE CASCADE,
                    summary TEXT,
                    key_points TEXT,
                    decisions TEXT,
                    action_items TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """,
            copy_columns=(
                "id",
                "recording_id",
                "summary",
                "key_points",
                "decisions",
                "action_items",
                "created_at",
            ),
        )

    def _rebuild_processing_jobs_table(self, conn: sqlite3.Connection) -> None:
        self._rebuild_table(
            conn,
            table_name="processing_jobs",
            create_sql="""
                CREATE TABLE processing_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
                    job_type TEXT NOT NULL CHECK(job_type IN ('transcription', 'summary')),
                    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued', 'running', 'completed', 'failed')),
                    payload TEXT,
                    error_message TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP
                )
            """,
            copy_columns=(
                "id",
                "recording_id",
                "job_type",
                "status",
                "payload",
                "error_message",
                "attempts",
                "created_at",
                "updated_at",
                "started_at",
                "completed_at",
            ),
            defaults={"attempts": "0", "status": "'queued'"},
        )

    def _rebuild_table(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        create_sql: str,
        copy_columns: tuple[str, ...],
        defaults: Optional[dict[str, str]] = None,
    ) -> None:
        old_table_name = f"{table_name}_old_fk_repair"
        old_columns = self._table_columns(conn, table_name)
        conn.execute(f"ALTER TABLE {table_name} RENAME TO {old_table_name}")
        conn.execute(create_sql)

        select_exprs = []
        for column in copy_columns:
            if column in old_columns:
                select_exprs.append(column)
            else:
                select_exprs.append((defaults or {}).get(column, f"NULL AS {column}"))
        conn.execute(
            f"""
            INSERT INTO {table_name} ({', '.join(copy_columns)})
            SELECT {', '.join(select_exprs)}
            FROM {old_table_name}
            """
        )
        conn.execute(f"DROP TABLE {old_table_name}")

    def _validate_schema_health(self, conn: sqlite3.Connection) -> None:
        """Fail fast on broken SQLite schema state after migrations."""
        orphaned_temp_tables = {
            "recordings_old",
            "transcripts_old_fk_repair",
            "summaries_old_fk_repair",
            "processing_jobs_old_fk_repair",
        }
        existing_orphans = [
            name
            for name in orphaned_temp_tables
            if self._table_exists(conn, name)
        ]
        if existing_orphans:
            raise RuntimeError(
                "Database schema contains leftover migration tables: "
                + ", ".join(sorted(existing_orphans))
            )

        required_columns = {
            "recordings": {"id", "title", "audio_path", "status"},
            "transcripts": {"id", "recording_id", "full_text", "language"},
            "transcript_segments": {
                "id",
                "transcript_id",
                "speaker",
                "speaker_name",
                "start_time",
                "end_time",
                "text",
            },
            "summaries": {
                "id",
                "recording_id",
                "summary",
                "key_points",
                "decisions",
                "action_items",
            },
            "processing_jobs": {"id", "recording_id", "job_type", "status"},
        }
        for table_name, expected_columns in required_columns.items():
            columns = self._table_columns(conn, table_name)
            missing_columns = expected_columns - columns
            if missing_columns:
                raise RuntimeError(
                    f"Database table {table_name} is missing columns: "
                    + ", ".join(sorted(missing_columns))
                )

        expected_fk_parents = {
            "transcripts": {"recordings"},
            "summaries": {"recordings"},
            "processing_jobs": {"recordings"},
            "transcript_segments": {"transcripts"},
        }
        for table_name, expected_parents in expected_fk_parents.items():
            actual_parents = self._foreign_key_parents(conn, table_name)
            missing_parents = expected_parents - actual_parents
            if missing_parents:
                raise RuntimeError(
                    f"Database table {table_name} has invalid foreign keys; "
                    f"missing parent(s): {', '.join(sorted(missing_parents))}"
                )

        missing_triggers = {
            "transcript_segments_ai",
            "transcript_segments_ad",
            "transcript_segments_au",
        } - self._objects_by_type(conn, "trigger")
        if missing_triggers:
            raise RuntimeError(
                "Database schema is missing FTS triggers: "
                + ", ".join(sorted(missing_triggers))
            )

        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            first_errors = [dict(row) for row in fk_errors[:5]]
            raise RuntimeError(
                "Database foreign key check failed: "
                + json.dumps(first_errors, ensure_ascii=False)
            )

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _foreign_key_parents(conn: sqlite3.Connection, table_name: str) -> set[str]:
        rows = conn.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
        return {row["table"] for row in rows}

    @staticmethod
    def _objects_by_type(conn: sqlite3.Connection, object_type: str) -> set[str]:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = ?",
            (object_type,),
        ).fetchall()
        return {row["name"] for row in rows}

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a database connection with proper settings."""
        conn = sqlite3.connect(
            str(self.db_path),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Recording operations
    def create_recording(self, recording: Recording) -> int:
        """Create a new recording entry."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO recordings (title, audio_path, duration_seconds, status)
                VALUES (?, ?, ?, ?)
                """,
                (
                    recording.title,
                    recording.audio_path,
                    recording.duration_seconds,
                    recording.status,
                ),
            )
            recording_id = cursor.lastrowid
            logger.debug(f"Created recording with id={recording_id}")
            return recording_id

    def get_recording(self, recording_id: int) -> Optional[Recording]:
        """Get a recording by ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
            if row:
                return Recording(**dict(row))
            return None

    def get_all_recordings(self, limit: int = 100, offset: int = 0) -> list[Recording]:
        """Get all recordings, ordered by creation date."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM recordings
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            return [Recording(**dict(row)) for row in rows]

    def get_recordings_by_statuses(self, statuses: list[str]) -> list[Recording]:
        """Get recordings that currently have one of the given statuses."""
        if not statuses:
            return []

        placeholders = ", ".join("?" for _ in statuses)
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM recordings
                WHERE status IN ({placeholders})
                ORDER BY created_at DESC
                """,
                tuple(statuses),
            ).fetchall()
            return [Recording(**dict(row)) for row in rows]

    def update_recording_status(self, recording_id: int, status: str) -> bool:
        """Update recording status."""
        if status not in RECORDING_STATUSES:
            raise ValueError(f"Invalid recording status: {status}")
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE recordings SET status = ? WHERE id = ?",
                (status, recording_id),
            )
            return cursor.rowcount > 0

    # Processing queue operations
    def create_processing_job(
        self,
        recording_id: int,
        job_type: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> int:
        """Create a durable processing job or return an equivalent queued job."""
        if job_type not in PROCESSING_JOB_TYPES:
            raise ValueError(f"Invalid processing job type: {job_type}")

        payload_json = json.dumps(payload) if payload else None
        with self._get_connection() as conn:
            existing = conn.execute(
                """
                SELECT id
                FROM processing_jobs
                WHERE recording_id = ?
                  AND job_type = ?
                  AND status IN ('queued', 'running')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (recording_id, job_type),
            ).fetchone()
            if existing:
                return int(existing["id"])

            cursor = conn.execute(
                """
                INSERT INTO processing_jobs (recording_id, job_type, payload)
                VALUES (?, ?, ?)
                """,
                (recording_id, job_type, payload_json),
            )
            return cursor.lastrowid

    def get_next_processing_job(self) -> Optional[ProcessingJob]:
        """Return the oldest queued processing job."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM processing_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """
            ).fetchone()
            return self._processing_job_from_row(row)

    def get_processing_job(self, job_id: int) -> Optional[ProcessingJob]:
        """Return a processing job by id."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM processing_jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
            return self._processing_job_from_row(row)

    def get_latest_processing_job_for_recording(
        self,
        recording_id: int,
    ) -> Optional[ProcessingJob]:
        """Return the newest processing job for a recording."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM processing_jobs
                WHERE recording_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (recording_id,),
            ).fetchone()
            return self._processing_job_from_row(row)

    def get_active_processing_jobs(self) -> list[ProcessingJob]:
        """Return queued/running jobs for startup recovery and diagnostics."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM processing_jobs
                WHERE status IN ('queued', 'running')
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()
            return [job for row in rows if (job := self._processing_job_from_row(row))]

    def update_processing_job_status(
        self,
        job_id: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> bool:
        """Update processing job status and lifecycle timestamps."""
        if status not in PROCESSING_JOB_STATUSES:
            raise ValueError(f"Invalid processing job status: {status}")

        started_at_expr = "CURRENT_TIMESTAMP" if status == "running" else "started_at"
        completed_at_expr = (
            "CURRENT_TIMESTAMP" if status in {"completed", "failed"} else "completed_at"
        )
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""
                UPDATE processing_jobs
                SET status = ?,
                    error_message = ?,
                    attempts = attempts + CASE WHEN ? = 'running' THEN 1 ELSE 0 END,
                    updated_at = CURRENT_TIMESTAMP,
                    started_at = {started_at_expr},
                    completed_at = {completed_at_expr}
                WHERE id = ?
                """,
                (status, error_message, status, job_id),
            )
            return cursor.rowcount > 0

    def update_processing_job_payload(
        self,
        job_id: int,
        payload_update: dict[str, Any],
    ) -> bool:
        """Merge a small payload update into a processing job and refresh heartbeat."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT payload FROM processing_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not row:
                return False

            payload = self._payload_from_value(row["payload"])
            payload = self._deep_merge_payload(payload, payload_update)
            cursor = conn.execute(
                """
                UPDATE processing_jobs
                SET payload = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (json.dumps(payload, ensure_ascii=False), job_id),
            )
            return cursor.rowcount > 0

    def touch_processing_job(
        self,
        job_id: int,
        payload_update: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Refresh a processing job heartbeat, optionally with a payload update."""
        if payload_update:
            return self.update_processing_job_payload(job_id, payload_update)

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE processing_jobs
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (job_id,),
            )
            return cursor.rowcount > 0

    def requeue_running_processing_jobs(self) -> int:
        """Move jobs left running by a previous shutdown back to queued."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE processing_jobs
                SET status = 'queued',
                    updated_at = CURRENT_TIMESTAMP,
                    error_message = NULL
                WHERE status = 'running'
                """
            )
            return cursor.rowcount

    def get_stale_running_processing_jobs(
        self,
        stale_after_seconds: int,
    ) -> list[ProcessingJob]:
        """Return running jobs whose heartbeat has not moved recently."""
        threshold = f"-{max(1, int(stale_after_seconds))} seconds"
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM processing_jobs
                WHERE status = 'running'
                  AND COALESCE(updated_at, started_at, created_at)
                      <= datetime('now', ?)
                ORDER BY updated_at ASC, id ASC
                """,
                (threshold,),
            ).fetchall()
            return [job for row in rows if (job := self._processing_job_from_row(row))]

    def requeue_processing_job(
        self,
        job_id: int,
        error_message: Optional[str] = None,
    ) -> bool:
        """Move one processing job back to queued for a future retry."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE processing_jobs
                SET status = 'queued',
                    error_message = ?,
                    updated_at = CURRENT_TIMESTAMP,
                    started_at = NULL,
                    completed_at = NULL
                WHERE id = ?
                  AND status IN ('queued', 'running')
                """,
                (error_message, job_id),
            )
            return cursor.rowcount > 0

    def fail_processing_jobs_for_recording(
        self,
        recording_id: int,
        error_message: str,
    ) -> int:
        """Fail queued/running jobs for a recording."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE processing_jobs
                SET status = 'failed',
                    error_message = ?,
                    updated_at = CURRENT_TIMESTAMP,
                    completed_at = CURRENT_TIMESTAMP
                WHERE recording_id = ?
                  AND status IN ('queued', 'running')
                """,
                (error_message, recording_id),
            )
            return cursor.rowcount

    def _processing_job_from_row(
        self,
        row: Optional[sqlite3.Row],
    ) -> Optional[ProcessingJob]:
        if not row:
            return None

        data = dict(row)
        if data.get("payload"):
            data["payload"] = self._payload_from_value(data["payload"])
        return ProcessingJob(**data)

    @staticmethod
    def _payload_from_value(value: Optional[str]) -> dict[str, Any]:
        if not value:
            return {}
        try:
            payload = json.loads(value)
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}

    @classmethod
    def _deep_merge_payload(
        cls,
        base: dict[str, Any],
        update: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(base)
        for key, value in update.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = cls._deep_merge_payload(merged[key], value)
            else:
                merged[key] = value
        return merged

    def update_recording_duration(self, recording_id: int, duration: int) -> bool:
        """Update recording duration."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE recordings SET duration_seconds = ? WHERE id = ?",
                (duration, recording_id),
            )
            return cursor.rowcount > 0

    def update_recording_title(self, recording_id: int, title: str) -> bool:
        """Update recording title."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE recordings SET title = ? WHERE id = ?",
                (title, recording_id),
            )
            return cursor.rowcount > 0

    def delete_recording(self, recording_id: int) -> bool:
        """Delete a recording and all associated data."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM recordings WHERE id = ?", (recording_id,)
            )
            return cursor.rowcount > 0

    # Transcript operations
    def create_transcript(self, transcript: Transcript) -> int:
        """Create a new transcript."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO transcripts (recording_id, full_text, language)
                VALUES (?, ?, ?)
                """,
                (transcript.recording_id, transcript.full_text, transcript.language),
            )
            return cursor.lastrowid

    def get_transcript(self, recording_id: int) -> Optional[Transcript]:
        """Get transcript for a recording."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM transcripts WHERE recording_id = ?", (recording_id,)
            ).fetchone()
            if row:
                return Transcript(**dict(row))
            return None

    def update_transcript_text(
        self, transcript_id: int, full_text: str, language: str
    ) -> bool:
        """Update transcript full text."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE transcripts SET full_text = ?, language = ? WHERE id = ?",
                (full_text, language, transcript_id),
            )
            return cursor.rowcount > 0

    # Segment operations
    def add_segments(self, segments: list[TranscriptSegment]) -> int:
        """Add multiple transcript segments."""
        if not segments:
            return 0
        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO transcript_segments (transcript_id, speaker, speaker_name, start_time, end_time, text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        s.transcript_id,
                        s.speaker,
                        s.speaker_name,
                        s.start_time,
                        s.end_time,
                        s.text,
                    )
                    for s in segments
                ],
            )
            return len(segments)

    def update_segment_speaker_names(
        self, transcript_id: int, speaker_names: dict[str, str]
    ) -> int:
        """Update display names for all segments of the given transcript."""
        if not speaker_names:
            return 0

        updated = 0
        with self._get_connection() as conn:
            for speaker, name in speaker_names.items():
                cursor = conn.execute(
                    """
                    UPDATE transcript_segments
                    SET speaker_name = ?
                    WHERE transcript_id = ? AND speaker = ?
                    """,
                    (name, transcript_id, speaker),
                )
                updated += cursor.rowcount
        return updated

    def get_segments(self, transcript_id: int) -> list[TranscriptSegment]:
        """Get all segments for a transcript."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM transcript_segments
                WHERE transcript_id = ?
                ORDER BY start_time
                """,
                (transcript_id,),
            ).fetchall()
            return [TranscriptSegment(**dict(row)) for row in rows]

    # Summary operations
    def create_summary(self, summary: Summary) -> int:
        """Create or update a summary for a recording."""
        key_points_json = json.dumps(summary.key_points) if summary.key_points else None
        decisions_json = json.dumps(summary.decisions) if summary.decisions else None
        action_items_json = (
            json.dumps(summary.action_items) if summary.action_items else None
        )

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO summaries (recording_id, summary, key_points, decisions, action_items)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(recording_id) DO UPDATE SET
                    summary = excluded.summary,
                    key_points = excluded.key_points,
                    decisions = excluded.decisions,
                    action_items = excluded.action_items,
                    created_at = CURRENT_TIMESTAMP
                """,
                (
                    summary.recording_id,
                    summary.summary,
                    key_points_json,
                    decisions_json,
                    action_items_json,
                ),
            )
            return cursor.lastrowid

    def get_summary(self, recording_id: int) -> Optional[Summary]:
        """Get summary for a recording."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM summaries WHERE recording_id = ?", (recording_id,)
            ).fetchone()
            if row:
                data = dict(row)
                if data.get("key_points"):
                    data["key_points"] = json.loads(data["key_points"])
                if data.get("decisions"):
                    data["decisions"] = json.loads(data["decisions"])
                if data.get("action_items"):
                    data["action_items"] = json.loads(data["action_items"])
                return Summary(**data)
            return None

    def delete_transcript(self, transcript_id: int) -> bool:
        """Delete a transcript and its segments."""
        with self._get_connection() as conn:
            # Delete segments first
            conn.execute(
                "DELETE FROM transcript_segments WHERE transcript_id = ?",
                (transcript_id,),
            )
            # Delete transcript
            cursor = conn.execute(
                "DELETE FROM transcripts WHERE id = ?", (transcript_id,)
            )
            return cursor.rowcount > 0

    def delete_summary(self, summary_id: int) -> bool:
        """Delete a summary."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM summaries WHERE id = ?", (summary_id,)
            )
            return cursor.rowcount > 0

    # Search operations
    def search_transcripts(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """
        Full-text search across all transcripts.

        Returns list of dicts with recording info and matching segments.
        """
        fts_query = self._build_fts_query(query)
        if not fts_query:
            return []

        with self._get_connection() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT
                        r.id as recording_id,
                        r.title,
                        r.created_at,
                        COALESCE(ts.speaker_name, ts.speaker) as speaker,
                        ts.start_time,
                        ts.end_time,
                        ts.text,
                        highlight(transcript_fts, 0, '<mark>', '</mark>') as highlighted_text
                    FROM transcript_fts
                    JOIN transcript_segments ts ON transcript_fts.rowid = ts.id
                    JOIN transcripts t ON ts.transcript_id = t.id
                    JOIN recordings r ON t.recording_id = r.id
                    WHERE transcript_fts MATCH ?
                    ORDER BY r.created_at DESC
                    LIMIT ?
                    """,
                    (fts_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                like_query = f"%{query}%"
                rows = conn.execute(
                    """
                    SELECT
                        r.id as recording_id,
                        r.title,
                        r.created_at,
                        COALESCE(ts.speaker_name, ts.speaker) as speaker,
                        ts.start_time,
                        ts.end_time,
                        ts.text,
                        ts.text as highlighted_text
                    FROM transcript_segments ts
                    JOIN transcripts t ON ts.transcript_id = t.id
                    JOIN recordings r ON t.recording_id = r.id
                    WHERE ts.text LIKE ?
                    ORDER BY r.created_at DESC
                    LIMIT ?
                    """,
                    (like_query, limit),
                ).fetchall()
            return [dict(row) for row in rows]

    def search_recordings(self, query: str, limit: int = 50) -> list[Recording]:
        """Search recordings by title or full transcript text."""
        query = query.strip()
        if not query:
            return []

        like_query = f"%{query}%"
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT r.*
                FROM recordings r
                LEFT JOIN transcripts t ON t.recording_id = r.id
                WHERE r.title LIKE ? OR t.full_text LIKE ?
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (like_query, like_query, limit),
            ).fetchall()
            return [Recording(**dict(row)) for row in rows]

    @staticmethod
    def _build_fts_query(query: str) -> str:
        """Build a safe FTS5 prefix query from user input."""
        tokens = re.findall(r"[\w]+", query, flags=re.UNICODE)
        return " ".join(f"{token}*" for token in tokens)


# Global database instance
_db: Optional[Database] = None


def get_database() -> Database:
    """Get or create global database instance."""
    global _db
    if _db is None:
        from src.utils.config import get_settings

        settings = get_settings()
        _db = Database(settings.database_path)
    return _db


def reset_database() -> Database:
    """Reset database instance (for testing)."""
    global _db
    _db = None
    return get_database()
