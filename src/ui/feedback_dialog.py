"""Direct privacy-safe feedback with public technical fallbacks."""

from __future__ import annotations

import urllib.parse
import urllib.request
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from src import __version__
from src.ui.i18n import tr
from src.ui.theme import (
    ACCENT_PRIMARY,
    ACCENT_PRIMARY_HOVER,
    BG_SURFACE_2,
    BORDER_DEFAULT,
    RADIUS_LG,
    RADIUS_MD,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TEXT_TERTIARY,
)
from src.utils.telemetry import capture_exception, track_event


FEATURE_REQUEST_URL = (
    "https://github.com/ainishanov/meeting-note/issues/new"
    "?template=feature_request.yml"
)
BUG_REPORT_URL = (
    "https://github.com/ainishanov/meeting-note/issues/new"
    "?template=bug_report.yml"
)
DISCUSSIONS_URL = "https://github.com/ainishanov/meeting-note/discussions/new/choose"
FEEDBACK_FORM_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSdlkV9OsGjm5HNkaHLT-vS_ScPZTcuEKLYJJteSF1Hbpf1ojQ/viewform"
)
FEEDBACK_SUBMIT_URL = FEEDBACK_FORM_URL.replace("/viewform", "/formResponse")
_CATEGORY_FIELD = "entry.1121103253"
_MESSAGE_FIELD = "entry.1258727091"
_CONTACT_FIELD = "entry.450011572"
_CATEGORY_VALUES = {
    "bug": "Bug / Ошибка",
    "feature": "Feature request / Идея",
    "general": "General feedback / Общий отзыв",
}


