"""Background update checks with verified, user-confirmed installation."""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

from src import __version__
from src.ui.i18n import tr
from src.utils.config import get_settings, save_env_settings
from src.utils.telemetry import capture_exception, track_event
from src.utils.updater import (
    UpdateInfo,
    check_for_update,
    download_verified_update,
    should_check_for_updates,
)


class UpdateCheckWorker(QThread):
    finished = pyqtSignal(object)

    def run(self) -> None:
        try:
            self.finished.emit(check_for_update(__version__))
        except Exception as error:
            self.finished.emit(error)


class UpdateDownloadWorker(QThread):
    finished = pyqtSignal(object)

    def __init__(self, update: UpdateInfo):
        super().__init__()
        self.update = update

    def run(self) -> None:
        try:
            destination = Path(tempfile.gettempdir()) / "MeetingNote" / "updates"
            self.finished.emit(
                download_verified_update(
                    self.update,
                    destination,
                    cancel_requested=self.isInterruptionRequested,
                )
            )
        except Exception as error:
            self.finished.emit(error)


class UpdateManager(QObject):
    """Own worker lifetimes and keep every install step visible to the user."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self._check_worker: Optional[UpdateCheckWorker] = None
        self._download_worker: Optional[UpdateDownloadWorker] = None
        self._pending_update: Optional[UpdateInfo] = None
        self._silent = True

    def check(self, *, silent: bool, force: bool = False) -> None:
        settings = get_settings()
        if silent and not settings.update_checks_enabled:
            return
        if not force and not should_check_for_updates(settings.last_update_check_epoch):
            return
        if self._check_worker and self._check_worker.isRunning():
            return

        self._silent = silent
        self._check_worker = UpdateCheckWorker()
        self._check_worker.finished.connect(self._on_check_finished)
        self._check_worker.start()

    def _on_check_finished(self, result: object) -> None:
        worker = self._check_worker
        self._check_worker = None
        if worker:
            worker.deleteLater()
        save_env_settings({"LAST_UPDATE_CHECK_EPOCH": int(time.time())})

        if isinstance(result, Exception):
            capture_exception(result, "update_check")
            if not self._silent:
                QMessageBox.warning(
                    self.parent_window,
                    tr("Не удалось проверить обновления"),
                    tr("Проверьте подключение к интернету и повторите позже."),
                )
            return

        if result is None:
            if not self._silent:
                QMessageBox.information(
                    self.parent_window,
                    tr("Обновления"),
                    tr("У вас установлена последняя версия Meeting Note."),
                )
            return

        self._pending_update = result
        track_event("update_available", version=result.version)
        prompt = QMessageBox(self.parent_window)
        prompt.setWindowTitle(tr("Доступно обновление"))
        prompt.setText(
            tr(
                "Meeting Note {version} готов к установке. Скачать файл и проверить SHA-256?",
                version=result.version,
            )
        )
        download = prompt.addButton(
            tr("Скачать и установить"), QMessageBox.ButtonRole.AcceptRole
        )
        prompt.addButton(tr("Позже"), QMessageBox.ButtonRole.RejectRole)
        prompt.exec()
        if prompt.clickedButton() is download:
            self._download(result)

    def _download(self, update: UpdateInfo) -> None:
        if self._download_worker and self._download_worker.isRunning():
            return
        self._download_worker = UpdateDownloadWorker(update)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.start()

    def _on_download_finished(self, result: object) -> None:
        worker = self._download_worker
        self._download_worker = None
        if worker:
            worker.deleteLater()

        if isinstance(result, Exception):
            capture_exception(result, "update_download")
            QMessageBox.warning(
                self.parent_window,
                tr("Не удалось скачать обновление"),
                tr("Файл не был запущен. Откройте страницу релиза и попробуйте позже."),
            )
            return

        installer = Path(result)
        if installer.suffix.lower() != ".exe":
            QMessageBox.information(
                self.parent_window,
                tr("Обновление скачано"),
                tr("Архив проверен и сохранён:\n{path}", path=installer),
            )
            return

        answer = QMessageBox.question(
            self.parent_window,
            tr("Установить обновление"),
            tr(
                "SHA-256 совпал с опубликованной контрольной суммой. "
                "Закрыть Meeting Note и запустить установщик?"
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            subprocess.Popen([str(installer)], close_fds=True)
            track_event("update_installer_launched")
            QApplication.quit()
        except Exception as error:
            capture_exception(error, "update_launch")
            QMessageBox.warning(
                self.parent_window,
                tr("Не удалось запустить установщик"),
                str(error),
            )

    def cleanup(self) -> None:
        """Avoid leaving Qt workers alive while the application exits."""
        for worker in (self._check_worker, self._download_worker):
            if worker and worker.isRunning():
                worker.requestInterruption()
                worker.wait(11000)
