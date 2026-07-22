"""One-time privacy choice for anonymous analytics and crash reports."""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from src.ui.i18n import tr
from src.ui.theme import TEXT_SECONDARY, TEXT_TERTIARY
from src.utils.config import save_env_settings


class PrivacyChoiceDialog(QDialog):
    """Ask once and keep both optional data-sharing choices off by default."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Приватность и улучшение приложения"))
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        title = QLabel(tr("Вы решаете, чем делиться"))
        title.setStyleSheet("font-size: 23px; font-weight: 700;")
        layout.addWidget(title)

        intro = QLabel(
            tr(
                "Оба пункта необязательны и выключены по умолчанию. "
                "Meeting Note никогда не отправляет записи, расшифровки, "
                "саммари, имена встреч, API-ключи или логи."
            )
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(intro)

        self.analytics_checkbox = QCheckBox(
            tr("Отправлять анонимные этапы воронки")
        )
        self.analytics_checkbox.setToolTip(
            tr("Запуск, запись, готовая расшифровка и готовое саммари — без содержимого встречи.")
        )
        layout.addWidget(self.analytics_checkbox)

        self.crash_checkbox = QCheckBox(tr("Отправлять очищенные отчёты о сбоях"))
        self.crash_checkbox.setToolTip(
            tr("Технический тип ошибки и версия приложения — без логов и локальных данных.")
        )
        layout.addWidget(self.crash_checkbox)

        note = QLabel(
            tr(
                "Разрешённые события отправляются в закрытые Google Forms. "
                "Настройки можно изменить позже: Файл → Настройки → Приватность."
            )
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"font-size: 12px; color: {TEXT_TERTIARY};")
        layout.addWidget(note)

        buttons = QDialogButtonBox()
        no_thanks = QPushButton(tr("Не отправлять"))
        save = QPushButton(tr("Сохранить выбор"))
        save.setDefault(True)
        no_thanks.clicked.connect(self._decline)
        save.clicked.connect(self._save)
        buttons.addButton(no_thanks, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.addButton(save, QDialogButtonBox.ButtonRole.AcceptRole)
        layout.addWidget(buttons)

    def _save(self) -> None:
        self._persist(
            self.analytics_checkbox.isChecked(),
            self.crash_checkbox.isChecked(),
        )

    def _decline(self) -> None:
        self._persist(False, False)

    def _persist(self, analytics: bool, crashes: bool) -> None:
        save_env_settings(
            {
                "PRIVACY_CHOICE_COMPLETED": True,
                "ANONYMOUS_ANALYTICS_ENABLED": analytics,
                "CRASH_REPORTS_ENABLED": crashes,
            }
        )
        self.accept()

    def reject(self) -> None:
        self._decline()
