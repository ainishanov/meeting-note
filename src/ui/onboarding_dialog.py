"""Guided first-run setup for a successful first meeting."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.ui.i18n import SUPPORTED_LANGUAGES, tr
from src.ui.settings_dialog import AudioTestWorker
from src.ui.theme import (
    ACCENT_PRIMARY,
    ACCENT_PRIMARY_HOVER,
    BG_SURFACE_1,
    BG_SURFACE_2,
    BORDER_DEFAULT,
    RADIUS_LG,
    RADIUS_MD,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TEXT_TERTIARY,
)
from src.utils.config import get_settings, reload_settings, save_env_settings
from src.utils.security import (
    get_microphone_settings,
    get_openai_api_key,
    get_openrouter_api_key,
    set_microphone_settings,
    set_openai_api_key,
    set_openrouter_api_key,
)


class OnboardingDialog(QDialog):
    """Four short steps that leave recording, audio, and AI ready to use."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = get_settings()
        self._audio_test_worker: Optional[AudioTestWorker] = None
        self._setup_ui()
        self._load_current_values()
        self._set_page(0)

    def _setup_ui(self) -> None:
        self.setWindowTitle(tr("Настройка Meeting Note"))
        self.setModal(True)
        self.setMinimumSize(720, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        top_row = QHBoxLayout()
        brand = QLabel("Meeting Note")
        brand.setStyleSheet(
            f"font-size: 15px; font-weight: 700; color: {TEXT_PRIMARY};"
        )
        top_row.addWidget(brand)
        top_row.addStretch()
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(
            f"font-size: 12px; color: {TEXT_TERTIARY};"
        )
        top_row.addWidget(self.progress_label)
        root.addLayout(top_row)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._create_welcome_page())
        self.stack.addWidget(self._create_ai_page())
        self.stack.addWidget(self._create_audio_page())
        self.stack.addWidget(self._create_ready_page())
        root.addWidget(self.stack, stretch=1)

        nav = QHBoxLayout()
        nav.setSpacing(10)
        self.skip_button = QPushButton(tr("Настроить позже"))
        self.skip_button.clicked.connect(self.reject)
        self.skip_button.setStyleSheet(self._secondary_button_style())
        nav.addWidget(self.skip_button)
        nav.addStretch()

        self.back_button = QPushButton(tr("Назад"))
        self.back_button.clicked.connect(self._previous_page)
        self.back_button.setStyleSheet(self._secondary_button_style())
        nav.addWidget(self.back_button)

        self.next_button = QPushButton(tr("Далее"))
        self.next_button.clicked.connect(self._next_page)
        self.next_button.setDefault(True)
        self.next_button.setStyleSheet(self._primary_button_style())
        nav.addWidget(self.next_button)
        root.addLayout(nav)

    def _page_shell(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 20, 0, 10)
        layout.setSpacing(16)

        title_label = QLabel(title)
        title_label.setWordWrap(True)
        title_label.setStyleSheet(
            f"font-size: 30px; font-weight: 700; color: {TEXT_PRIMARY};"
        )
        layout.addWidget(title_label)

        subtitle_label = QLabel(subtitle)
        subtitle_label.setWordWrap(True)
        subtitle_label.setStyleSheet(
            f"font-size: 14px; color: {TEXT_SECONDARY}; line-height: 1.5;"
        )
        layout.addWidget(subtitle_label)
        return page, layout

    def _create_welcome_page(self) -> QWidget:
        page, layout = self._page_shell(
            tr("Не теряйте решения после созвонов"),
            tr(
                "Meeting Note записывает звук компьютера и микрофона, создаёт "
                "расшифровку и превращает разговор в решения и задачи."
            ),
        )

        card = self._card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(10)
        language_label = QLabel(tr("Язык интерфейса"))
        language_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {TEXT_PRIMARY};"
        )
        card_layout.addWidget(language_label)

        self.language_combo = QComboBox()
        for code, label in SUPPORTED_LANGUAGES.items():
            self.language_combo.addItem(label, code)
        card_layout.addWidget(self.language_combo)
        layout.addWidget(card)

        benefits = QLabel(
            tr("✓ Без бота в звонке\n✓ Локальная история встреч\n✓ Zoom, Teams, Meet и Telemost")
        )
        benefits.setStyleSheet(
            f"font-size: 14px; color: {TEXT_SECONDARY}; line-height: 1.7;"
        )
        layout.addWidget(benefits)
        layout.addStretch()
        return page

    def _create_ai_page(self) -> QWidget:
        page, layout = self._page_shell(
            tr("Подключите AI"),
            tr(
                "OpenAI расшифровывает аудио. OpenRouter создаёт краткий итог, "
                "решения и задачи. Ключи хранятся в Windows Credential Manager."
            ),
        )

        card = self._card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(12)

        openai_label = QLabel("OpenAI API key")
        openai_label.setStyleSheet(f"font-weight: 600; color: {TEXT_PRIMARY};")
        card_layout.addWidget(openai_label)
        self.openai_key_input = QLineEdit()
        self.openai_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key_input.setPlaceholderText("sk-…")
        card_layout.addWidget(self.openai_key_input)

        openrouter_label = QLabel("OpenRouter API key")
        openrouter_label.setStyleSheet(f"font-weight: 600; color: {TEXT_PRIMARY};")
        card_layout.addWidget(openrouter_label)
        self.openrouter_key_input = QLineEdit()
        self.openrouter_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.openrouter_key_input.setPlaceholderText("sk-or-…")
        card_layout.addWidget(self.openrouter_key_input)

        links = QLabel(
            "<a href='https://platform.openai.com/api-keys'>OpenAI keys</a> · "
            "<a href='https://openrouter.ai/settings/keys'>OpenRouter keys</a>"
        )
        links.setOpenExternalLinks(True)
        links.setStyleSheet(f"font-size: 12px; color: {TEXT_TERTIARY};")
        card_layout.addWidget(links)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _create_audio_page(self) -> QWidget:
        page, layout = self._page_shell(
            tr("Проверьте звук до первой встречи"),
            tr(
                "Включите любой звук на компьютере и нажмите проверку. "
                "Meeting Note также проверит микрофон, если он включён."
            ),
        )

        card = self._card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(12)

        system_row = QHBoxLayout()
        system_row.addWidget(QLabel("🔊"))
        system_label = QLabel(tr("Системный звук — устройство Windows по умолчанию"))
        system_label.setStyleSheet(f"color: {TEXT_PRIMARY};")
        system_row.addWidget(system_label, stretch=1)
        card_layout.addLayout(system_row)

        self.mic_checkbox = QCheckBox(tr("Записывать микрофон вместе со звуком встречи"))
        self.mic_checkbox.setChecked(True)
        card_layout.addWidget(self.mic_checkbox)

        self.audio_test_button = QPushButton(tr("Проверить звук 3 секунды"))
        self.audio_test_button.clicked.connect(self._test_audio)
        self.audio_test_button.setStyleSheet(self._secondary_button_style())
        card_layout.addWidget(self.audio_test_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self.audio_result_label = QLabel(tr("Проверка ещё не запускалась"))
        self.audio_result_label.setWordWrap(True)
        self.audio_result_label.setStyleSheet(
            f"font-size: 12px; color: {TEXT_TERTIARY};"
        )
        card_layout.addWidget(self.audio_result_label)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _create_ready_page(self) -> QWidget:
        page, layout = self._page_shell(
            tr("Всё готово к первой встрече"),
            tr(
                "Когда Meeting Note заметит Zoom, Teams, Meet или Telemost, "
                "приложение предложит записать разговор."
            ),
        )

        checklist = self._card()
        checklist_layout = QVBoxLayout(checklist)
        checklist_layout.setContentsMargins(20, 18, 20, 18)
        checklist_layout.setSpacing(12)
        for text in (
            tr("✓ Запись системного звука"),
            tr("✓ Расшифровка и определение спикеров"),
            tr("✓ Решения и задачи сразу после встречи"),
            tr("✓ Поиск по истории разговоров"),
        ):
            label = QLabel(text)
            label.setStyleSheet(f"font-size: 14px; color: {TEXT_PRIMARY};")
            checklist_layout.addWidget(label)
        layout.addWidget(checklist)
        layout.addStretch()
        return page

    def _card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("onboardingCard")
        card.setStyleSheet(
            f"QFrame#onboardingCard {{ background-color: {BG_SURFACE_2}; border: 1px solid {BORDER_DEFAULT}; "
            f"border-radius: {RADIUS_LG}px; }}"
            "QFrame#onboardingCard QLabel, QFrame#onboardingCard QCheckBox "
            "{ background: transparent; border: none; }"
        )
        return card

    def _load_current_values(self) -> None:
        language_index = self.language_combo.findData(self.settings.app_language)
        if language_index >= 0:
            self.language_combo.setCurrentIndex(language_index)

        self.openai_key_input.setText(get_openai_api_key() or "")
        self.openrouter_key_input.setText(get_openrouter_api_key() or "")
        self.mic_checkbox.setChecked(self.settings.microphone_enabled)

    def _set_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.progress_label.setText(tr("Шаг {current} из {total}", current=index + 1, total=self.stack.count()))
        self.back_button.setVisible(index > 0)
        self.next_button.setText(
            tr("Открыть Meeting Note") if index == self.stack.count() - 1 else tr("Далее")
        )

    def _previous_page(self) -> None:
        self._set_page(max(0, self.stack.currentIndex() - 1))

    def _next_page(self) -> None:
        index = self.stack.currentIndex()
        if index == 1 and not self._api_keys_are_present():
            return
        if index == self.stack.count() - 1:
            self._finish_setup()
            return
        self._set_page(index + 1)

    def _api_keys_are_present(self) -> bool:
        if self.openai_key_input.text().strip() and self.openrouter_key_input.text().strip():
            return True
        QMessageBox.warning(
            self,
            tr("Нужны два API ключа"),
            tr("Добавьте ключи OpenAI и OpenRouter или выберите «Настроить позже»."),
        )
        return False

    def _test_audio(self) -> None:
        if self._audio_test_worker and self._audio_test_worker.isRunning():
            return

        self.audio_test_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.audio_result_label.setText(tr("Слушаю системный звук и микрофон…"))
        self._audio_test_worker = AudioTestWorker(
            output_dir=self.settings.recordings_dir,
            sample_rate=self.settings.sample_rate,
            channels=self.settings.channels,
            audio_device_index=self.settings.audio_device_index,
            microphone_enabled=self.mic_checkbox.isChecked(),
            microphone_device_index=self.settings.microphone_device_index,
            microphone_volume=self.settings.microphone_volume,
        )
        self._audio_test_worker.finished.connect(self._on_audio_test_finished)
        self._audio_test_worker.start()

    def _on_audio_test_finished(self, result) -> None:
        worker = self._audio_test_worker
        self._audio_test_worker = None
        if worker:
            worker.deleteLater()

        self.audio_test_button.setEnabled(True)
        self.skip_button.setEnabled(True)
        self.next_button.setEnabled(True)

        if isinstance(result, Exception):
            self.audio_result_label.setText(tr("Проверка не удалась: {error}", error=str(result)))
            return

        system_pct = int((result.get("system") or 0.0) * 100)
        microphone = result.get("microphone")
        mic_text = tr("выключен") if microphone is None else f"{int(microphone * 100)}%"
        if system_pct < 1 and (microphone is None or microphone < 0.01):
            self.audio_result_label.setText(
                tr(
                    "Сигнал не найден. Включите звук на компьютере и повторите. "
                    "Системный звук: {system_pct}%, микрофон: {mic_text}.",
                    system_pct=system_pct,
                    mic_text=mic_text,
                )
            )
        else:
            self.audio_result_label.setText(
                tr(
                    "✓ Звук работает. Системный звук: {system_pct}%, микрофон: {mic_text}.",
                    system_pct=system_pct,
                    mic_text=mic_text,
                )
            )

    def _finish_setup(self) -> None:
        openai_key = self.openai_key_input.text().strip()
        openrouter_key = self.openrouter_key_input.text().strip()
        if not set_openai_api_key(openai_key) or not set_openrouter_api_key(openrouter_key):
            QMessageBox.warning(
                self,
                tr("Не удалось сохранить ключи"),
                tr("Windows Credential Manager недоступен. Настройка не была завершена."),
            )
            return

        microphone_enabled = self.mic_checkbox.isChecked()
        microphone_settings = get_microphone_settings()
        if not set_microphone_settings(
            enabled=microphone_enabled,
            device_index=microphone_settings.get("device_index"),
            volume=float(microphone_settings.get("volume", 1.0)),
        ):
            QMessageBox.warning(
                self,
                tr("Не удалось сохранить настройки микрофона"),
                tr("Попробуйте ещё раз или настройте микрофон позже."),
            )
            return

        save_env_settings(
            {
                "APP_LANGUAGE": self.language_combo.currentData(),
                "MICROPHONE_ENABLED": microphone_enabled,
                "ONBOARDING_COMPLETED": True,
            }
        )
        reload_settings()
        self.accept()

    def reject(self) -> None:
        if self._audio_test_worker and self._audio_test_worker.isRunning():
            return
        super().reject()

    @staticmethod
    def _primary_button_style() -> str:
        return f"""
            QPushButton {{
                background-color: {ACCENT_PRIMARY}; color: #ffffff; border: none;
                border-radius: {RADIUS_MD}px; padding: 10px 20px;
                font-size: 13px; font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {ACCENT_PRIMARY_HOVER}; }}
            QPushButton:disabled {{ background-color: {BG_SURFACE_1}; color: {TEXT_TERTIARY}; }}
        """

    @staticmethod
    def _secondary_button_style() -> str:
        return f"""
            QPushButton {{
                background-color: transparent; color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: {RADIUS_MD}px;
                padding: 9px 16px; font-size: 13px;
            }}
            QPushButton:hover {{ color: {TEXT_PRIMARY}; background-color: {BG_SURFACE_2}; }}
            QPushButton:disabled {{ color: {TEXT_TERTIARY}; }}
        """
