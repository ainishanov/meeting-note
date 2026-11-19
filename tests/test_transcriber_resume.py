import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from pydub import AudioSegment

from src.core.transcriber import Transcriber


class TranscriberResumeProgressTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.audio_path = Path(temp.name) / "meeting.wav"
        self.audio_path.touch()
        self.cache_path = Path(temp.name) / "meeting.chunks.json"
        self.transcriber = Transcriber(api_key="offline-test")
        self.transcriber.MAX_CHUNK_DURATION = 2
        self.texts = [
            "We reviewed the launch plan.",
            "The team agreed on a date.",
            "Prepare the release notes.",
            "Confirm the final checklist.",
        ]
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch(
            "src.core.transcriber.AudioSegment.from_file",
            return_value=AudioSegment.silent(duration=8000, frame_rate=16000),
        ))
        stack.enter_context(patch.object(
            self.transcriber, "_is_silent_chunk", return_value=False,
        ))
        stack.enter_context(patch.object(
            self.transcriber, "_chunk_cache_path", return_value=self.cache_path,
        ))
        self._seed_interrupted_transcription()

    def _response(self, _buffer, _model, _language, chunk_number):
        return {"text": self.texts[chunk_number - 1], "language": "en"}

    def _run(self, request, progress_callback=None):
        with patch.object(
            self.transcriber, "_request_chunk_transcription", side_effect=request,
        ) as mocked_request:
            result = self.transcriber._transcribe_chunked(
                self.audio_path,
                language="en",
                duration_seconds=8.0,
                model=self.transcriber.DEFAULT_MODEL,
                progress_callback=progress_callback,
                resume_key="recording-1",
            )
        return result, mocked_request

    def _seed_interrupted_transcription(self):
        def interrupt(buffer, model, language, chunk_number):
            if chunk_number == 3:
                raise RuntimeError("Simulated interruption")
            return self._response(buffer, model, language, chunk_number)

        with self.assertRaisesRegex(RuntimeError, "Simulated interruption"):
            self._run(interrupt)

    def _assert_monotonic_progress(self, updates, minimum):
        counts = [current for current, total, _ in updates if total == 4]
        self.assertEqual(counts, sorted(counts))
        self.assertGreaterEqual(min(counts), minimum)
        self.assertEqual(counts[-1], 4)

    def test_resume_reports_saved_progress_and_only_processes_missing_chunks(self):
        updates = []
        result, request = self._run(
            self._response, lambda *update: updates.append(update),
        )

        self.assertEqual([call.args[3] for call in request.call_args_list], [3, 4])
        processing = [u for u in updates if "обработка" in u[2]]
        self.assertEqual(processing[0][:2], (2, 4))
        self.assertIn("Фрагмент 3/4", processing[0][2])
        self.assertFalse(any("Фрагмент 1/4" in u[2] for u in updates))
        self.assertFalse(any("Фрагмент 2/4" in u[2] for u in updates))
        self._assert_monotonic_progress(updates, minimum=2)
        self.assertEqual(result.full_text, " ".join(self.texts))

    def test_cache_with_gap_does_not_make_progress_go_backwards(self):
        cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        del cache["chunks"]["0"]
        self.cache_path.write_text(json.dumps(cache), encoding="utf-8")
        updates = []

        result, request = self._run(
            self._response, lambda *update: updates.append(update),
        )

        self.assertEqual([call.args[3] for call in request.call_args_list], [1, 3, 4])
        self.assertFalse(any("Фрагмент 2/4" in u[2] for u in updates))
        self._assert_monotonic_progress(updates, minimum=1)
        self.assertEqual(result.full_text, " ".join(self.texts))

    def test_invalidated_cache_starts_from_zero(self):
        cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        cache["meta"]["audio_mtime_ns"] -= 1
        self.cache_path.write_text(json.dumps(cache), encoding="utf-8")
        updates = []

        _, request = self._run(
            self._response, lambda *update: updates.append(update),
        )

        self.assertEqual([call.args[3] for call in request.call_args_list], [1, 2, 3, 4])
        processing = [u for u in updates if "обработка" in u[2]]
        self.assertEqual(processing[0][:2], (0, 4))
        self.assertFalse(any("Продолжаю" in u[2] for u in updates))
        self._assert_monotonic_progress(updates, minimum=0)


if __name__ == "__main__":
    unittest.main()
