"""AI-powered meeting summarization via OpenRouter."""

import json
import re
import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger
from openai import OpenAI

from src.core.database import Summary, TranscriptSegment


@dataclass
class SummaryResult:
    """Result of meeting summarization."""

    summary: str
    key_points: list[str]
    decisions: list[str]
    action_items: list[str]


@dataclass
class SummaryCostEstimate:
    """Approximate summary request size and cost."""

    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Optional[float]


SUMMARY_MODEL_PRICES_USD_PER_M: dict[str, tuple[float, float]] = {
    "google/gemini-2.5-flash-lite": (0.10, 0.40),
}


def estimate_summary_cost(
    transcript: str,
    model: Optional[str] = None,
    output_tokens: int = 6000,
) -> SummaryCostEstimate:
    """Estimate summary cost from character count using conservative token math."""
    if model is None:
        try:
            from src.utils.config import get_settings

            model = get_settings().summary_model
        except Exception:
            model = Summarizer.MODEL_NAME

    input_tokens = max(1, int(len(transcript) / 4))
    prices = SUMMARY_MODEL_PRICES_USD_PER_M.get(model)
    cost_usd = None
    if prices:
        input_price, output_price = prices
        cost_usd = (
            input_tokens / 1_000_000 * input_price
            + output_tokens / 1_000_000 * output_price
        )

    return SummaryCostEstimate(
        model=model or Summarizer.MODEL_NAME,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )


def format_summary_estimate(transcript: str, model: Optional[str] = None) -> str:
    """Human-readable model/cost estimate for the summary UI."""
    estimate = estimate_summary_cost(transcript, model=model)
    tokens = f"~{estimate.input_tokens // 1000}k input tokens"
    if estimate.cost_usd is None:
        return f"{estimate.model}, {tokens}"
    return f"{estimate.model}, {tokens}, ~${estimate.cost_usd:.4f}"


SYSTEM_PROMPT = """You are an expert meeting analyst. Extract the most useful information from the transcript.

## What to produce:

1. **Summary** (summary) - 2-4 paragraphs with the core substance of the meeting
2. **Key points** (key_points) - the main topics discussed
3. **Decisions** (decisions) - concrete decisions that were made
4. **Action items** (action_items) - who needs to do what and by when

## Rules:

- Write in the same language as the transcript
- Be specific: instead of "discussed the project", write "discussed launching project X by the end of the quarter"
- For action items, include the owner (@name) and due date when mentioned
- If speakers are not identified, do not invent names
- Group related topics together
- Preserve numbers, dates, amounts, and metrics

## Response format (JSON):

{
    "summary": "Meeting overview...",
    "key_points": ["Topic 1: details", "Topic 2: details"],
    "decisions": ["Decision 1", "Decision 2"],
    "action_items": ["@Name: task (deadline)", "Task without owner"]
}

If a section has no content, such as no decisions, return an empty array []."""

USER_PROMPT_TEMPLATE = """Analyze this meeting transcript and extract the key information.

Transcript:
{transcript}

Return ONLY valid JSON without markdown."""

TITLE_GENERATION_PROMPT = """Create a short title for this meeting recording based on its content.

Rules:
- Maximum 5-7 words
- Capture the meeting topic
- No quotes or special symbols
- Use the same language as the transcript

Examples of good titles:
- Product launch planning
- Quarterly KPI review
- Marketing sync
- Weekly team standup

Transcript (first 2000 characters):
{transcript}

Return ONLY the title, nothing else."""

SPEAKER_NAME_INFERENCE_PROMPT = """Infer real speaker names from the meeting transcript.

Speakers are already marked with technical labels: Speaker 1, Speaker 2, and so on.

Rules:
- Return a name only when the transcript contains explicit evidence.
- The strongest evidence is self-identification, such as "I am Olga" or "this is Andrew".
- A direct address by name is evidence only when neighboring turns make it clear which Speaker answers that address.
- Do not treat mentions of third parties as the current speaker's name.
- Do not invent names and do not use roles such as manager, client, or team.
- If confidence is low, return name=null and confidence="low".

Transcript:
{transcript}

Return ONLY valid JSON without markdown in this format:
{{
  "speakers": [
    {{"speaker": "Speaker 1", "name": "Olga", "confidence": "high", "evidence": "short quote/explanation"}},
    {{"speaker": "Speaker 2", "name": null, "confidence": "low", "evidence": ""}}
  ]
}}"""


def get_segment_speaker_label(segment: TranscriptSegment) -> str:
    return segment.display_speaker


def apply_speaker_names(
    segments: list[TranscriptSegment],
    speaker_names: dict[str, str],
) -> None:
    """Apply inferred display names to transcript segments in memory."""
    if not speaker_names:
        return

    for segment in segments:
        if segment.speaker in speaker_names:
            segment.speaker_name = speaker_names[segment.speaker]


