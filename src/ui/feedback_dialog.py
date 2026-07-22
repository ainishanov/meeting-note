"""Privacy-safe routes for product feedback and support."""

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.ui.i18n import tr
from src.ui.theme import (
    ACCENT_PRIMARY,
    ACCENT_PRIMARY_HOVER,
    ACCENT_SECONDARY,
    BG_SURFACE_2,
    BORDER_DEFAULT,
    RADIUS_LG,
    RADIUS_MD,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TEXT_TERTIARY,
)


FEATURE_REQUEST_URL = (
    "https://github.com/ainishanov/meeting-note/issues/new"
    "?template=feature_request.yml"
)
BUG_REPORT_URL = (
    "https://github.com/ainishanov/meeting-note/issues/new"
    "?template=bug_report.yml"
)
DISCUSSIONS_URL = "https://github.com/ainishanov/meeting-note/discussions/new/choose"


class FeedbackDialog(QDialog):
    """Let users choose the right public feedback channel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle(tr("Обратная связь"))
        self.setModal(True)
        self.setMinimumSize(600, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 24)
        root.setSpacing(14)

        title = QLabel(tr("Помогите сделать Meeting Note лучше"))
        title.setWordWrap(True)
        title.setStyleSheet(
            f"font-size: 27px; font-weight: 700; color: {TEXT_PRIMARY};"
        )
        root.addWidget(title)

        subtitle = QLabel(
            tr(
                "Выберите, что хотите отправить. GitHub откроется, чтобы вы "
                "могли проверить текст перед публикацией."
            )
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"font-size: 14px; color: {TEXT_SECONDARY};")
        root.addWidget(subtitle)

        self.feature_button = self._add_route(
            root,
            title=tr("Предложить улучшение"),
            description=tr("Расскажите, какой результат или сценарий стоит улучшить."),
            button_text=tr("Предложить улучшение"),
            url=FEATURE_REQUEST_URL,
            accent=ACCENT_PRIMARY,
            primary=True,
        )
        self.bug_button = self._add_route(
            root,
            title=tr("Сообщить о проблеме"),
            description=tr("Опишите, что сломалось и как это повторить."),
            button_text=tr("Сообщить о проблеме"),
            url=BUG_REPORT_URL,
            accent=ACCENT_SECONDARY,
        )
        self.discussion_button = self._add_route(
            root,
            title=tr("Обсудить идею"),
            description=tr("Задайте вопрос или поделитесь свободной обратной связью."),
            button_text=tr("Открыть обсуждения"),
            url=DISCUSSIONS_URL,
            accent=TEXT_SECONDARY,
        )

        privacy = QLabel(
            tr(
                "Meeting Note не прикрепляет записи, расшифровки, API-ключи или логи."
            )
        )
        privacy.setWordWrap(True)
        privacy.setStyleSheet(f"font-size: 12px; color: {TEXT_TERTIARY};")
        root.addWidget(privacy)

        footer = QHBoxLayout()
        footer.addStretch()
        close_button = QPushButton(tr("Закрыть"))
        close_button.clicked.connect(self.reject)
        footer.addWidget(close_button)
        root.addLayout(footer)

    def _add_route(
        self,
        parent_layout: QVBoxLayout,
        *,
        title: str,
        description: str,
        button_text: str,
        url: str,
        accent: str,
        primary: bool = False,
    ) -> QPushButton:
        card = QFrame()
        card.setObjectName("feedbackCard")
        card.setStyleSheet(
            f"QFrame#feedbackCard {{ background-color: {BG_SURFACE_2}; "
            f"border: 1px solid {BORDER_DEFAULT}; border-radius: {RADIUS_LG}px; }}"
            "QFrame#feedbackCard QLabel { background: transparent; border: none; }"
        )
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 15, 16, 15)
        layout.setSpacing(16)

        copy = QVBoxLayout()
        copy.setSpacing(4)
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {accent};"
        )
        copy.addWidget(title_label)
        description_label = QLabel(description)
        description_label.setWordWrap(True)
        description_label.setStyleSheet(
            f"font-size: 12px; color: {TEXT_SECONDARY};"
        )
        copy.addWidget(description_label)
        layout.addLayout(copy, stretch=1)

        button = QPushButton(button_text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumWidth(170)
        if primary:
            button.setStyleSheet(
                f"QPushButton {{ background-color: {ACCENT_PRIMARY}; color: #ffffff; "
                f"border-radius: {RADIUS_MD}px; padding: 10px 16px; font-weight: 600; }}"
                f"QPushButton:hover {{ background-color: {ACCENT_PRIMARY_HOVER}; }}"
            )
        else:
            button.setStyleSheet(
                f"QPushButton {{ background-color: transparent; color: {TEXT_PRIMARY}; "
                f"border: 1px solid {BORDER_DEFAULT}; border-radius: {RADIUS_MD}px; "
                "padding: 9px 15px; font-weight: 600; }"
                f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
            )
        button.clicked.connect(lambda _checked=False, route=url: self._open_route(route))
        layout.addWidget(button)
        parent_layout.addWidget(card)
        return button

    def _open_route(self, url: str) -> None:
        if QDesktopServices.openUrl(QUrl(url)):
            self.accept()
            return

        QMessageBox.warning(
            self,
            tr("Не удалось открыть ссылку"),
            tr("Откройте страницу вручную: {url}", url=url),
        )
