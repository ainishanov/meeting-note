"""Plain text export for transcripts."""

from pathlib import Path
from typing import Optional

from src.core.database import Recording, Summary, Transcript, TranscriptSegment
from src.core.recording_titles import display_recording_title


def export_txt(
    recording: Recording,
    transcript: Optional[Transcript],
    segments: list[TranscriptSegment],
    summary: Optional[Summary],
    output_path: Path,
) -> None:
    """
    Export transcript to plain text file.

    Args:
        recording: Recording data
        transcript: Transcript data
        segments: List of transcript segments
        summary: Summary data
        output_path: Path to output file
    """
    lines = []

    # Header
    lines.append("=" * 60)
    lines.append(f"ЗАПИСЬ: {display_recording_title(recording)}")
    lines.append("=" * 60)
    lines.append("")

    # Info
    if recording.created_at:
        if isinstance(recording.created_at, str):
            date_str = recording.created_at
        else:
            date_str = recording.created_at.strftime("%d.%m.%Y %H:%M")
        lines.append(f"Дата: {date_str}")

    if recording.duration_seconds:
        minutes = recording.duration_seconds // 60
        seconds = recording.duration_seconds % 60
        lines.append(f"Длительность: {minutes}:{seconds:02d}")

    if transcript and transcript.language:
        lines.append(f"Язык: {transcript.language}")

    lines.append("")

    # Summary section
    if summary:
        lines.append("-" * 60)
        lines.append("КРАТКОЕ СОДЕРЖАНИЕ")
        lines.append("-" * 60)
        lines.append("")

        if summary.summary:
            lines.append(summary.summary)
            lines.append("")

        if summary.key_points:
            lines.append("Ключевые темы:")
            for point in summary.key_points:
                lines.append(f"  • {point}")
            lines.append("")

        if summary.decisions:
            lines.append("Принятые решения:")
            for decision in summary.decisions:
                lines.append(f"  ✓ {decision}")
            lines.append("")

        if summary.action_items:
            lines.append("Задачи:")
            for item in summary.action_items:
                lines.append(f"  □ {item}")
            lines.append("")

    # Transcript section
    lines.append("-" * 60)
    lines.append("ТРАНСКРИПТ")
    lines.append("-" * 60)
    lines.append("")

    if segments:
        current_speaker = None
        for seg in segments:
            speaker_label = seg.display_speaker
            if speaker_label != current_speaker:
                current_speaker = speaker_label
                lines.append("")
                lines.append(f"[{speaker_label}]")

            # Format timestamp
            start_min = int(seg.start_time // 60)
            start_sec = int(seg.start_time % 60)
            timestamp = f"[{start_min}:{start_sec:02d}]"

            lines.append(f"  {timestamp} {seg.text}")
    elif transcript and transcript.full_text:
        lines.append(transcript.full_text)
    else:
        lines.append("(Транскрипт отсутствует)")

    lines.append("")
    lines.append("=" * 60)
    lines.append("Сгенерировано Meeting Note")
    lines.append("=" * 60)

    # Write file
    output_path.write_text("\n".join(lines), encoding="utf-8")
