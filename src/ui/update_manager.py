"""Background update checks with verified, user-confirmed installation."""

from __future__ import annotations

import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from src import __version__
from src.ui.i18n import tr
from src.utils.config import get_settings, save_env_settings
from src.utils.telemetry import capture_exception, track_event
from src.utils.updater import (
    RELEASES_PAGE_URL,
    UpdateFailure,
    UpdateFailureKind,
    UpdateInfo,
    UpdateResult,
    UpdateStage,
    check_for_update,
    classify_update_failure,
    download_verified_update,
    should_check_for_updates,
)


@dataclass(frozen=True)
class UpdateFailurePresentation:
    title: str
    message: str
    retry_label: Optional[str]


def failure_presentation(failure: UpdateFailure) -> UpdateFailurePresentation:
    """Return precise copy and the action that can recover the failed stage."""
    if failure.stage == UpdateStage.CHECK:
        if failure.kind == UpdateFailureKind.NETWORK:
            message = tr(
                "Не удалось связаться с GitHub Releases. "
                "Проверьте подключение и повторите проверку."
            )
        else:
            message = tr(
                "Не удалось прочитать данные последнего релиза. "
                "Установщик не скачивался и не запускался."
            )
        return UpdateFailurePresentation(
            title=tr("Не удалось проверить обновления"),
            message=message,
            retry_label=tr("Повторить проверку") if failure.retryable else None,
        )

    if failure.kind == UpdateFailureKind.NETWORK:
        return UpdateFailurePresentation(
            title=tr("Загрузка прервана"),
            message=tr(
                "Соединение прервалось во время загрузки обновления. "
                "Неполный файл удалён, установщик не запускался."
            ),
            retry_label=tr("Повторить загрузку"),
        )
    if failure.kind == UpdateFailureKind.RELEASE:
        return UpdateFailurePresentation(
            title=tr("Релиз не готов к установке"),
            message=tr(
                "В релизе нет совместимого установщика или корректной "
                "контрольной суммы. Установщик не запускался."
            ),
            retry_label=None,
        )
    if failure.kind == UpdateFailureKind.INTEGRITY:
        return UpdateFailurePresentation(
            title=tr("Проверка обновления не пройдена"),
            message=tr(
                "Скачанный файл не совпал с файлом из релиза. "
                "Он удалён, установщик не запускался."
            ),
            retry_label=tr("Повторить загрузку"),
        )
    if failure.kind == UpdateFailureKind.STORAGE:
        return UpdateFailurePresentation(
            title=tr("Не удалось сохранить обновление"),
            message=tr(
                "Meeting Note не смог сохранить файл обновления. "
                "Проверьте свободное место на диске и повторите загрузку."
            ),
            retry_label=tr("Повторить загрузку"),
        )
    if failure.kind == UpdateFailureKind.LAUNCH:
        return UpdateFailurePresentation(
            title=tr("Не удалось запустить установщик"),
            message=tr(
                "Обновление скачано и проверено, но Windows не запустила "
                "установщик. Файл сохранён и готов к повторному запуску."
            ),
            retry_label=tr("Запустить снова"),
        )
    return UpdateFailurePresentation(
        title=tr("Не удалось подготовить обновление"),
        message=tr(
            "Обновление не было подготовлено, установщик не запускался. "
            "Повторите загрузку или откройте страницу релиза."
        ),
        retry_label=tr("Повторить загрузку") if failure.retryable else None,
    )


class UpdateCheckWorker(QThread):
    finished = Signal(object)

    def run(self) -> None:
        try:
            result = UpdateResult.success(check_for_update(__version__))
        except Exception as error:
            result = UpdateResult.failed(
                classify_update_failure(error, UpdateStage.CHECK)
            )
        self.finished.emit(result)


