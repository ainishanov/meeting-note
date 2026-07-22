import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

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


if __name__ == "__main__":
    unittest.main()