def submit_feedback(
    category: str,
    message: str,
    contact: str = "",
    timeout: float = 8.0,
) -> None:
    """Submit user-authored feedback without collecting their Google account email."""
    if category not in _CATEGORY_VALUES:
        raise ValueError("Unsupported feedback category")
    clean_message = message.strip()
    if len(clean_message) < 5:
        raise ValueError("Feedback is too short")

    payload = urllib.parse.urlencode(
        {
            _CATEGORY_FIELD: _CATEGORY_VALUES[category],
            _MESSAGE_FIELD: f"[Meeting Note v{__version__}]\n{clean_message}",
            _CONTACT_FIELD: contact.strip()[:240],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        FEEDBACK_SUBMIT_URL,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": f"MeetingNote/{__version__}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read(256)


class FeedbackSubmitWorker(QThread):
    finished = pyqtSignal(object)

    def __init__(self, category: str, message: str, contact: str):
        super().__init__()
        self.category = category
        self.message = message
        self.contact = contact

    def run(self) -> None:
        try:
            submit_feedback(self.category, self.message, self.contact)
            self.finished.emit(True)
        except Exception as error:
            self.finished.emit(error)


class FeedbackDialog(QDialog):
    """Collect a short response directly and keep GitHub for public technical work."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[FeedbackSubmitWorker] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle(tr("Обратная связь"))
        self.setModal(True)
        self.setMinimumSize(650, 610)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 24)
        root.setSpacing(13)

        title = QLabel(tr("Помогите сделать Meeting Note лучше"))
        title.setWordWrap(True)
        title.setStyleSheet(
            f"font-size: 27px; font-weight: 700; color: {TEXT_PRIMARY};"
        )
        root.addWidget(title)

        subtitle = QLabel(
            tr(
                "Отправьте короткий отзыв прямо из приложения. Аккаунт GitHub "
                "или Google не нужен, адрес аккаунта не собирается."
            )
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"font-size: 14px; color: {TEXT_SECONDARY};")
        root.addWidget(subtitle)

        form = QFrame()
        form.setObjectName("feedbackForm")
        form.setStyleSheet(
            f"QFrame#feedbackForm {{ background-color: {BG_SURFACE_2}; "
            f"border: 1px solid {BORDER_DEFAULT}; border-radius: {RADIUS_LG}px; }}"
        )
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(18, 16, 18, 16)
        form_layout.setSpacing(9)

        self.category_combo = QComboBox()
        self.category_combo.addItem(tr("Общий отзыв"), "general")
        self.category_combo.addItem(tr("Предложить улучшение"), "feature")
        self.category_combo.addItem(tr("Сообщить о проблеме"), "bug")
        form_layout.addWidget(self.category_combo)

        self.message_input = QPlainTextEdit()
        self.message_input.setPlaceholderText(
            tr("Что получилось хорошо? Что мешает? Что стоит изменить?")
        )
        self.message_input.setMinimumHeight(130)
        form_layout.addWidget(self.message_input)

        self.contact_input = QLineEdit()
        self.contact_input.setPlaceholderText(
            tr("Email или Telegram для ответа — необязательно")
        )
        form_layout.addWidget(self.contact_input)

        self.privacy_checkbox = QCheckBox(
            tr("В отзыве нет записей, расшифровок, API-ключей или личных данных")
        )
        form_layout.addWidget(self.privacy_checkbox)

        actions = QHBoxLayout()
        self.fallback_button = QPushButton(tr("Открыть форму в браузере"))
        self.fallback_button.clicked.connect(
            lambda: self._open_route(FEEDBACK_FORM_URL)
        )
        actions.addWidget(self.fallback_button)
        actions.addStretch()
        self.submit_button = QPushButton(tr("Отправить отзыв"))
        self.submit_button.clicked.connect(self._submit)
        self.submit_button.setStyleSheet(
            f"QPushButton {{ background-color: {ACCENT_PRIMARY}; color: #ffffff; "
            f"border-radius: {RADIUS_MD}px; padding: 10px 18px; font-weight: 600; }}"
            f"QPushButton:hover {{ background-color: {ACCENT_PRIMARY_HOVER}; }}"
        )
        actions.addWidget(self.submit_button)
        form_layout.addLayout(actions)
        root.addWidget(form)

        technical = QLabel(tr("Публичные технические каналы"))
        technical.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {TEXT_TERTIARY};"
        )
        root.addWidget(technical)

        routes = QHBoxLayout()
        self.feature_button = self._route_button(
            tr("Feature request"), FEATURE_REQUEST_URL
        )
        self.bug_button = self._route_button(tr("Bug report"), BUG_REPORT_URL)
        self.discussion_button = self._route_button(
            tr("Discussion"), DISCUSSIONS_URL
        )
        routes.addWidget(self.feature_button)
        routes.addWidget(self.bug_button)
        routes.addWidget(self.discussion_button)
        root.addLayout(routes)

        privacy = QLabel(
            tr(
                "Текст и необязательный контакт сохраняются в закрытой Google Form. "
                "Meeting Note не прикрепляет записи, расшифровки, API-ключи или логи."
            )
        )
        privacy.setWordWrap(True)
        privacy.setStyleSheet(f"font-size: 11px; color: {TEXT_TERTIARY};")
        root.addWidget(privacy)

    def _route_button(self, text: str, url: str) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, route=url: self._open_route(route))
        return button

    def _submit(self) -> None:
        message = self.message_input.toPlainText().strip()
        if len(message) < 5:
            QMessageBox.warning(
                self,
                tr("Добавьте пару слов"),
                tr("Опишите, что получилось или что стоит изменить."),
            )
            return
        if not self.privacy_checkbox.isChecked():
            QMessageBox.warning(
                self,
                tr("Проверьте приватность"),
                tr("Подтвердите, что отзыв не содержит данных встречи или секретов."),
            )
            return

        self.submit_button.setEnabled(False)
        self.submit_button.setText(tr("Отправляю..."))
        self._worker = FeedbackSubmitWorker(
            self.category_combo.currentData(),
            message,
            self.contact_input.text(),
        )
        self._worker.finished.connect(self._on_submit_finished)
        self._worker.start()

    def _on_submit_finished(self, result: object) -> None:
        worker = self._worker
        self._worker = None
        if worker:
            worker.deleteLater()
        self.submit_button.setEnabled(True)
        self.submit_button.setText(tr("Отправить отзыв"))

        if isinstance(result, Exception):
            capture_exception(result, "feedback_submit")
            QMessageBox.warning(
                self,
                tr("Не удалось отправить отзыв"),
                tr("Откройте форму в браузере или повторите позже."),
            )
            return

        track_event("feedback_submitted", category=self.category_combo.currentData())
        QMessageBox.information(
            self,
            tr("Спасибо"),
            tr("Отзыв отправлен. Спасибо, что помогаете улучшать Meeting Note."),
        )
        self.accept()

    def _open_route(self, url: str) -> None:
        if url == FEEDBACK_FORM_URL:
            track_event("feedback_form_opened")
        if QDesktopServices.openUrl(QUrl(url)):
            return
        QMessageBox.warning(
            self,
            tr("Не удалось открыть ссылку"),
            tr("Откройте страницу вручную: {url}", url=url),
        )

    def reject(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        super().reject()
