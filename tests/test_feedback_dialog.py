import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog

from src.ui.feedback_dialog import (
    BUG_REPORT_URL,
    DISCUSSIONS_URL,
    FEATURE_REQUEST_URL,
    FeedbackDialog,
)


class FeedbackDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = FeedbackDialog()

    def tearDown(self):
        self.dialog.deleteLater()

    def test_routes_use_the_project_feedback_channels(self):
        self.assertIn("feature_request.yml", FEATURE_REQUEST_URL)
        self.assertIn("bug_report.yml", BUG_REPORT_URL)
        self.assertIn("/discussions/", DISCUSSIONS_URL)

    @patch("src.ui.feedback_dialog.QDesktopServices.openUrl", return_value=True)
    def test_open_route_waits_for_user_to_publish_in_github(self, open_url):
        self.dialog._open_route(FEATURE_REQUEST_URL)

        opened_url = open_url.call_args.args[0]
        self.assertEqual(opened_url.toString(), FEATURE_REQUEST_URL)
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)


if __name__ == "__main__":
    unittest.main()
