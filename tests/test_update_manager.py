import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from src.ui.update_manager import UpdateManager, failure_presentation
from src.utils.updater import (
    UpdateFailure,
    UpdateFailureKind,
    UpdateResult,
    UpdateStage,
)


def identity_tr(text: str, **kwargs: object) -> str:
    return text.format(**kwargs) if kwargs else text


class UpdateManagerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.parent = QWidget()
        self.manager = UpdateManager(self.parent)

    def tearDown(self):
        self.manager.cleanup()
        self.parent.deleteLater()

    @patch("src.ui.update_manager.tr", side_effect=identity_tr)
    def test_download_network_copy_describes_only_download_state(self, _tr):
        failure = UpdateFailure(
            stage=UpdateStage.DOWNLOAD,
            kind=UpdateFailureKind.NETWORK,
            detail="offline",
            retryable=True,
        )

        presentation = failure_presentation(failure)

        self.assertEqual(presentation.title, "Загрузка прервана")
        self.assertIn("Соединение прервалось", presentation.message)
        self.assertIn("Неполный файл удалён", presentation.message)
        self.assertEqual(presentation.retry_label, "Повторить загрузку")

    @patch("src.ui.update_manager.tr", side_effect=identity_tr)
    def test_launch_copy_preserves_successful_download_state(self, _tr):
        failure = UpdateFailure(
            stage=UpdateStage.LAUNCH,
            kind=UpdateFailureKind.LAUNCH,
            detail="blocked",
            retryable=True,
        )

        presentation = failure_presentation(failure)

        self.assertEqual(presentation.title, "Не удалось запустить установщик")
        self.assertIn("скачано и проверено", presentation.message)
        self.assertEqual(presentation.retry_label, "Запустить снова")

    def test_cancelled_download_is_silent(self):
        failure = UpdateFailure(
            stage=UpdateStage.DOWNLOAD,
            kind=UpdateFailureKind.CANCELLED,
            detail="cancelled",
            retryable=False,
        )

        with (
            patch.object(self.manager, "_show_failure") as show_failure,
            patch("src.ui.update_manager.capture_exception") as capture,
            patch("src.ui.update_manager.track_event") as track,
        ):
            self.manager._on_download_finished(UpdateResult.failed(failure))

        show_failure.assert_not_called()
        capture.assert_not_called()
        track.assert_called_once_with("update_download_cancelled")

    def test_download_failure_keeps_its_domain_state(self):
        error = OSError("disk full")
        failure = UpdateFailure(
            stage=UpdateStage.SAVE,
            kind=UpdateFailureKind.STORAGE,
            detail=str(error),
            retryable=True,
            cause=error,
        )

        with (
            patch.object(self.manager, "_show_failure") as show_failure,
            patch("src.ui.update_manager.capture_exception") as capture,
            patch("src.ui.update_manager.track_event") as track,
        ):
            self.manager._on_download_finished(UpdateResult.failed(failure))

        show_failure.assert_called_once_with(failure)
        capture.assert_called_once_with(error, "update_download")
        track.assert_called_once_with(
            "update_failed",
            stage="save",
            reason="storage",
        )

    def test_failed_check_does_not_consume_daily_check_interval(self):
        failure = UpdateFailure(
            stage=UpdateStage.CHECK,
            kind=UpdateFailureKind.NETWORK,
            detail="offline",
            retryable=True,
        )
        self.manager._silent = False

        with (
            patch.object(self.manager, "_show_failure") as show_failure,
            patch("src.ui.update_manager.save_env_settings") as save,
            patch("src.ui.update_manager.capture_exception"),
            patch("src.ui.update_manager.track_event"),
        ):
            self.manager._on_check_finished(UpdateResult.failed(failure))

        save.assert_not_called()
        show_failure.assert_called_once_with(failure)

    def test_verified_installer_moves_to_ready_state(self):
        installer = Path("MeetingNoteSetup-v0.4.0.exe")

        with patch.object(self.manager, "_prompt_to_install") as prompt:
            self.manager._on_download_finished(UpdateResult.success(installer))

        self.assertEqual(self.manager._downloaded_installer, installer)
        prompt.assert_called_once_with(installer)


if __name__ == "__main__":
    unittest.main()
