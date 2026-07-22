import os
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from src.ui.feedback_dialog import (
    BUG_REPORT_URL,
    DISCUSSIONS_URL,
    FEEDBACK_FORM_URL,
    FEATURE_REQUEST_URL,
    FeedbackDialog,
    submit_feedback,
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
        self.assertIn("docs.google.com/forms", FEEDBACK_FORM_URL)
        self.assertIn("feature_request.yml", FEATURE_REQUEST_URL)
        self.assertIn("bug_report.yml", BUG_REPORT_URL)
        self.assertIn("/discussions/", DISCUSSIONS_URL)

    @patch("src.ui.feedback_dialog.QDesktopServices.openUrl", return_value=True)
    def test_open_route_waits_for_user_to_publish_in_github(self, open_url):
        self.dialog._open_route(FEATURE_REQUEST_URL)

        opened_url = open_url.call_args.args[0]
        self.assertEqual(opened_url.toString(), FEATURE_REQUEST_URL)

    @patch("src.ui.feedback_dialog.QDesktopServices.openUrl", return_value=True)
    def test_direct_feedback_does_not_require_github(self, open_url):
        self.dialog._open_route(FEEDBACK_FORM_URL)

        opened_url = open_url.call_args.args[0]
        self.assertEqual(opened_url.toString(), FEEDBACK_FORM_URL)
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Rejected)

    @patch("src.ui.feedback_dialog.urllib.request.urlopen")
    def test_direct_submit_sends_only_user_authored_fields(self, urlopen):
        response = MagicMock()
        response.read.return_value = b"ok"
        urlopen.return_value.__enter__.return_value = response

        submit_feedback("general", "The summary view is useful", "@tester")

        request = urlopen.call_args.args[0]
        fields = parse_qs(request.data.decode("utf-8"))
        self.assertEqual(fields["entry.1121103253"], ["General feedback / Общий отзыв"])
        self.assertIn("The summary view is useful", fields["entry.1258727091"][0])
        self.assertEqual(fields["entry.450011572"], ["@tester"])


if __name__ == "__main__":
    unittest.main()
