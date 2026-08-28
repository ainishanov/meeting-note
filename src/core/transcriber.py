"""OpenAI GPT-4o Transcribe API integration with speaker diarization."""

import asyncio
import base64
import io
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger
from openai import OpenAI
from pydub import AudioSegment

from src.core.database import TranscriptSegment


# Known Whisper hallucination patterns (case-insensitive)
HALLUCINATION_PATTERNS = [
    r"редактор субтитров",
    r"корректор\s+[а-яё]\.",
    r"субтитры\s+(сделал|создал|подготовил)",
    r"thank you for watching",
    r"thanks for watching",
    r"please subscribe",
    r"like and subscribe",
    r"don't forget to subscribe",
    r"see you in the next",
    r"subtitles by",
    r"captions by",
    r"transcribed by",
    r"амара\.орг",
    r"amara\.org",
]

# Compiled patterns for efficiency
_HALLUCINATION_RE = re.compile(
    "|".join(HALLUCINATION_PATTERNS), re.IGNORECASE | re.UNICODE
)


@dataclass
class TranscriptionResult:
    """Result of audio transcription."""

    full_text: str
    language: str
    segments: list[TranscriptSegment]
    duration_seconds: float


class Transcriber:
    """
    Audio transcription using OpenAI GPT-4o Transcribe API.

    Features:
    - Automatic language detection (Russian/English)
    - Speaker diarization
    - Chunking for long audio files
    - Silent chunk detection to prevent hallucinations
    - Hallucination filtering
    """

    # The Transcriptions API accepts files up to 25 MB.
    MAX_FILE_SIZE_MB = 25
    # Keep each upload small enough to survive slow or unstable connections.
    # Two minutes of 16 kHz mono PCM is about 3.7 MiB; larger real-world chunks
    # repeatedly lost the connection before diarization returned a response.
    MAX_CHUNK_DURATION = 120  # 2 minutes
    # Minimum RMS level for audio to be considered non-silent
    # Values below this threshold are likely silence or very quiet noise
    MIN_RMS_THRESHOLD = 500
    # Ratio of hallucination text to total text that triggers filtering
    HALLUCINATION_RATIO_THRESHOLD = 0.5
    DEFAULT_MODEL = "gpt-4o-mini-transcribe"
    DIARIZE_MODEL = "gpt-4o-transcribe-diarize"
    WHISPER_MODEL = "whisper-1"
    DIARIZATION_PIPELINE_VERSION = 2
    MAX_KNOWN_SPEAKERS = 4
    MIN_SPEAKER_REFERENCE_SECONDS = 2.0
    TARGET_SPEAKER_REFERENCE_SECONDS = 4.0
    MAX_SPEAKER_REFERENCE_SECONDS = 10.0
    MAX_SHORT_UNKNOWN_SECONDS = MIN_SPEAKER_REFERENCE_SECONDS

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize transcriber.

        Args:
            api_key: OpenAI API key (uses secure storage if not provided)
        """
        self._api_key = api_key
        self._client: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        """Get or create OpenAI client."""
        if self._client is None:
            api_key = self._api_key
            if not api_key:
                from src.utils.security import get_openai_api_key

                api_key = get_openai_api_key()

            if not api_key:
                raise ValueError(
                    "OpenAI API key not configured. "
                    "Set OPENAI_API_KEY environment variable or configure in settings."
                )

            # Retry here, where chunk progress and durable cache state are known.
            # The SDK otherwise retries inside every application-level attempt,
            # making one failed chunk appear frozen for several minutes.
            self._client = OpenAI(api_key=api_key, max_retries=0)

        return self._client

    def _get_audio_rms(self, audio_segment: AudioSegment) -> float:
        """Calculate RMS (root mean square) level of audio segment."""
        samples = np.array(audio_segment.get_array_of_samples(), dtype=np.float32)
        if len(samples) == 0:
            return 0.0
        return float(np.sqrt(np.mean(samples**2)))

    def _is_silent_chunk(self, audio_segment: AudioSegment) -> bool:
        """Check if audio chunk is silent or too quiet for transcription."""
        rms = self._get_audio_rms(audio_segment)
        is_silent = rms < self.MIN_RMS_THRESHOLD
        if is_silent:
            logger.debug(f"Silent chunk detected: RMS={rms:.1f} < {self.MIN_RMS_THRESHOLD}")
        return is_silent

    def _is_hallucination(self, text: str) -> bool:
        """Check if text matches known Whisper hallucination patterns."""
        if not text or len(text.strip()) < 10:
            return False
        return bool(_HALLUCINATION_RE.search(text))

    def _filter_hallucinations(self, text: str) -> str:
        """Remove hallucination patterns from text."""
        if not text:
            return text

        lines = text.split("\n")
        filtered_lines = []

        for line in lines:
            if not self._is_hallucination(line):
                filtered_lines.append(line)
            else:
                logger.debug(f"Filtered hallucination: {line[:50]}...")

        return "\n".join(filtered_lines)

    def _detect_repetitive_text(self, text: str, min_repeats: int = 3) -> bool:
        """Detect if text contains excessive repetition (sign of hallucination)."""
        if not text or len(text) < 50:
            return False

        # Split into sentences/phrases
        phrases = re.split(r'[.!?]\s*', text)
        phrases = [p.strip().lower() for p in phrases if len(p.strip()) > 10]

        if len(phrases) < min_repeats:
            return False

        # Count phrase occurrences
        counter = Counter(phrases)
        most_common = counter.most_common(1)

        if most_common:
            phrase, count = most_common[0]
            # If any phrase repeats more than min_repeats times, it's likely hallucination
            if count >= min_repeats:
                logger.debug(f"Repetitive text detected: '{phrase[:30]}...' x{count}")
                return True

        return False

    def _clean_transcription(self, text: str, segments: list) -> tuple[str, list]:
        """Clean transcription by removing hallucinations and repetitive text."""
        # Filter hallucination patterns
        cleaned_text = self._filter_hallucinations(text)

        # Check for repetitive text (whole transcription is likely garbage)
        if self._detect_repetitive_text(cleaned_text):
            logger.warning("Transcription appears to be mostly repetitive hallucination")
            # Keep only non-repetitive parts
            sentences = re.split(r'([.!?]\s*)', cleaned_text)
            seen = set()
            unique_parts = []
            for i in range(0, len(sentences) - 1, 2):
                sentence = sentences[i].strip().lower()
                if sentence and sentence not in seen:
                    seen.add(sentence)
                    unique_parts.append(sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else ""))
            cleaned_text = "".join(unique_parts)

        # Filter segments that are hallucinations
        cleaned_segments = [
            seg for seg in segments
            if not self._is_hallucination(seg.text)
        ]

        return cleaned_text.strip(), cleaned_segments

    def _get_attr(self, value, name: str, default=None):
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    def _sanitize_speaker_label(self, speaker) -> Optional[str]:
        """Keep only useful speaker labels returned by transcription models."""
        if speaker is None:
            return None

        label = str(speaker).strip()
        if not label or not any(char.isalnum() for char in label):
            return None

        label = re.sub(r"\s+", " ", label)
        return label[:60]

    def _normalize_global_speaker_labels(
        self, segments: list[TranscriptSegment]
    ) -> None:
        """Rename one request's stable A/B labels in first-seen order."""
        speaker_map: dict[str, str] = {}
        for segment in segments:
            if not segment.speaker:
                continue
            if segment.speaker not in speaker_map:
                speaker_map[segment.speaker] = f"Speaker {len(speaker_map) + 1}"
            segment.speaker = speaker_map[segment.speaker]

    def _speaker_display_name(self, api_name: str) -> str:
        match = re.fullmatch(r"speaker_(\d+)", api_name)
        if match:
            return f"Speaker {match.group(1)}"
        return api_name

    def _speaker_api_name(self, display_name: str) -> str:
        match = re.fullmatch(r"Speaker (\d+)", display_name)
        if match:
            return f"speaker_{match.group(1)}"
        return display_name

    def _build_speaker_reference(
        self,
        chunk: AudioSegment,
        segments: list[TranscriptSegment],
        local_speaker: str,
        chunk_start_seconds: float,
    ) -> str:
        """Create a 2-10 second WAV data URL containing one enrolled voice."""
        matching_segments = [
            segment
            for segment in segments
            if segment.speaker == local_speaker
        ]
        matching_segments.sort(
            key=lambda segment: segment.end_time - segment.start_time,
            reverse=True,
        )

        max_duration_ms = int(self.MAX_SPEAKER_REFERENCE_SECONDS * 1000)
        min_duration_ms = int(self.MIN_SPEAKER_REFERENCE_SECONDS * 1000)
        target_duration_ms = int(self.TARGET_SPEAKER_REFERENCE_SECONDS * 1000)
        reference = AudioSegment.empty()
        for segment in matching_segments:
            start_ms = max(
                0,
                int((segment.start_time - chunk_start_seconds) * 1000),
            )
            end_ms = min(
                len(chunk),
                int((segment.end_time - chunk_start_seconds) * 1000),
            )
            if end_ms <= start_ms:
                continue
            segment_duration_ms = end_ms - start_ms
            if segment_duration_ms >= min_duration_ms:
                extract_duration_ms = min(
                    target_duration_ms,
                    segment_duration_ms,
                )
                midpoint_ms = (start_ms + end_ms) // 2
                extract_start_ms = max(
                    start_ms,
                    midpoint_ms - extract_duration_ms // 2,
                )
                extract_end_ms = min(
                    end_ms,
                    extract_start_ms + extract_duration_ms,
                )
                reference = chunk[extract_start_ms:extract_end_ms]
                break

            remaining_ms = min(target_duration_ms, max_duration_ms) - len(reference)
            if remaining_ms <= 0:
                break
            reference += chunk[start_ms : min(end_ms, start_ms + remaining_ms)]
            if len(reference) >= min_duration_ms:
                break

        if not reference:
            raise RuntimeError(
                f"Could not create an audio reference for speaker {local_speaker}"
            )

        if len(reference) < min_duration_ms:
            reference += AudioSegment.silent(
                duration=min_duration_ms - len(reference),
                frame_rate=reference.frame_rate,
            )

        reference = (
            reference[:max_duration_ms]
            .set_channels(1)
            .set_frame_rate(16000)
            .set_sample_width(2)
        )
        buffer = io.BytesIO()
        reference.export(buffer, format="wav")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:audio/wav;base64,{encoded}"

    def _unknown_speaker_labels(
        self,
        segments: list[TranscriptSegment],
        speaker_references: dict[str, str],
    ) -> list[str]:
        """Return request-local labels not matched to an enrolled voice."""
        return list(
            dict.fromkeys(
                segment.speaker
                for segment in segments
                if segment.speaker
                and segment.speaker not in speaker_references
            )
        )

    def _resolve_short_unknown_segments(
        self,
        segments: list[TranscriptSegment],
        speaker_references: dict[str, str],
    ) -> None:
        """Attach labels too short for a valid voice sample to a known turn."""
        unknown_labels = self._unknown_speaker_labels(
            segments,
            speaker_references,
        )
        for unknown_label in unknown_labels:
            unknown_indexes = [
                index
                for index, segment in enumerate(segments)
                if segment.speaker == unknown_label
            ]
            total_seconds = sum(
                max(0.0, segments[index].end_time - segments[index].start_time)
                for index in unknown_indexes
            )
            if total_seconds > self.MAX_SHORT_UNKNOWN_SECONDS:
                continue

            for index in unknown_indexes:
                current = segments[index]
                previous = next(
                    (
                        candidate
                        for candidate in reversed(segments[:index])
                        if candidate.speaker in speaker_references
                    ),
                    None,
                )
                following = next(
                    (
                        candidate
                        for candidate in segments[index + 1 :]
                        if candidate.speaker in speaker_references
                    ),
                    None,
                )
                if previous is not None and following is not None:
                    previous_gap = abs(current.start_time - previous.end_time)
                    following_gap = abs(following.start_time - current.end_time)
                    current.speaker = (
                        previous.speaker
                        if previous_gap <= following_gap
                        else following.speaker
                    )
                elif previous is not None:
                    current.speaker = previous.speaker
                elif following is not None:
                    current.speaker = following.speaker

    def _enroll_next_speaker(
        self,
        segments: list[TranscriptSegment],
        chunk: AudioSegment,
        chunk_start_seconds: float,
        speaker_references: dict[str, str],
        replace_api_name: Optional[str] = None,
    ) -> str:
        """Enroll the dominant currently unknown voice for another model pass."""
        unknown_labels = self._unknown_speaker_labels(
            segments,
            speaker_references,
        )
        if not unknown_labels:
            raise RuntimeError("No unknown speaker is available to enroll")
        if (
            replace_api_name is None
            and len(speaker_references) >= self.MAX_KNOWN_SPEAKERS
        ):
            unknown_seconds = {
                label: round(
                    sum(
                        max(0.0, segment.end_time - segment.start_time)
                        for segment in segments
                        if segment.speaker == label
                    ),
                    2,
                )
                for label in unknown_labels
            }
            logger.error(
                f"Unrecognized diarization labels after enrollment: {unknown_seconds}"
            )
            raise RuntimeError(
                "Speaker diarization found an unrecognized voice after "
                f"enrolling {self.MAX_KNOWN_SPEAKERS} speakers. The recording "
                "was preserved; no duplicate speaker labels were saved."
            )

        speaking_seconds = {
            label: sum(
                max(0.0, segment.end_time - segment.start_time)
                for segment in segments
                if segment.speaker == label
            )
            for label in unknown_labels
        }
        local_label = max(unknown_labels, key=speaking_seconds.__getitem__)
        api_name = replace_api_name or f"speaker_{len(speaker_references) + 1}"
        speaker_references[api_name] = self._build_speaker_reference(
            chunk,
            segments,
            local_label,
            chunk_start_seconds,
        )
        return api_name

    def _map_known_speaker_labels(
        self,
        segments: list[TranscriptSegment],
        speaker_references: dict[str, str],
    ) -> None:
        """Convert provider voice-reference IDs to stable display labels."""
        for segment in segments:
            if segment.speaker:
                if segment.speaker not in speaker_references:
                    raise RuntimeError(
                        f"Unrecognized speaker label: {segment.speaker}"
                    )
                segment.speaker = self._speaker_display_name(segment.speaker)

    def _refresh_speaker_references(
        self,
        segments: list[TranscriptSegment],
        chunk: AudioSegment,
        chunk_start_seconds: float,
        speaker_references: dict[str, str],
        reference_chunks: dict[str, int],
        chunk_number: int,
    ) -> None:
        """Keep enrolled voice samples current as the recording progresses."""
        labels = list(
            dict.fromkeys(
                self._speaker_api_name(segment.speaker)
                for segment in segments
                if segment.speaker
            )
        )
        for api_name in labels:
            if api_name not in speaker_references:
                continue
            reference_segments = [
                TranscriptSegment(
                    transcript_id=segment.transcript_id,
                    speaker=api_name,
                    start_time=segment.start_time,
                    end_time=segment.end_time,
                    text=segment.text,
                )
                for segment in segments
                if segment.speaker
                and self._speaker_api_name(segment.speaker) == api_name
            ]
            speaker_references[api_name] = self._build_speaker_reference(
                chunk,
                reference_segments,
                api_name,
                chunk_start_seconds,
            )
            reference_chunks[api_name] = chunk_number

    def _build_transcription_params(
        self,
        model: str,
        file,
        language: Optional[str],
        speaker_references: Optional[dict[str, str]] = None,
    ) -> dict:
        params = {
            "model": model,
            "file": file,
            "language": language,
        }
        if model == self.WHISPER_MODEL:
            params["response_format"] = "verbose_json"
            params["timestamp_granularities"] = ["segment"]
        elif model == self.DIARIZE_MODEL:
            params["response_format"] = "diarized_json"
            params["chunking_strategy"] = "auto"
            if speaker_references:
                params["known_speaker_names"] = list(speaker_references)
                params["known_speaker_references"] = list(
                    speaker_references.values()
                )
        else:
            params["response_format"] = "json"
        return {key: value for key, value in params.items() if value is not None}

    def _response_to_result_parts(
        self,
        response,
        language: Optional[str],
        time_offset: float = 0.0,
        use_heuristic_speakers: bool = False,
    ) -> tuple[str, str, list[TranscriptSegment]]:
        full_text = self._get_attr(response, "text", "") or ""
        detected_language = self._get_attr(response, "language", language or "unknown")
        raw_segments = self._get_attr(response, "segments", []) or []

        segments: list[TranscriptSegment] = []
        for index, segment in enumerate(raw_segments):
            text = (self._get_attr(segment, "text", "") or "").strip()
            if not text:
                continue
            speaker = self._sanitize_speaker_label(
                self._get_attr(segment, "speaker", None)
            )
            if speaker is None and use_heuristic_speakers:
                speaker = self._detect_speaker(segment, index, raw_segments)
            segments.append(
                TranscriptSegment(
                    transcript_id=0,
                    speaker=speaker,
                    start_time=(
                        float(self._get_attr(segment, "start", 0) or 0)
                        + time_offset
                    ),
                    end_time=(
                        float(self._get_attr(segment, "end", 0) or 0)
                        + time_offset
                    ),
                    text=text,
                )
            )

        return full_text, detected_language, segments

    def _request_chunk_transcription(
        self,
        buffer: io.BytesIO,
        model: str,
        language: Optional[str],
        chunk_number: int,
        speaker_references: Optional[dict[str, str]] = None,
    ):
        """Send one bounded chunk with application-owned retry semantics."""
        client = self._get_client()
        max_retries = 3
        for attempt in range(max_retries):
            try:
                buffer.seek(0)
                return client.audio.transcriptions.create(
                    **self._build_transcription_params(
                        model,
                        ("chunk.wav", buffer, "audio/wav"),
                        language,
                        speaker_references=speaker_references,
                    )
                )
            except Exception as e:
                if (
                    self._is_retryable_transcription_error(e)
                    and attempt < max_retries - 1
                ):
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(
                        f"Chunk {chunk_number} attempt {attempt + 1} failed: "
                        f"{e}. Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                    continue
                logger.error(f"Failed to transcribe chunk {chunk_number}: {e}")
                raise

        raise RuntimeError(f"Chunk {chunk_number} returned no response")

    def _transcribe_diarized_chunk(
        self,
        buffer: io.BytesIO,
        chunk: AudioSegment,
        language: Optional[str],
        chunk_start_seconds: float,
        chunk_number: int,
        speaker_references: dict[str, str],
        reference_chunks: dict[str, int],
    ) -> tuple[str, str, list[TranscriptSegment]]:
        """Enroll unknown voices one at a time, then return globally named turns."""
        candidate_names: list[str] = []
        max_classification_passes = self.MAX_KNOWN_SPEAKERS * 3
        for _ in range(max_classification_passes):
            response = self._request_chunk_transcription(
                buffer,
                self.DIARIZE_MODEL,
                language,
                chunk_number,
                speaker_references or None,
            )
            chunk_text, chunk_language, segments = self._response_to_result_parts(
                response,
                language,
                time_offset=chunk_start_seconds,
            )
            if len(speaker_references) >= self.MAX_KNOWN_SPEAKERS:
                self._resolve_short_unknown_segments(
                    segments,
                    speaker_references,
                )
            unknown_labels = self._unknown_speaker_labels(
                segments,
                speaker_references,
            )
            if not unknown_labels:
                self._refresh_speaker_references(
                    segments,
                    chunk,
                    chunk_start_seconds,
                    speaker_references,
                    reference_chunks,
                    chunk_number,
                )
                self._map_known_speaker_labels(segments, speaker_references)
                return chunk_text, chunk_language, segments

            used_known_names = {
                segment.speaker
                for segment in segments
                if segment.speaker in speaker_references
            }
            replace_api_name = next(
                (
                    name
                    for name in candidate_names
                    if name not in used_known_names
                ),
                None,
            )
            if (
                replace_api_name is None
                and len(speaker_references) >= self.MAX_KNOWN_SPEAKERS
            ):
                inactive_names = [
                    name
                    for name in speaker_references
                    if name not in used_known_names
                ]
                if inactive_names:
                    replace_api_name = min(
                        inactive_names,
                        key=lambda name: reference_chunks.get(name, -1),
                    )
            enrolled_name = self._enroll_next_speaker(
                segments,
                chunk,
                chunk_start_seconds,
                speaker_references,
                replace_api_name=replace_api_name,
            )
            reference_chunks[enrolled_name] = chunk_number
            if replace_api_name is None:
                candidate_names.append(enrolled_name)
            logger.info(
                f"{'Refined' if replace_api_name else 'Enrolled'} "
                f"{enrolled_name} from chunk {chunk_number}; "
                "reclassifying the chunk with voice references"
            )

        raise RuntimeError(
            f"Speaker enrollment did not stabilize for chunk {chunk_number}"
        )

    def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        model: Optional[str] = None,
        progress_callback: Optional[callable] = None,
        resume_key: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio file with speaker diarization.

        Args:
            audio_path: Path to audio file (WAV, MP3, etc.)
            language: Optional language hint ("ru" or "en")
            model: OpenAI transcription model
            progress_callback: Optional callback(current, total, message) for progress updates

        Returns:
            TranscriptionResult with full text and segments
        """
        model = model or self.DEFAULT_MODEL
        logger.info(
            f"Starting transcription: {audio_path}, language={language}, model={model}"
        )

        # Check file exists
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Get file size
        file_size_mb = audio_path.stat().st_size / (1024 * 1024)
        logger.debug(f"Audio file size: {file_size_mb:.2f} MB")

        # Load audio to get duration
        try:
            from scipy.io import wavfile

            sample_rate, audio_data = wavfile.read(str(audio_path))
            duration_seconds = len(audio_data) / sample_rate
        except Exception as e:
            logger.warning(f"Could not read WAV file directly: {e}")
            # Try with pydub
            try:
                audio = AudioSegment.from_file(str(audio_path))
                duration_seconds = len(audio) / 1000.0
            except Exception:
                duration_seconds = 0

        logger.debug(f"Audio duration: {duration_seconds:.1f}s")

        # Long meetings use bounded, resumable requests. Diarized chunks carry
        # provider-supported voice references so speaker identity remains global.
        needs_chunking = (
            file_size_mb > self.MAX_FILE_SIZE_MB
            or duration_seconds > self.MAX_CHUNK_DURATION
        )
        if needs_chunking:
            return self._transcribe_chunked(
                audio_path,
                language,
                duration_seconds,
                model,
                progress_callback,
                resume_key,
            )

        return self._transcribe_single(
            audio_path, language, duration_seconds, model, progress_callback
        )

    def _is_retryable_transcription_error(self, error: Exception) -> bool:
        message = str(error).lower()
        return any(
            marker in message
            for marker in (
                "500",
                "502",
                "503",
                "connection error",
                "timeout",
                "timed out",
            )
        )

    def _transcribe_single(
        self,
        audio_path: Path,
        language: Optional[str],
        duration_seconds: float,
        model: str,
        progress_callback: Optional[callable] = None,
    ) -> TranscriptionResult:
        """Transcribe a single audio file (no chunking needed)."""
        if progress_callback:
            progress_callback(0, 1, f"Sending audio to {model}...")

        client = self._get_client()

        try:
            max_retries = 3
            response = None
            for attempt in range(max_retries):
                try:
                    with open(audio_path, "rb") as audio_file:
                        response = client.audio.transcriptions.create(
                            **self._build_transcription_params(
                                model, audio_file, language
                            )
                        )
                    break
                except Exception as e:
                    if (
                        self._is_retryable_transcription_error(e)
                        and attempt < max_retries - 1
                    ):
                        wait_time = 2 ** (attempt + 1)
                        logger.warning(f"Transcription attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        raise

            full_text, detected_language, segments = self._response_to_result_parts(
                response,
                language,
                use_heuristic_speakers=(model == self.WHISPER_MODEL),
            )
            if model == self.DIARIZE_MODEL:
                self._normalize_global_speaker_labels(segments)
            # Clean transcription from hallucinations
            full_text, segments = self._clean_transcription(full_text, segments)

            if progress_callback:
                progress_callback(1, 1, "Transcript ready")

            logger.info(
                f"Transcription complete: {len(full_text)} chars, "
                f"{len(segments)} segments, language={detected_language}"
            )

            return TranscriptionResult(
                full_text=full_text,
                language=detected_language,
                segments=segments,
                duration_seconds=duration_seconds,
            )

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise

    def _transcribe_chunked(
        self,
        audio_path: Path,
        language: Optional[str],
        duration_seconds: float,
        model: str,
        progress_callback: Optional[callable] = None,
        resume_key: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe long audio file by splitting into chunks."""
        logger.info(f"Using chunked transcription for long file ({duration_seconds:.1f}s)")

        if progress_callback:
            progress_callback(0, 100, "Loading audio file...")

        try:
            # Load audio with pydub
            audio = AudioSegment.from_file(str(audio_path))
        except Exception as e:
            logger.error(f"Failed to load audio: {e}")
            raise

        # Calculate chunk parameters
        chunk_duration_ms = self.MAX_CHUNK_DURATION * 1000
        num_chunks = math.ceil(len(audio) / chunk_duration_ms)
        cache_path = self._chunk_cache_path(resume_key, model) if resume_key else None
        chunk_cache = self._load_chunk_cache(cache_path)
        audio_stat = audio_path.stat()
        cache_meta = {
            "pipeline_version": self.DIARIZATION_PIPELINE_VERSION,
            "audio_path": str(audio_path),
            "audio_size": audio_stat.st_size,
            "audio_mtime_ns": audio_stat.st_mtime_ns,
            "model": model,
            "duration_seconds": duration_seconds,
            "chunk_duration_ms": chunk_duration_ms,
            "num_chunks": num_chunks,
        }
        if chunk_cache.get("meta") != cache_meta:
            chunk_cache = {"chunks": {}}
        chunk_cache["meta"] = cache_meta
        chunk_entries = chunk_cache.setdefault("chunks", {})
        speaker_references: dict[str, str] = {}
        reference_chunks: dict[str, int] = {}
        if model == self.DIARIZE_MODEL:
            cached_references = chunk_cache.get("speaker_references", {})
            if isinstance(cached_references, dict):
                speaker_references = {
                    str(name): str(reference)
                    for name, reference in cached_references.items()
                    if isinstance(name, str) and isinstance(reference, str)
                }
            if len(speaker_references) > self.MAX_KNOWN_SPEAKERS:
                chunk_cache = {"meta": cache_meta, "chunks": {}}
                chunk_entries = chunk_cache["chunks"]
                speaker_references = {}
            cached_reference_chunks = chunk_cache.get("reference_chunks", {})
            if isinstance(cached_reference_chunks, dict):
                reference_chunks = {
                    str(name): int(chunk_number)
                    for name, chunk_number in cached_reference_chunks.items()
                    if isinstance(name, str)
                    and isinstance(chunk_number, (int, float))
                }

        all_segments: list[TranscriptSegment] = []
        full_text_parts: list[str] = []
        detected_language = language

        skipped_chunks = 0
        for i in range(num_chunks):
            output_start_ms = i * chunk_duration_ms
            start_ms = output_start_ms
            end_ms = min((i + 1) * chunk_duration_ms, len(audio))
            chunk = audio[start_ms:end_ms]

            logger.debug(f"Processing chunk {i + 1}/{num_chunks} ({start_ms/1000:.1f}s - {end_ms/1000:.1f}s)")

            if progress_callback:
                time_range = f"{start_ms//1000//60}:{start_ms//1000%60:02d} - {end_ms//1000//60}:{end_ms//1000%60:02d}"
                message = f"Фрагмент {i + 1}/{num_chunks}: обработка ({time_range})"
                logger.debug(f"Progress update: {i}/{num_chunks} - {message}")
                progress_callback(i, num_chunks, message)

            cached_chunk = chunk_entries.get(str(i))
            if self._is_valid_cached_chunk(cached_chunk, start_ms, end_ms):
                logger.info(f"Using cached transcription chunk {i + 1}/{num_chunks}")
                if cached_chunk.get("skipped"):
                    skipped_chunks += 1
                    if progress_callback:
                        reason = cached_chunk.get("skip_reason") or "пропущен"
                        progress_callback(
                            i + 1,
                            num_chunks,
                            f"Фрагмент {i + 1}/{num_chunks} пропущен: {reason}",
                        )
                else:
                    full_text_parts.append(cached_chunk.get("text", ""))
                    cached_segments = [
                        self._segment_from_cache(segment_data)
                        for segment_data in cached_chunk.get("segments", [])
                    ]
                    if model == self.DIARIZE_MODEL:
                        self._refresh_speaker_references(
                            cached_segments,
                            chunk,
                            start_ms / 1000.0,
                            speaker_references,
                            reference_chunks,
                            i + 1,
                        )
                    all_segments.extend(cached_segments)
                    if detected_language is None and cached_chunk.get("language"):
                        detected_language = cached_chunk["language"]
                if progress_callback and not cached_chunk.get("skipped"):
                    progress_callback(
                        i + 1,
                        num_chunks,
                        f"Фрагмент {i + 1}/{num_chunks} уже готов",
                    )
                continue

            def cache_chunk(
                *,
                skipped: bool,
                chunk_text: str = "",
                output_segments: Optional[list[TranscriptSegment]] = None,
                chunk_language: Optional[str] = None,
                skip_reason: Optional[str] = None,
            ) -> None:
                if cache_path is None:
                    return
                chunk_entries[str(i)] = {
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "skipped": skipped,
                    "skip_reason": skip_reason,
                    "text": chunk_text,
                    "language": chunk_language,
                    "segments": [
                        self._segment_to_cache(segment)
                        for segment in (output_segments or [])
                    ],
                }
                if model == self.DIARIZE_MODEL:
                    chunk_cache["speaker_references"] = speaker_references
                    chunk_cache["reference_chunks"] = reference_chunks
                self._save_chunk_cache(cache_path, chunk_cache)

            # Skip silent chunks to prevent hallucinations
            if self._is_silent_chunk(chunk):
                logger.info(f"Skipping silent chunk {i + 1}/{num_chunks}")
                skipped_chunks += 1
                cache_chunk(skipped=True, skip_reason="тишина")
                if progress_callback:
                    progress_callback(
                        i + 1,
                        num_chunks,
                        f"Фрагмент {i + 1}/{num_chunks} пропущен: тишина",
                    )
                continue

            # Export chunk to bytes with explicit format parameters
            # Whisper requires: 16-bit PCM, mono, 16kHz sample rate
            buffer = io.BytesIO()
            try:
                # Convert to mono if stereo
                if chunk.channels > 1:
                    chunk = chunk.set_channels(1)
                # Resample to 16kHz if needed (Whisper optimal)
                if chunk.frame_rate != 16000:
                    chunk = chunk.set_frame_rate(16000)
                # Export as 16-bit PCM WAV (default format for pydub)
                chunk.export(buffer, format="wav")
                buffer.seek(0)
                chunk_size = len(buffer.getvalue())
                logger.debug(f"Chunk {i + 1} exported: {chunk_size / 1024:.1f} KB (mono, 16kHz)")
            except Exception as e:
                logger.error(f"Failed to export chunk {i + 1}: {e}")
                raise

            if model == self.DIARIZE_MODEL:
                (
                    chunk_text,
                    chunk_language,
                    raw_chunk_segments,
                ) = self._transcribe_diarized_chunk(
                    buffer,
                    chunk,
                    language,
                    start_ms / 1000.0,
                    i + 1,
                    speaker_references,
                    reference_chunks,
                )
            else:
                response = self._request_chunk_transcription(
                    buffer,
                    model,
                    language,
                    i + 1,
                )
                (
                    chunk_text,
                    chunk_language,
                    raw_chunk_segments,
                ) = self._response_to_result_parts(
                    response,
                    language,
                    time_offset=start_ms / 1000.0,
                    use_heuristic_speakers=(model == self.WHISPER_MODEL),
                )
            if detected_language is None and chunk_language:
                detected_language = chunk_language

            chunk_segments: list[TranscriptSegment] = []
            chunk_text_parts: list[str] = []
            filtered_count = 0

            for seg in raw_chunk_segments:
                seg_text = seg.text.strip()
                if self._is_hallucination(seg_text):
                    logger.debug(f"Filtered hallucinated segment: {seg_text[:50]}...")
                    filtered_count += 1
                    continue

                chunk_segments.append(
                    TranscriptSegment(
                        transcript_id=0,
                        speaker=seg.speaker,
                        start_time=seg.start_time,
                        end_time=seg.end_time,
                        text=seg_text,
                    )
                )

            output_chunk_segments: list[TranscriptSegment] = []
            for seg in chunk_segments:
                output_chunk_segments.append(seg)
                chunk_text_parts.append(seg.text)

            if not raw_chunk_segments and chunk_text:
                chunk_text_parts.append(chunk_text.strip())

            # Check if chunk is mostly hallucination (>80% segments filtered)
            total_segments = len(raw_chunk_segments)
            if total_segments > 0 and filtered_count / total_segments > 0.8:
                logger.warning(
                    f"Chunk {i + 1} is mostly hallucination "
                    f"({filtered_count}/{total_segments} segments filtered), skipping"
                )
                skipped_chunks += 1
                cache_chunk(
                    skipped=True,
                    chunk_language=chunk_language,
                    skip_reason="галлюцинация модели",
                )
                if progress_callback:
                    progress_callback(
                        i + 1,
                        num_chunks,
                        f"Фрагмент {i + 1}/{num_chunks} пропущен: галлюцинация модели",
                    )
                continue

            # Check for repetitive text in remaining content
            chunk_text = " ".join(chunk_text_parts)
            if chunk_text and self._detect_repetitive_text(chunk_text):
                logger.warning(f"Chunk {i + 1} contains repetitive hallucination, skipping")
                skipped_chunks += 1
                cache_chunk(
                    skipped=True,
                    chunk_language=chunk_language,
                    skip_reason="повторяющаяся галлюцинация",
                )
                if progress_callback:
                    progress_callback(
                        i + 1,
                        num_chunks,
                        f"Фрагмент {i + 1}/{num_chunks} пропущен: повторяющаяся галлюцинация",
                    )
                continue

            if filtered_count > 0:
                logger.info(
                    f"Chunk {i + 1}: filtered {filtered_count}/{total_segments} "
                    f"hallucinated segments, kept {len(output_chunk_segments)}"
                )

            full_text_parts.append(chunk_text)
            all_segments.extend(output_chunk_segments)
            cache_chunk(
                skipped=False,
                chunk_text=chunk_text,
                output_segments=output_chunk_segments,
                chunk_language=chunk_language,
            )
            if progress_callback:
                progress_callback(
                    i + 1,
                    num_chunks,
                    f"Фрагмент {i + 1}/{num_chunks} готов",
                )

        if skipped_chunks > 0:
            logger.info(f"Skipped {skipped_chunks}/{num_chunks} chunks (silent or hallucination)")

        full_text = " ".join(full_text_parts)

        # Final cleanup of any remaining hallucinations
        full_text, all_segments = self._clean_transcription(full_text, all_segments)

        if progress_callback:
            progress_callback(num_chunks, num_chunks, "Transcript ready")

        logger.info(
            f"Chunked transcription complete: {num_chunks} chunks ({skipped_chunks} skipped), "
            f"{len(full_text)} chars, {len(all_segments)} segments, "
            f"{len({segment.speaker for segment in all_segments if segment.speaker})} speakers"
        )

        if cache_path and cache_path.exists():
            try:
                cache_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to remove transcription chunk cache: {e}")

        return TranscriptionResult(
            full_text=full_text,
            language=detected_language or "unknown",
            segments=all_segments,
            duration_seconds=duration_seconds,
        )

    def _chunk_cache_path(self, resume_key: Optional[str], model: str) -> Optional[Path]:
        if not resume_key:
            return None
        from src.utils.config import get_settings

        safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{resume_key}_{model}")
        return get_settings().app_data_dir / "processing" / f"{safe_key}.chunks.json"

    def _load_chunk_cache(self, cache_path: Optional[Path]) -> dict:
        if not cache_path or not cache_path.exists():
            return {"chunks": {}}
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to read transcription chunk cache: {e}")
            return {"chunks": {}}

    def _save_chunk_cache(self, cache_path: Path, chunk_cache: dict) -> None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = cache_path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(chunk_cache, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_path.replace(cache_path)
        except Exception as e:
            logger.warning(f"Failed to save transcription chunk cache: {e}")

    def _is_valid_cached_chunk(
        self,
        cached_chunk: object,
        start_ms: int,
        end_ms: int,
    ) -> bool:
        return (
            isinstance(cached_chunk, dict)
            and cached_chunk.get("start_ms") == start_ms
            and cached_chunk.get("end_ms") == end_ms
        )

    def _segment_to_cache(self, segment: TranscriptSegment) -> dict:
        return {
            "speaker": segment.speaker,
            "speaker_name": segment.speaker_name,
            "start_time": segment.start_time,
            "end_time": segment.end_time,
            "text": segment.text,
        }

    def _segment_from_cache(self, data: dict) -> TranscriptSegment:
        return TranscriptSegment(
            transcript_id=0,
            speaker=data.get("speaker"),
            speaker_name=data.get("speaker_name"),
            start_time=float(data.get("start_time", 0.0)),
            end_time=float(data.get("end_time", 0.0)),
            text=str(data.get("text", "")),
        )

    def _detect_speaker(
        self, segment, index: int, all_segments: list
    ) -> Optional[str]:
        """
        Basic speaker detection heuristic.

        This is a simplified approach. For better results, consider using
        a dedicated diarization service or model.
        """
        # Check for significant pause before this segment
        if index > 0:
            prev_seg = all_segments[index - 1]
            gap = self._get_attr(segment, "start", 0) - self._get_attr(
                prev_seg, "end", 0
            )

            # If there's a gap > 1 second, might be speaker change
            if gap > 1.0:
                # Alternate between Speaker 1 and Speaker 2
                # (This is very basic - real diarization would be more sophisticated)
                prev_speaker = getattr(self, "_last_speaker", "Speaker 1")
                new_speaker = "Speaker 2" if prev_speaker == "Speaker 1" else "Speaker 1"
                self._last_speaker = new_speaker
                return new_speaker

        # Default to Speaker 1 for first segment or continuous speech
        if not hasattr(self, "_last_speaker"):
            self._last_speaker = "Speaker 1"
        return self._last_speaker

    async def transcribe_async(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        model: Optional[str] = None,
    ) -> TranscriptionResult:
        """Async version of transcribe (runs in thread pool)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.transcribe(audio_path, language, model)
        )


# Global transcriber instance
_transcriber: Optional[Transcriber] = None


def get_transcriber() -> Transcriber:
    """Get or create global transcriber instance."""
    global _transcriber
    if _transcriber is None:
        _transcriber = Transcriber()
    return _transcriber
