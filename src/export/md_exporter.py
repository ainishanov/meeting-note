"""Markdown export for transcripts."""

from pathlib import Path
from typing import Optional

from src.core.database import Recording, Summary, Transcript, TranscriptSegment
from src.core.recording_titles import display_recording_title


def _escape_md(text: object) -> str:
    """Escape user text for Markdown output."""
    value = "" if text is None else str(text)
    return (
        value
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("`", "\\`")
        .replace("#", "\\#")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("<", "\\<")
        .replace(">", "\\>")
    )


def export_markdown(
    recording: Recording,
    transcript: Optional[Transcript],
    segments: list[TranscriptSegment],
    summary: Optional[Summary],
    output_path: Path,
) -> None:
    """
    Export transcript to Markdown file.

    Args:
        recording: Recording data
        transcript: Transcript data
        segments: List of transcript segments
        summary: Summary data
        output_path: Path to output file
    """
    lines = []

    # Title
    lines.append(f"# {_escape_md(display_recording_title(recording))}")
    lines.append("")

    # Info table
    lines.append("| Параметр | Значение |")
    lines.append("|----------|----------|")

    if recording.created_at:
        if isinstance(recording.created_at, str):
            date_str = recording.created_at
        else:
            date_str = recording.created_at.strftime("%d.%m.%Y %H:%M")
        lines.append(f"| Дата | {_escape_md(date_str)} |")

    if recording.duration_seconds:
        minutes = recording.duration_seconds // 60
        seconds = recording.duration_seconds % 60
        lines.append(f"| Длительность | {minutes}:{seconds:02d} |")

    if transcript and transcript.language:
        lang_names = {"ru": "Русский", "en": "English"}
        lang = lang_names.get(transcript.language, transcript.language)
        lines.append(f"| Язык | {_escape_md(lang)} |")

    lines.append("")

    # Summary section
    if summary:
        lines.append("## Краткое содержание")
        lines.append("")

        if summary.summary:
            lines.append(_escape_md(summary.summary))
            lines.append("")

        if summary.key_points:
            lines.append("### Ключевые темы")
            lines.append("")
            for point in summary.key_points:
                lines.append(f"- {_escape_md(point)}")
            lines.append("")

        if summary.decisions:
            lines.append("### Принятые решения")
            lines.append("")
            for decision in summary.decisions:
                lines.append(f"- {_escape_md(decision)}")
            lines.append("")

        if summary.action_items:
            lines.append("### Задачи")
            lines.append("")
            for item in summary.action_items:
                lines.append(f"- [ ] {_escape_md(item)}")
            lines.append("")

    # Transcript section
    lines.append("## Транскрипт")
    lines.append("")

    if segments:
        current_speaker = None
        for seg in segments:
            speaker_label = seg.display_speaker
            if speaker_label != current_speaker:
                current_speaker = speaker_label
                lines.append("")
                lines.append(f"**{_escape_md(speaker_label)}:**")
                lines.append("")

            # Format timestamp
            start_min = int(seg.start_time // 60)
            start_sec = int(seg.start_time % 60)
            timestamp = f"`[{start_min}:{start_sec:02d}]`"

            lines.append(f"> {timestamp} {_escape_md(seg.text)}")
    elif transcript and transcript.full_text:
        lines.append(_escape_md(transcript.full_text))
    else:
        lines.append("*Транскрипт отсутствует*")

    lines.append("")
    lines.append("---")
    lines.append("*Сгенерировано Meeting Note*")

    # Write file
    output_path.write_text("\n".join(lines), encoding="utf-8")
