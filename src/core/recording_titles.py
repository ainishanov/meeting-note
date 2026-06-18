"""Deterministic recording title and file-name helpers."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional


LEGACY_TITLE_PREFIX = "Запись "
GENERATED_TITLE_RE = re.compile(
    r"^(?P<date>\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})\s+[—-]\s+.+$"
)


def coerce_datetime(value: Any) -> Optional[datetime]:
    """Return a datetime for DB/Pydantic values when possible."""
    if isinstance(value, datetime):
        return value
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def format_recording_title(created_at: Any = None) -> str:
    """Format the user-facing recording title from date and time only."""
    recorded_at = coerce_datetime(created_at) or datetime.now()
    return recorded_at.strftime("%d.%m.%Y %H:%M")


def is_auto_generated_title(title: str | None) -> bool:
    """Return whether a title is one of the app-generated legacy/AI titles."""
    value = (title or "").strip()
    return (
        not value
        or value.startswith(LEGACY_TITLE_PREFIX)
        or bool(GENERATED_TITLE_RE.match(value))
    )


def display_recording_title(recording: Any) -> str:
    """Return the title shown in UI/export content."""
    title = (getattr(recording, "title", "") or "").strip()
    created_at = getattr(recording, "created_at", None)

    if is_auto_generated_title(title):
        recorded_at = coerce_datetime(created_at)
        if recorded_at:
            return format_recording_title(recorded_at)

        generated_match = GENERATED_TITLE_RE.match(title)
        if generated_match:
            return generated_match.group("date")

        if title.startswith(LEGACY_TITLE_PREFIX):
            legacy_date = title[len(LEGACY_TITLE_PREFIX) :].strip()
            if legacy_date:
                return legacy_date

    return title or format_recording_title(created_at)


def recording_file_stem(recording: Any) -> str:
    """Return a deterministic export file stem without AI-generated text."""
    created_at = coerce_datetime(getattr(recording, "created_at", None))
    timestamp = created_at.strftime("%d_%m_%Y %H_%M") if created_at else "recording"

    recording_id = getattr(recording, "id", None)
    if recording_id is not None:
        return f"{recording_id}_{timestamp}"
    return timestamp
