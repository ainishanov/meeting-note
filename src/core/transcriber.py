"""OpenAI GPT-4o Transcribe API integration with speaker diarization."""

import asyncio
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

    # OpenAI Whisper/GPT-4o has 25MB file limit
    MAX_FILE_SIZE_MB = 25
    # Maximum audio duration per chunk (in seconds)
    MAX_CHUNK_DURATION = 600  # 10 minutes
    # Extra audio to include before each diarized chunk so we can match speaker
    # labels at chunk boundaries instead of treating local A/B labels as global.
    DIARIZE_CHUNK_OVERLAP_SECONDS = 30
    # Minimum RMS level for audio to be considered non-silent
    # Values below this threshold are likely silence or very quiet noise
    MIN_RMS_THRESHOLD = 500
    # Ratio of hallucination text to total text that triggers filtering
    HALLUCINATION_RATIO_THRESHOLD = 0.5
    DEFAULT_MODEL = "gpt-4o-mini-transcribe"
    DIARIZE_MODEL = "gpt-4o-transcribe-diarize"
    WHISPER_MODEL = "whisper-1"
    SPEAKER_MATCH_MIN_SCORE = 0.35

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

            self._client = OpenAI(api_key=api_key)

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

    def _normalize_speaker_text(self, text: str) -> set[str]:
        words = re.findall(r"[\wа-яё]+", text.lower(), re.UNICODE)
        return {word for word in words if len(word) > 2}

    def _speaker_text_similarity(self, left: str, right: str) -> float:
        left_words = self._normalize_speaker_text(left)
        right_words = self._normalize_speaker_text(right)
        if not left_words or not right_words:
            return 0.0

        intersection = left_words & right_words
        union = left_words | right_words
        return len(intersection) / len(union)

    def _build_overlap_speaker_map(
        self,
        previous_segments: list[TranscriptSegment],
        chunk_segments: list[TranscriptSegment],
        chunk_output_start: float,
    ) -> dict[str, str]:
        """Map chunk-local speaker labels to existing global labels using overlap."""
        if not previous_segments or not chunk_segments:
            return {}

        overlap_start = max(
            0.0, chunk_output_start - self.DIARIZE_CHUNK_OVERLAP_SECONDS
        )
        previous_overlap = [
            segment
            for segment in previous_segments
            if segment.speaker
            and segment.end_time >= overlap_start
            and segment.start_time <= chunk_output_start + 2.0
        ]
        current_overlap = [
            segment
            for segment in chunk_segments
            if segment.speaker
            and segment.end_time >= overlap_start
            and segment.start_time <= chunk_output_start + 2.0
        ]

        scores: dict[tuple[str, str], float] = {}
        for current in current_overlap:
            for previous in previous_overlap:
                current_speaker = current.speaker
                previous_speaker = previous.speaker
                if not current_speaker or not previous_speaker:
                    continue

                time_overlap = max(
                    0.0,
                    min(current.end_time, previous.end_time)
                    - max(current.start_time, previous.start_time),
                )
                current_mid = (current.start_time + current.end_time) / 2
                previous_mid = (previous.start_time + previous.end_time) / 2
                time_proximity = 1 / (1 + abs(current_mid - previous_mid))
                text_similarity = self._speaker_text_similarity(
                    current.text, previous.text
                )
                if time_overlap <= 0 and text_similarity < 0.15:
                    continue

                score = time_overlap + (time_proximity * 0.5) + (
                    2 * text_similarity
                )

                if score <= 0:
                    continue

                key = (current_speaker, previous_speaker)
                scores[key] = scores.get(key, 0.0) + score

        speaker_map: dict[str, str] = {}
        used_global_speakers: set[str] = set()
        ranked_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        for (local_speaker, global_speaker), score in ranked_scores:
            if score < self.SPEAKER_MATCH_MIN_SCORE:
                continue
            if local_speaker in speaker_map or global_speaker in used_global_speakers:
                continue
            speaker_map[local_speaker] = global_speaker
            used_global_speakers.add(global_speaker)

        return speaker_map

    def _normalize_diarized_chunk_speakers(
        self,
        chunk_segments: list[TranscriptSegment],
        previous_segments: list[TranscriptSegment],
        chunk_output_start: float,
        next_speaker_number: int,
    ) -> int:
        """
        Convert model-local diarization labels into transcript-level labels.

        The diarize API returns labels such as A/B per request. When long audio is
        split, those labels are only reliable inside that chunk. We reuse a prior
        global speaker only when the overlap proves the mapping.
        """
        speaker_map = self._build_overlap_speaker_map(
            previous_segments, chunk_segments, chunk_output_start
        )

        local_to_global = dict(speaker_map)
        for segment in chunk_segments:
            local_speaker = segment.speaker
            if not local_speaker:
                continue

            if local_speaker not in local_to_global:
                local_to_global[local_speaker] = f"Speaker {next_speaker_number}"
                next_speaker_number += 1

            segment.speaker = local_to_global[local_speaker]

        return next_speaker_number

    def _build_transcription_params(
        self,
        model: str,
        file,
        language: Optional[str],
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

        # Determine if we need to chunk. Diarized requests already use the API's
        # auto chunking, so avoid app-level chunking when the whole file fits.
        needs_chunking = file_size_mb > self.MAX_FILE_SIZE_MB or (
            model != self.DIARIZE_MODEL
            and duration_seconds > self.MAX_CHUNK_DURATION
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
                    is_retryable = "500" in str(e) or "502" in str(e) or "503" in str(e) or "Connection error" in str(e) or "timeout" in str(e).lower()
                    if is_retryable and attempt < max_retries - 1:
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
                self._normalize_diarized_chunk_speakers(
                    segments,
                    previous_segments=[],
                    chunk_output_start=0.0,
                    next_speaker_number=1,
                )

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
        chunk_cache["meta"] = {
            "audio_path": str(audio_path),
            "model": model,
            "duration_seconds": duration_seconds,
            "chunk_duration_ms": chunk_duration_ms,
            "num_chunks": num_chunks,
        }
        chunk_entries = chunk_cache.setdefault("chunks", {})

        all_segments: list[TranscriptSegment] = []
        full_text_parts: list[str] = []
        detected_language = language
        next_speaker_number = 1

        skipped_chunks = 0
        for i in range(num_chunks):
            output_start_ms = i * chunk_duration_ms
            overlap_ms = (
                self.DIARIZE_CHUNK_OVERLAP_SECONDS * 1000
                if model == self.DIARIZE_MODEL and i > 0
                else 0
            )
            start_ms = max(0, output_start_ms - overlap_ms)
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
                    all_segments.extend(cached_segments)
                    if detected_language is None and cached_chunk.get("language"):
                        detected_language = cached_chunk["language"]
                next_speaker_number = cached_chunk.get(
                    "next_speaker_number",
                    next_speaker_number,
                )
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
                    "next_speaker_number": next_speaker_number,
                    "segments": [
                        self._segment_to_cache(segment)
                        for segment in (output_segments or [])
                    ],
                }
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

            # Transcribe chunk with retry logic for transient API errors
            client = self._get_client()
            max_retries = 3
            response = None
            for attempt in range(max_retries):
                try:
                    buffer.seek(0)
                    response = client.audio.transcriptions.create(
                        **self._build_transcription_params(
                            model,
                            ("chunk.wav", buffer, "audio/wav"),
                            language,
                        )
                    )
                    break
                except Exception as e:
                    is_retryable = "500" in str(e) or "502" in str(e) or "503" in str(e) or "Connection error" in str(e) or "timeout" in str(e).lower()
                    if is_retryable and attempt < max_retries - 1:
                        wait_time = 2 ** (attempt + 1)  # 2, 4 seconds
                        logger.warning(f"Chunk {i + 1} attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Failed to transcribe chunk {i + 1}: {e}")
                        raise

            chunk_text, chunk_language, raw_chunk_segments = self._response_to_result_parts(
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
            output_start_seconds = output_start_ms / 1000.0

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

            if model == self.DIARIZE_MODEL:
                next_speaker_number = self._normalize_diarized_chunk_speakers(
                    chunk_segments,
                    all_segments,
                    output_start_seconds,
                    next_speaker_number,
                )

            output_chunk_segments: list[TranscriptSegment] = []
            for seg in chunk_segments:
                if i > 0 and seg.end_time <= output_start_seconds + 0.5:
                    continue
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
            f"{len(full_text)} chars, {len(all_segments)} segments"
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
