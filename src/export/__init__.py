"""Export functionality for transcripts."""

from pathlib import Path
from typing import Optional

from src.core.database import Recording, Summary, Transcript, TranscriptSegment
from src.core.recording_titles import recording_file_stem
from src.export.txt_exporter import export_txt
from src.export.md_exporter import export_markdown
from src.export.docx_exporter import export_docx


def export_transcript(
    recording: Recording,
    transcript: Optional[Transcript],
    segments: list[TranscriptSegment],
    summary: Optional[Summary],
    format_type: str,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    Export transcript to specified format.

    Args:
        recording: Recording data
        transcript: Transcript data (optional)
        segments: List of transcript segments
        summary: Summary data (optional)
        format_type: Export format ("txt", "md", "docx")
        output_dir: Output directory (default: user's Documents)

    Returns:
        Path to exported file
    """
    if output_dir is None:
        output_dir = Path.home() / "Documents" / "MeetingNote"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_title = recording_file_stem(recording)

    if format_type == "txt":
        filename = f"{safe_title}.txt"
        output_path = output_dir / filename
        export_txt(recording, transcript, segments, summary, output_path)
    elif format_type == "md":
        filename = f"{safe_title}.md"
        output_path = output_dir / filename
        export_markdown(recording, transcript, segments, summary, output_path)
    elif format_type == "docx":
        filename = f"{safe_title}.docx"
        output_path = output_dir / filename
        export_docx(recording, transcript, segments, summary, output_path)
    else:
        raise ValueError(f"Unknown format: {format_type}")

    return output_path