def create_speaker_aware_summary(
    summarizer,
    recording_id: int,
    transcript_text: str,
    segments: list[TranscriptSegment],
) -> Summary:
    """Create a summary using speaker labels when they are available."""
    if any(segment.speaker for segment in segments):
        segment_payload = [
            {"speaker": get_segment_speaker_label(segment), "text": segment.text}
            for segment in segments
            if segment.text
        ]
        if segment_payload:
            result = summarizer.summarize_with_segments(segment_payload)
            return Summary(
                recording_id=recording_id,
                summary=result.summary,
                key_points=result.key_points,
                decisions=result.decisions,
                action_items=result.action_items,
            )

    return summarizer.create_summary_for_recording(recording_id, transcript_text)


class Summarizer:
    """
    Meeting summarization using OpenRouter chat completions.

    Generates:
    - Overall meeting summary
    - Key discussion points
    - Action items
    """

    MODEL_NAME = "google/gemini-2.5-flash-lite"
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
    SUMMARY_CHUNK_THRESHOLD_CHARS = 60000
    SUMMARY_CHUNK_CHARS = 30000
    MAX_TRANSCRIPT_CHARS = 500000

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """
        Initialize summarizer.

        Args:
            api_key: OpenRouter API key (uses secure storage if not provided)
            model_name: OpenRouter model id
            base_url: OpenRouter-compatible API base URL
        """
        self._api_key = api_key
        self._model_name = model_name
        self._base_url = base_url
        self._client: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        """Get or create OpenRouter-backed OpenAI client."""
        if self._client is None:
            api_key = self._api_key
            if not api_key:
                from src.utils.security import get_openrouter_api_key

                api_key = get_openrouter_api_key()

            if not api_key:
                raise ValueError(
                    "OpenRouter API key not configured. "
                    "Set OPENROUTER_API_KEY environment variable or configure in settings."
                )

            self._client = OpenAI(
                api_key=api_key,
                base_url=self._get_base_url(),
                default_headers={"X-Title": "Meeting Note"},
            )

        return self._client

    def _get_model_name(self) -> str:
        if self._model_name:
            return self._model_name

        from src.utils.config import get_settings

        return get_settings().summary_model or self.MODEL_NAME

    def _get_base_url(self) -> str:
        if self._base_url:
            return self._base_url

        from src.utils.config import get_settings

        return get_settings().openrouter_base_url or self.OPENROUTER_BASE_URL

    def _request_content(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        json_response: bool,
    ) -> str:
        """Request a chat completion and return the message text."""
        client = self._get_client()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        request = {
            "model": self._get_model_name(),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_response:
            request["response_format"] = {"type": "json_object"}

        max_retries = 3
        retry_delay = 10
        for attempt in range(max_retries):
            try:
                try:
                    response = client.chat.completions.create(**request)
                except Exception as e:
                    if json_response and self._is_response_format_error(e):
                        logger.warning(
                            "OpenRouter model rejected response_format; retrying without it"
                        )
                        request.pop("response_format", None)
                        response = client.chat.completions.create(**request)
                    else:
                        raise
                return self._clean_response_text(
                    response.choices[0].message.content or ""
                )
            except Exception as e:
                if attempt < max_retries - 1 and self._is_retryable_error(e):
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning(
                        f"Summary provider rate limit, waiting {wait_time}s before "
                        f"retry {attempt + 2}/{max_retries}"
                    )
                    time.sleep(wait_time)
                    continue
                raise

        raise RuntimeError("OpenRouter request failed without an exception")

    def _is_retryable_error(self, error: Exception) -> bool:
        message = str(error).lower()
        return (
            "429" in message
            or "rate limit" in message
            or "resource exhausted" in message
            or "temporarily unavailable" in message
        )

    def _is_response_format_error(self, error: Exception) -> bool:
        message = str(error).lower()
        return (
            "response_format" in message
            or "response format" in message
            or "structured output" in message
            or "unsupported parameter" in message
        )

    def _clean_response_text(self, content: str) -> str:
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            if len(lines) >= 2:
                content = "\n".join(lines[1:-1]).strip()
        return content

    def summarize(
        self,
        transcript: str,
        max_tokens: int = 6000,
    ) -> SummaryResult:
        """
        Generate meeting summary from transcript.

        Args:
            transcript: Full meeting transcript text
            max_tokens: Maximum tokens for response (not used with Gemini, kept for API compatibility)

        Returns:
            SummaryResult with summary, key points, and action items
        """
        if not transcript or len(transcript.strip()) < 50:
            logger.warning("Transcript too short for meaningful summary")
            return SummaryResult(
                summary="Transcript is too short to analyze.",
                key_points=[],
                decisions=[],
                action_items=[],
            )

        logger.info(f"Generating summary for transcript ({len(transcript)} chars)")
        if len(transcript) > self.SUMMARY_CHUNK_THRESHOLD_CHARS:
            return self._summarize_chunked(transcript, max_tokens)

        return self._summarize_single(transcript, max_tokens)

    def _summarize_single(
        self,
        transcript: str,
        max_tokens: int,
    ) -> SummaryResult:
        """Generate one JSON summary request without recursive chunking."""
        content = ""
        try:
            if len(transcript) > self.MAX_TRANSCRIPT_CHARS:
                logger.warning(
                    f"Truncating transcript from {len(transcript)} to {self.MAX_TRANSCRIPT_CHARS} chars"
                )
                transcript = transcript[:self.MAX_TRANSCRIPT_CHARS] + "\n\n[Transcript truncated...]"

            content = self._request_content(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=USER_PROMPT_TEMPLATE.format(transcript=transcript),
                temperature=0.3,
                max_tokens=max_tokens,
                json_response=True,
            )
            result_data = json.loads(content)

            summary_result = SummaryResult(
                summary=result_data.get("summary", ""),
                key_points=result_data.get("key_points", []),
                decisions=result_data.get("decisions", []),
                action_items=result_data.get("action_items", []),
            )

            logger.info(
                f"Summary generated: {len(summary_result.key_points)} key points, "
                f"{len(summary_result.decisions)} decisions, "
                f"{len(summary_result.action_items)} action items"
            )

            return summary_result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse summary JSON: {e}")
            # Try to extract text even if JSON parsing fails
            return SummaryResult(
                summary=content if content else "Could not generate a summary.",
                key_points=[],
                decisions=[],
                action_items=[],
            )

        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            raise

    def _summarize_chunked(
        self,
        transcript: str,
        max_tokens: int,
    ) -> SummaryResult:
        """Summarize long transcripts by chunking then merging the extracted facts."""
        chunks = self._split_transcript_for_summary(transcript)
        logger.info(
            f"Using chunked summary for {len(transcript)} chars: {len(chunks)} chunks"
        )

        chunk_results: list[SummaryResult] = []
        for index, chunk in enumerate(chunks, start=1):
            logger.info(f"Summarizing transcript chunk {index}/{len(chunks)}")
            chunk_results.append(self._summarize_single(chunk, max_tokens=3500))

        merged_lines: list[str] = []
        for index, result in enumerate(chunk_results, start=1):
            merged_lines.append(f"Part {index}:")
            if result.summary:
                merged_lines.append(f"Summary: {result.summary}")
            if result.key_points:
                merged_lines.append("Key points:")
                merged_lines.extend(f"- {item}" for item in result.key_points)
            if result.decisions:
                merged_lines.append("Decisions:")
                merged_lines.extend(f"- {item}" for item in result.decisions)
            if result.action_items:
                merged_lines.append("Action items:")
                merged_lines.extend(f"- {item}" for item in result.action_items)
            merged_lines.append("")

        merged_transcript = "\n".join(merged_lines)
        logger.info(
            f"Merging {len(chunks)} partial summaries ({len(merged_transcript)} chars)"
        )
        return self._summarize_single(merged_transcript, max_tokens=max_tokens)

    def _split_transcript_for_summary(self, transcript: str) -> list[str]:
        """Split transcript into line-aware chunks for robust long-meeting summaries."""
        lines = transcript.splitlines() or [transcript]
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for line in lines:
            line_len = len(line) + 1
            if current and current_len + line_len > self.SUMMARY_CHUNK_CHARS:
                chunks.append("\n".join(current))
                current = []
                current_len = 0

            if line_len > self.SUMMARY_CHUNK_CHARS:
                for start in range(0, len(line), self.SUMMARY_CHUNK_CHARS):
                    piece = line[start:start + self.SUMMARY_CHUNK_CHARS]
                    if current:
                        chunks.append("\n".join(current))
                        current = []
                        current_len = 0
                    chunks.append(piece)
                continue

            current.append(line)
            current_len += line_len

        if current:
            chunks.append("\n".join(current))

        return chunks

    def summarize_with_segments(
        self,
        segments: list[dict],
        max_tokens: int = 6000,
    ) -> SummaryResult:
        """
        Generate summary from transcript segments with speaker info.

        Args:
            segments: List of segments with 'speaker' and 'text' keys
            max_tokens: Maximum tokens for response

        Returns:
            SummaryResult with summary, key points, and action items
        """
        # Format segments with speaker labels
        formatted_lines = []
        for seg in segments:
            speaker = seg.get("speaker", "Speaker")
            text = seg.get("text", "").strip()
            if text:
                formatted_lines.append(f"{speaker}: {text}")

        transcript = "\n".join(formatted_lines)
        return self.summarize(transcript, max_tokens)

    def _format_segments_for_name_inference(
        self,
        segments: list[TranscriptSegment],
        max_chars: int = 120000,
    ) -> str:
        lines: list[str] = []
        total_chars = 0
        for segment in segments:
            if not segment.speaker or not segment.text:
                continue

            start_min = int(segment.start_time // 60)
            start_sec = int(segment.start_time % 60)
            line = f"[{start_min}:{start_sec:02d}] {segment.speaker}: {segment.text.strip()}"
            if total_chars + len(line) > max_chars:
                lines.append("[Transcript truncated for speaker name inference]")
                break
            lines.append(line)
            total_chars += len(line)

        return "\n".join(lines)

    def _clean_speaker_name(self, name: object) -> Optional[str]:
        if name is None:
            return None

        value = str(name).strip()
        if len(value) < 2:
            return None

        value = re.sub(r"\s+", " ", value)
        if re.fullmatch(r"speaker\s*\d+", value, flags=re.IGNORECASE):
            return None
        if len(value) > 40:
            return None
        if not re.fullmatch(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё .'-]*", value):
            return None

        return value

    def _parse_speaker_name_map(self, result_data: object) -> dict[str, str]:
        if not isinstance(result_data, dict):
            return {}

        speakers = result_data.get("speakers", [])
        if not isinstance(speakers, list):
            return {}

        candidates: dict[str, str] = {}
        duplicate_names: set[str] = set()
        seen_names: dict[str, str] = {}

        for item in speakers:
            if not isinstance(item, dict):
                continue

            speaker = str(item.get("speaker") or "").strip()
            confidence = str(item.get("confidence") or "").strip().lower()
            name = self._clean_speaker_name(item.get("name"))

            if not speaker or confidence != "high" or not name:
                continue

            name_key = name.casefold()
            if name_key in seen_names and seen_names[name_key] != speaker:
                duplicate_names.add(name_key)
                continue

            seen_names[name_key] = speaker
            candidates[speaker] = name

        return {
            speaker: name
            for speaker, name in candidates.items()
            if name.casefold() not in duplicate_names
        }

    def infer_speaker_names(
        self,
        segments: list[TranscriptSegment],
    ) -> dict[str, str]:
        """Infer real speaker names from transcript text when evidence is strong."""
        speaker_labels = {segment.speaker for segment in segments if segment.speaker}
        if not speaker_labels:
            return {}
        if all(segment.speaker_name for segment in segments if segment.speaker):
            return {}

        transcript = self._format_segments_for_name_inference(segments)
        if len(transcript.strip()) < 50:
            return {}

        logger.info(
            f"Inferring speaker names for {len(speaker_labels)} speakers "
            f"({len(transcript)} chars)"
        )

        try:
            content = self._request_content(
                system_prompt=None,
                user_prompt=SPEAKER_NAME_INFERENCE_PROMPT.format(
                    transcript=transcript
                ),
                temperature=0.1,
                max_tokens=2000,
                json_response=True,
            )
            speaker_names = self._parse_speaker_name_map(json.loads(content))
            if speaker_names:
                logger.info(f"Inferred speaker names: {speaker_names}")
            return speaker_names

        except Exception as e:
            logger.warning(f"Speaker name inference failed: {e}")
            return {}

    def generate_title(self, transcript: str) -> str:
        """
        Generate a short descriptive title from transcript.

        Args:
            transcript: Full or partial transcript text

        Returns:
            Short title describing the meeting content
        """
        if not transcript or len(transcript.strip()) < 50:
            return ""

        # Use only first 2000 chars for title generation
        transcript_preview = transcript[:2000]

        logger.info("Generating title from transcript")

        try:
            title = self._request_content(
                system_prompt=None,
                user_prompt=TITLE_GENERATION_PROMPT.format(
                    transcript=transcript_preview
                ),
                temperature=0.5,
                max_tokens=50,
                json_response=False,
            )
            # Remove quotes if present
            title = title.strip('"\'')
            # Limit length
            if len(title) > 100:
                title = title[:97] + "..."

            logger.info(f"Generated title: {title}")
            return title

        except Exception as e:
            logger.error(f"Title generation failed: {e}")
            return ""

    def create_summary_for_recording(
        self, recording_id: int, transcript_text: str
    ) -> Summary:
        """
        Create and save summary for a recording.

        Args:
            recording_id: ID of the recording in database
            transcript_text: Full transcript text

        Returns:
            Summary object ready to save to database
        """
        result = self.summarize(transcript_text)

        return Summary(
            recording_id=recording_id,
            summary=result.summary,
            key_points=result.key_points,
            decisions=result.decisions,
            action_items=result.action_items,
        )


# Global summarizer instance
_summarizer: Optional[Summarizer] = None


def get_summarizer() -> Summarizer:
    """Get or create global summarizer instance."""
    global _summarizer
    if _summarizer is None:
        _summarizer = Summarizer()
    return _summarizer