class UpdateDownloadWorker(QThread):
    finished = Signal(object)

    def __init__(self, update: UpdateInfo):
        super().__init__()
        self.update = update

    def run(self) -> None:
        try:
            destination = Path(tempfile.gettempdir()) / "MeetingNote" / "updates"
            result = UpdateResult.success(
                download_verified_update(
                    self.update,
                    destination,
                    cancel_requested=self.isInterruptionRequested,
                )
            )
        except Exception as error:
            result = UpdateResult.failed(
                classify_update_failure(error, UpdateStage.DOWNLOAD)
            )
        self.finished.emit(result)


class UpdateManager(QObject):
    """Own worker lifetimes and keep every install step visible to the user."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self._check_worker: Optional[UpdateCheckWorker] = None
        self._download_worker: Optional[UpdateDownloadWorker] = None
        self._download_progress: Optional[QProgressDialog] = None
        self._pending_update: Optional[UpdateInfo] = None
        self._downloaded_installer: Optional[Path] = None
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

        typed_result = self._typed_result(result, UpdateStage.CHECK)
        if typed_result.failure:
            self._capture_failure(typed_result.failure, "update_check")
            if not self._silent:
                self._show_failure(typed_result.failure)
            return

        save_env_settings({"LAST_UPDATE_CHECK_EPOCH": int(time.time())})
        update = typed_result.value
        if update is None:
            if not self._silent:
                QMessageBox.information(
                    self.parent_window,
                    tr("Обновления"),
                    tr("У вас установлена последняя версия Meeting Note."),
                )
            return

        if not isinstance(update, UpdateInfo):
            failure = classify_update_failure(
                TypeError("Update check returned an invalid value"),
                UpdateStage.CHECK,
            )
            self._capture_failure(failure, "update_check")
            if not self._silent:
                self._show_failure(failure)
            return

        self._pending_update = update
        track_event("update_available", version=update.version)
        prompt = QMessageBox(self.parent_window)
        prompt.setWindowTitle(tr("Доступно обновление"))
        prompt.setText(
            tr(
                "Доступна Meeting Note {version}. Скачать обновление? "
                "Перед установкой приложение проверит файл.",
                version=update.version,
            )
        )
        download = prompt.addButton(
            tr("Скачать обновление"), QMessageBox.ButtonRole.AcceptRole
        )
        prompt.addButton(tr("Позже"), QMessageBox.ButtonRole.RejectRole)
        prompt.exec()
        if prompt.clickedButton() is download:
            self._download(update)

    def _download(self, update: UpdateInfo) -> None:
        if self._download_worker and self._download_worker.isRunning():
            return
        self._pending_update = update
        self._downloaded_installer = None
        self._download_worker = UpdateDownloadWorker(update)
        self._download_worker.finished.connect(self._on_download_finished)
        self._show_download_progress(update, self._download_worker)
        self._download_worker.start()

    def _on_download_finished(self, result: object) -> None:
        worker = self._download_worker
        self._download_worker = None
        if worker:
            worker.deleteLater()
        self._close_download_progress()

        typed_result = self._typed_result(result, UpdateStage.DOWNLOAD)
        if typed_result.failure:
            if typed_result.failure.kind == UpdateFailureKind.CANCELLED:
                track_event("update_download_cancelled")
                return
            self._capture_failure(typed_result.failure, "update_download")
            self._show_failure(typed_result.failure)
            return

        if not isinstance(typed_result.value, (str, Path)):
            failure = classify_update_failure(
                TypeError("Update download returned an invalid path"),
                UpdateStage.DOWNLOAD,
            )
            self._capture_failure(failure, "update_download")
            self._show_failure(failure)
            return

        installer = Path(typed_result.value)
        if installer.suffix.lower() != ".exe":
            QMessageBox.information(
                self.parent_window,
                tr("Обновление скачано"),
                tr("Архив проверен и сохранён:\n{path}", path=installer),
            )
            return

        self._downloaded_installer = installer
        self._prompt_to_install(installer)

    def _prompt_to_install(self, installer: Path) -> None:
        prompt = QMessageBox(self.parent_window)
        prompt.setWindowTitle(tr("Обновление готово"))
        prompt.setText(
            tr(
                "Обновление скачано и проверено. "
                "Закрыть Meeting Note и установить новую версию?"
            )
        )
        install = prompt.addButton(
            tr("Закрыть и установить"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        prompt.addButton(tr("Позже"), QMessageBox.ButtonRole.RejectRole)
        prompt.exec()
        if prompt.clickedButton() is install:
            self._launch_installer(installer)

    def _launch_installer(self, installer: Path) -> None:
        try:
            subprocess.Popen([str(installer)], close_fds=True)
            track_event("update_installer_launched")
            QApplication.quit()
        except Exception as error:
            failure = classify_update_failure(error, UpdateStage.LAUNCH)
            self._capture_failure(failure, "update_launch")
            self._show_failure(failure)

    def _show_download_progress(
        self,
        update: UpdateInfo,
        worker: UpdateDownloadWorker,
    ) -> None:
        progress = QProgressDialog(
            tr("Скачиваем Meeting Note {version}…", version=update.version),
            tr("Отменить"),
            0,
            0,
            self.parent_window,
        )
        progress.setWindowTitle(tr("Скачивание обновления"))
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.canceled.connect(worker.requestInterruption)
        self._download_progress = progress
        progress.show()

    def _close_download_progress(self) -> None:
        progress = self._download_progress
        self._download_progress = None
        if progress:
            progress.close()
            progress.deleteLater()

    def _show_failure(self, failure: UpdateFailure) -> None:
        presentation = failure_presentation(failure)
        prompt = QMessageBox(self.parent_window)
        prompt.setIcon(QMessageBox.Icon.Warning)
        prompt.setWindowTitle(presentation.title)
        prompt.setText(presentation.message)

        retry = None
        if presentation.retry_label:
            retry = prompt.addButton(
                presentation.retry_label,
                QMessageBox.ButtonRole.AcceptRole,
            )
        release = prompt.addButton(
            tr("Открыть страницу релиза"),
            QMessageBox.ButtonRole.ActionRole,
        )
        prompt.addButton(tr("Закрыть"), QMessageBox.ButtonRole.RejectRole)
        prompt.exec()

        clicked = prompt.clickedButton()
        if retry is not None and clicked is retry:
            self._retry_stage(failure.stage)
        elif clicked is release:
            self._open_release_page()

    def _retry_stage(self, stage: UpdateStage) -> None:
        if stage == UpdateStage.CHECK:
            self.check(silent=False, force=True)
        elif stage == UpdateStage.LAUNCH and self._downloaded_installer:
            self._launch_installer(self._downloaded_installer)
        elif self._pending_update:
            self._download(self._pending_update)

    def _open_release_page(self) -> None:
        release_url = (
            self._pending_update.release_url
            if self._pending_update
            else RELEASES_PAGE_URL
        )
        QDesktopServices.openUrl(QUrl(release_url))

    @staticmethod
    def _typed_result(result: object, stage: UpdateStage) -> UpdateResult[object]:
        if isinstance(result, UpdateResult):
            return result
        failure = classify_update_failure(
            TypeError("Update worker returned an invalid result"),
            stage,
        )
        return UpdateResult.failed(failure)

    @staticmethod
    def _capture_failure(failure: UpdateFailure, telemetry_stage: str) -> None:
        error = failure.cause or RuntimeError(failure.detail)
        capture_exception(error, telemetry_stage)
        track_event(
            "update_failed",
            stage=failure.stage.value,
            reason=failure.kind.value,
        )

    def cleanup(self) -> None:
        """Avoid leaving Qt workers alive while the application exits."""
        self._close_download_progress()
        for worker in (self._check_worker, self._download_worker):
            if worker and worker.isRunning():
                worker.requestInterruption()
                worker.wait(11000)
