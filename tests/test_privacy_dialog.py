import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.ui.privacy_dialog import PrivacyChoiceDialog


class PrivacyChoiceDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_decline_persists_explicit_opt_out(self):
        dialog = PrivacyChoiceDialog()
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            with patch("src.ui.privacy_dialog.save_env_settings") as save:
                dialog._decline()

        save.assert_called_once_with(
            {
                "PRIVACY_CHOICE_COMPLETED": True,
                "ANONYMOUS_ANALYTICS_ENABLED": False,
                "CRASH_REPORTS_ENABLED": False,
            }
        )
        dialog.deleteLater()

    def test_choices_are_off_by_default(self):
        dialog = PrivacyChoiceDialog()
        self.assertFalse(dialog.analytics_checkbox.isChecked())
        self.assertFalse(dialog.crash_checkbox.isChecked())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
