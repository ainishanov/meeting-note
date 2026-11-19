import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.core.audio_recorder import CaptureStatus
from src.ui.i18n import tr
from src.ui.recording_widget import RecordingWidget


class RecordingWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = RecordingWidget()

    def tearDown(self):
        self.widget.deleteLater()

    def test_detected_call_becomes_primary_idle_action(self):
        self.widget.set_detected_meeting("chrome.exe (meeting)")

        self.assertEqual(self.widget.status_label.text(), tr("Обнаружен созвон"))
        self.assertEqual(self.widget.context_label.text(), tr("Созвон в браузере"))
        self.assertEqual(self.widget.main_button.text(), tr("Записать этот созвон"))
        self.assertTrue(self.widget._detection_timer.isActive())

    def test_recording_state_reveals_only_active_controls(self):
        self.assertTrue(self.widget.stop_button.isHidden())
        self.assertTrue(self.widget.level_meter.isHidden())
        self.assertTrue(self.widget.duration_label.isHidden())

        self.widget.set_detected_meeting("zoom.exe")
        self.widget.set_recording_state("recording")

        self.assertFalse(self.widget.stop_button.isHidden())
        self.assertFalse(self.widget.level_meter.isHidden())
        self.assertFalse(self.widget.duration_label.isHidden())
        self.assertEqual(self.widget.context_label.text(), tr("Системный звук и микрофон записываются"))
        self.assertFalse(self.widget._detection_timer.isActive())

    def test_recording_shows_where_meeting_sound_is_captured(self):
        self.widget.set_recording_state("recording")

        self.widget.set_audio_source(
            CaptureStatus(("Динамики", "Наушники"), None, "Микрофон")
        )
        self.assertEqual(
            self.widget.context_label.text(),
            tr("Слушаю: {sources}", sources="Динамики, Наушники") + " · " + tr("микрофон"),
        )

        self.widget.set_audio_source(CaptureStatus(("Динамики", "Наушники"), "Наушники", None))
        self.assertEqual(
            self.widget.context_label.text(), tr("Звук встречи: {source}", source="Наушники")
        )

        self.widget.set_audio_source(CaptureStatus((), None, None))
        self.assertEqual(self.widget.context_label.text(), tr("Выходы звука не найдены"))

    def test_source_reported_before_recording_starts_is_kept(self):
        self.widget.set_audio_source(CaptureStatus(("Наушники",), "Наушники", "Микрофон"))
        self.widget.set_recording_state("recording")

        self.assertEqual(
            self.widget.context_label.text(),
            tr("Звук встречи: {source}", source="Наушники") + " · " + tr("микрофон"),
        )

    def test_source_is_forgotten_after_recording(self):
        self.widget.set_recording_state("recording")
        self.widget.set_audio_source(CaptureStatus(("Наушники",), "Наушники", None))
        self.widget.set_recording_state("idle")

        self.assertEqual(self.widget.context_label.text(), tr("Системный звук и микрофон"))
        self.widget.set_recording_state("recording")
        self.assertEqual(self.widget.context_label.text(), tr("Системный звук и микрофон записываются"))


if __name__ == "__main__":
    unittest.main()
