"""Deterministic recording title and file-name helpers."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional


LEGACY_TITLE_PREFIX = "Запись "
DATE_ONLY_TITLE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}$")
GENERATED_TITLE_RE = re.compile(
    r"^(?P<date>\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})\s+[—-]\s+(?P<semantic>.+)$"
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
        or bool(DATE_ONLY_TITLE_RE.match(value))
        or bool(GENERATED_TITLE_RE.match(value))
    )


def sanitize_semantic_title(value: str | None, max_length: int = 72) -> str:
    """Return a compact, single-line title suitable for meeting history."""
    title = re.sub(r"\s+", " ", (value or "").strip())
    title = re.sub(r"^[\s•*#\-–—✓☐]+", "", title).strip(' "\'')
    title = re.sub(r"[.!?,;:]+$", "", title).strip()
    if not title or DATE_ONLY_TITLE_RE.match(title):
        return ""

    if len(title) <= max_length:
        return title

    shortened = title[: max_length + 1]
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    return shortened.rstrip(" -–—,.;:") + "…"


def semantic_title_from_summary(summary: Any) -> str:
    """Derive a useful local fallback title from an existing summary."""
    if summary is None:
        return ""

    key_points = getattr(summary, "key_points", None) or []
    for point in key_points:
        title = sanitize_semantic_title(str(point))
        if title:
            return title

    summary_text = re.sub(r"\s+", " ", str(getattr(summary, "summary", "") or "")).strip()
    if not summary_text:
        return ""
    first_sentence = re.split(r"(?<=[.!?])\s+", summary_text, maxsplit=1)[0]
    return sanitize_semantic_title(first_sentence)


def display_recording_title(recording: Any) -> str:
    """Return the title shown in UI/export content."""
    title = (getattr(recording, "title", "") or "").strip()
    created_at = getattr(recording, "created_at", None)

    if is_auto_generated_title(title):
        generated_match = GENERATED_TITLE_RE.match(title)
        if generated_match:
            semantic = sanitize_semantic_title(generated_match.group("semantic"))
            if semantic:
                return semantic

        recorded_at = coerce_datetime(created_at)
        if recorded_at:
            return format_recording_title(recorded_at)

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
