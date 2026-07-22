"""Settings dialog for application configuration."""

from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.utils.config import get_settings, save_env_settings
from src.utils.security import (
    get_openai_api_key,
    get_openrouter_api_key,
    set_openai_api_key,
    set_openrouter_api_key,
    get_microphone_settings,
    set_microphone_settings,
)
from src.ui.theme import TEXT_TERTIARY
from src.ui.i18n import SUPPORTED_LANGUAGES, tr


class AudioTestWorker(QThread):
    """Short audio-device probe used by the settings dialog."""

    finished = pyqtSignal(object)

    def __init__(
        self,
        output_dir,
        sample_rate: int,
        channels: int,
        audio_device_index: Optional[int],
        microphone_enabled: bool,
        microphone_device_index: Optional[int],
        microphone_volume: float,
    ):
        super().__init__()
        self.output_dir = output_dir
        self.sample_rate = sample_rate
        self.channels = channels
        self.audio_device_index = audio_device_index
        self.microphone_enabled = microphone_enabled
        self.microphone_device_index = microphone_device_index
        self.microphone_volume = microphone_volume

    def run(self):
        try:
            from src.core.audio_recorder import AudioRecorder

            recorder = AudioRecorder(
                output_dir=self.output_dir,
                sample_rate=self.sample_rate,
                channels=self.channels,
                microphone_enabled=self.microphone_enabled,
                microphone_device_index=self.microphone_device_index,
                microphone_volume=self.microphone_volume,
            )
            try:
                if self.audio_device_index is not None:
                    recorder.set_device(self.audio_device_index)
                levels = recorder.test_levels(duration_seconds=3.0)
            finally:
                recorder.cleanup()

            self.finished.emit(levels)
        except Exception as e:
            self.finished.emit(e)


class SettingsDialog(QDialog):
    """Settings dialog for configuring the application."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = get_settings()
        self._audio_test_worker: Optional[AudioTestWorker] = None
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle(tr("Настройки"))
        self.setMinimumSize(600, 520)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Tab widget
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)

        # General tab
        general_tab = self._create_general_tab()
        tab_widget.addTab(general_tab, tr("Общие"))

        privacy_tab = self._create_privacy_tab()
        tab_widget.addTab(privacy_tab, tr("Приватность"))

        # API tab
        api_tab = self._create_api_tab()
        tab_widget.addTab(api_tab, "API")

        # Audio tab
        audio_tab = self._create_audio_tab()
        tab_widget.addTab(audio_tab, tr("Аудио"))

        # Auto-trigger tab
        trigger_tab = self._create_trigger_tab()
        tab_widget.addTab(trigger_tab, tr("Авто-запуск"))

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._save_settings)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _create_general_tab(self) -> QWidget:
        """Create general application settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        language_group = QGroupBox(tr("Язык интерфейса"))
        language_layout = QFormLayout(language_group)

        self.language_combo = QComboBox()
        for code, label in SUPPORTED_LANGUAGES.items():
            self.language_combo.addItem(label, code)
        language_layout.addRow(tr("Язык:"), self.language_combo)

        language_note = QLabel(
            "English is the default interface for the public app. "
            "Language changes apply after saving settings and restarting."
        )
        language_note.setWordWrap(True)
        language_note.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        language_layout.addRow("", language_note)

        layout.addWidget(language_group)
        layout.addStretch()
        return widget

    def _create_api_tab(self) -> QWidget:
        """Create API settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # OpenAI group
        openai_group = QGroupBox("OpenAI API")
        openai_layout = QFormLayout(openai_group)

        # API key
        api_key_layout = QHBoxLayout()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("OpenAI API key")
        api_key_layout.addWidget(self.api_key_input)

        self.show_key_button = QPushButton(tr("Показать"))
        self.show_key_button.setCheckable(True)
        self.show_key_button.toggled.connect(self._toggle_key_visibility)
        api_key_layout.addWidget(self.show_key_button)

        openai_layout.addRow(tr("API ключ:"), api_key_layout)

        # Test button
        test_button = QPushButton(tr("Проверить подключение"))
        test_button.clicked.connect(self._test_api_connection)
        openai_layout.addRow("", test_button)

        layout.addWidget(openai_group)

        # Summary provider group
        google_group = QGroupBox("OpenRouter (Summary: Gemini)")
        google_layout = QFormLayout(google_group)

        google_key_layout = QHBoxLayout()
        self.openrouter_api_key_input = QLineEdit()
        self.openrouter_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.openrouter_api_key_input.setPlaceholderText("OpenRouter API key")
        google_key_layout.addWidget(self.openrouter_api_key_input)

        self.show_openrouter_key_button = QPushButton(tr("Показать"))
        self.show_openrouter_key_button.setCheckable(True)
        self.show_openrouter_key_button.toggled.connect(
            self._toggle_openrouter_key_visibility
        )
        google_key_layout.addWidget(self.show_openrouter_key_button)

        google_layout.addRow(tr("API ключ:"), google_key_layout)

        self.summary_model_input = QLineEdit()
        self.summary_model_input.setPlaceholderText("google/gemini-2.5-flash-lite")
        google_layout.addRow(tr("Модель:"), self.summary_model_input)

        test_google_button = QPushButton(tr("Проверить подключение"))
        test_google_button.clicked.connect(self._test_openrouter_connection)
        google_layout.addRow("", test_google_button)

        layout.addWidget(google_group)

        transcription_group = QGroupBox(tr("Транскрибация"))
        transcription_layout = QFormLayout(transcription_group)

        self.transcription_model_combo = QComboBox()
        self.transcription_model_combo.addItem(
            "GPT-4o mini Transcribe (cheaper, recommended)",
            "gpt-4o-mini-transcribe",
        )
        self.transcription_model_combo.addItem(
            "GPT-4o Transcribe (more accurate)",
            "gpt-4o-transcribe",
        )
        self.transcription_model_combo.addItem(
            "GPT-4o Transcribe Diarize (speakers)",
            "gpt-4o-transcribe-diarize",
        )
        self.transcription_model_combo.addItem("Whisper legacy", "whisper-1")
        transcription_layout.addRow(tr("Модель:"), self.transcription_model_combo)

        layout.addWidget(transcription_group)

        # Info
        info_label = QLabel(
            tr("Ключи: ")
            + "<a href='https://platform.openai.com/api-keys'>OpenAI</a> · "
            "<a href='https://openrouter.ai/settings/keys'>OpenRouter</a>"
        )
        info_label.setOpenExternalLinks(True)
        info_label.setStyleSheet(f"color: {TEXT_TERTIARY};")
        layout.addWidget(info_label)

        layout.addStretch()
        return widget

    def _create_privacy_tab(self) -> QWidget:
        """Create transparent, opt-in privacy controls."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        sharing_group = QGroupBox(tr("Диагностика и улучшение продукта"))
        sharing_layout = QVBoxLayout(sharing_group)

        self.analytics_checkbox = QCheckBox(
            tr("Отправлять анонимные этапы воронки")
        )
        self.analytics_checkbox.setToolTip(
            tr("Запуск, запись, готовая расшифровка и готовое саммари — без содержимого встречи.")
        )
        sharing_layout.addWidget(self.analytics_checkbox)

        self.crash_reports_checkbox = QCheckBox(
            tr("Отправлять очищенные отчёты о сбоях")
        )
        self.crash_reports_checkbox.setToolTip(
            tr("Технический тип ошибки и версия приложения — без логов и локальных данных.")
        )
        sharing_layout.addWidget(self.crash_reports_checkbox)

        privacy_note = QLabel(
            tr(
                "Meeting Note никогда не отправляет записи, расшифровки, саммари, "
                "названия встреч, API-ключи или логи. Разрешённые события "
                "отправляются в закрытые Google Forms."
            )
        )
        privacy_note.setWordWrap(True)
        privacy_note.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        sharing_layout.addWidget(privacy_note)
        layout.addWidget(sharing_group)

        updates_group = QGroupBox(tr("Обновления"))
        updates_layout = QVBoxLayout(updates_group)
        self.update_checks_checkbox = QCheckBox(
            tr("Автоматически проверять новые версии")
        )
        updates_layout.addWidget(self.update_checks_checkbox)
        updates_note = QLabel(
            tr(
                "Проверка обращается только к GitHub Releases и не отправляет "
                "идентификатор установки."
            )
        )
        updates_note.setWordWrap(True)
        updates_note.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        updates_layout.addWidget(updates_note)
        layout.addWidget(updates_group)

        layout.addStretch()
        return widget

    def _create_audio_tab(self) -> QWidget:
        """Create audio settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Device group (system audio / loopback)
        device_group = QGroupBox(tr("Системный звук (голос собеседника)"))
        device_layout = QFormLayout(device_group)

        self.device_combo = QComboBox()
        device_layout.addRow(tr("Устройство:"), self.device_combo)

        refresh_button = QPushButton(tr("Обновить список"))
        refresh_button.clicked.connect(self._refresh_all_devices)
        device_layout.addRow("", refresh_button)

        self.audio_test_button = QPushButton(tr("Проверить звук (3 сек)"))
        self.audio_test_button.clicked.connect(self._test_audio_devices)
        device_layout.addRow("", self.audio_test_button)

        self.audio_test_label = QLabel("")
        self.audio_test_label.setWordWrap(True)
        self.audio_test_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        device_layout.addRow("", self.audio_test_label)

        layout.addWidget(device_group)

        # Microphone group
        mic_group = QGroupBox(tr("Микрофон (ваш голос)"))
        mic_layout = QFormLayout(mic_group)

        self.mic_enabled_checkbox = QCheckBox(tr("Записывать микрофон"))
        self.mic_enabled_checkbox.setToolTip(
            tr("Записывает ваш голос с микрофона в дополнение к системному звуку.\n")
            + tr("Ваш голос будет записан даже если микрофон выключен в приложении звонка.")
        )
        self.mic_enabled_checkbox.toggled.connect(self._on_mic_enabled_changed)
        mic_layout.addRow(self.mic_enabled_checkbox)

        self.mic_device_combo = QComboBox()
        mic_layout.addRow(tr("Устройство:"), self.mic_device_combo)

        # Volume slider
        volume_layout = QHBoxLayout()
        self.mic_volume_spin = QSpinBox()
        self.mic_volume_spin.setRange(0, 200)
        self.mic_volume_spin.setValue(100)
        self.mic_volume_spin.setSuffix("%")
        self.mic_volume_spin.setToolTip(tr("Громкость микрофона при микшировании (100% = без изменений)"))
        volume_layout.addWidget(self.mic_volume_spin)
        mic_layout.addRow(tr("Громкость:"), volume_layout)

        layout.addWidget(mic_group)

        # Quality group
        quality_group = QGroupBox(tr("Качество записи"))
        quality_layout = QFormLayout(quality_group)

        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(["16000", "22050", "44100", "48000"])
        quality_layout.addRow(tr("Частота дискретизации:"), self.sample_rate_combo)

        self.channels_combo = QComboBox()
        self.channels_combo.addItems(["1 (Mono)", "2 (Stereo)"])
        quality_layout.addRow(tr("Каналы:"), self.channels_combo)

        layout.addWidget(quality_group)

        # Load devices once after both combos are created
        self._refresh_all_devices()

        layout.addStretch()
        return widget

    def _on_mic_enabled_changed(self, enabled: bool):
        """Handle microphone enabled checkbox change."""
        self.mic_device_combo.setEnabled(enabled)
        self.mic_volume_spin.setEnabled(enabled)

    def _on_trigger_mode_changed(self, index: int):
        """Update description when trigger mode changes."""
        mode = self.trigger_mode_combo.currentData()
        descriptions = {
            "manual": tr("Автозапуск отключен. Запись начинается только по кнопке."),
            "notification": (
                tr("При обнаружении созвона (Zoom, Teams и т.д.) показывается всплывающее окно с предложением начать запись.")
            ),
            "process": (
                "Recording starts automatically when a meeting app is detected "
                "(Zoom, Teams, and others)."
            ),
            "vad": (
                "Recording starts automatically when microphone speech is detected. "
                "It stops after sustained silence."
            ),
            "combined": (
                "Combined mode: detect a meeting app first, then start when speech appears."
            ),
        }
        self.mode_description.setText(descriptions.get(mode, ""))

    def _create_trigger_tab(self) -> QWidget:
        """Create auto-trigger settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Mode group
        mode_group = QGroupBox(tr("Режим автозапуска"))
        mode_layout = QVBoxLayout(mode_group)

        self.trigger_mode_combo = QComboBox()
        self.trigger_mode_combo.addItem(tr("Ручной (без автозапуска)"), "manual")
        self.trigger_mode_combo.addItem(
            tr("🔔 Уведомление (показать окно при созвоне)"), "notification"
        )
        self.trigger_mode_combo.addItem(
            tr("▶ Автозапуск при открытии приложения"), "process"
        )
        self.trigger_mode_combo.addItem(
            tr("🎤 Автозапуск при обнаружении речи"), "vad"
        )
        self.trigger_mode_combo.addItem(
            tr("⚡ Комбинированный (приложение + речь)"), "combined"
        )
        self.trigger_mode_combo.currentIndexChanged.connect(self._on_trigger_mode_changed)
        mode_layout.addWidget(self.trigger_mode_combo)

        # Mode description
        self.mode_description = QLabel()
        self.mode_description.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        self.mode_description.setWordWrap(True)
        mode_layout.addWidget(self.mode_description)

        layout.addWidget(mode_group)

        # Process monitor settings
        process_group = QGroupBox(tr("Мониторинг приложений"))
        process_layout = QFormLayout(process_group)

        self.process_monitor_checkbox = QCheckBox("Watch for meeting apps")
        process_layout.addRow(self.process_monitor_checkbox)

        self.process_list_label = QLabel(
            "Watched apps:\n"
            "Zoom, Teams, Google Meet, Discord, Slack, Yandex Telemost"
        )
        self.process_list_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        process_layout.addRow(self.process_list_label)

        layout.addWidget(process_group)

        # VAD settings
        vad_group = QGroupBox(tr("Детекция голоса (VAD)"))
        vad_layout = QFormLayout(vad_group)

        self.vad_checkbox = QCheckBox(tr("Автоматически определять речь"))
        vad_layout.addRow(self.vad_checkbox)

        self.vad_aggressiveness = QSpinBox()
        self.vad_aggressiveness.setRange(0, 3)
        self.vad_aggressiveness.setValue(2)
        vad_layout.addRow(tr("Чувствительность (0-3):"), self.vad_aggressiveness)

        self.speech_threshold = QSpinBox()
        self.speech_threshold.setRange(1, 60)
        self.speech_threshold.setValue(10)
        self.speech_threshold.setSuffix(" " + tr("сек"))
        vad_layout.addRow(tr("Минимум речи для старта:"), self.speech_threshold)

        self.silence_threshold = QSpinBox()
        self.silence_threshold.setRange(5, 120)
        self.silence_threshold.setValue(30)
        self.silence_threshold.setSuffix(" " + tr("сек"))
        vad_layout.addRow(tr("Тишина для остановки:"), self.silence_threshold)

        layout.addWidget(vad_group)

        layout.addStretch()
        return widget

    def _refresh_all_devices(self):
        """Refresh both audio device lists using a single AudioRecorder instance."""
        self.device_combo.clear()
        self.mic_device_combo.clear()
        self.device_combo.addItem(tr("По умолчанию"), None)
        self.mic_device_combo.addItem(tr("По умолчанию"), None)

        try:
            from src.core.audio_recorder import AudioRecorder

            recorder = AudioRecorder(
                output_dir=self.settings.recordings_dir,
                sample_rate=self.settings.sample_rate,
            )
            try:
                for device in recorder.get_available_devices():
                    label = device.name + (" (Loopback)" if device.is_loopback else "")
                    self.device_combo.addItem(label, device.index)

                for device in recorder.get_microphone_devices():
                    self.mic_device_combo.addItem(device.name, device.index)
            finally:
                recorder.cleanup()

        except Exception as e:
            self.device_combo.addItem(f"{tr('Ошибка')}: {e}")
            self.mic_device_combo.addItem(f"{tr('Ошибка')}: {e}", None)

    def _load_settings(self):
        """Load current settings into form."""
        language_index = self.language_combo.findData(self.settings.app_language)
        if language_index >= 0:
            self.language_combo.setCurrentIndex(language_index)

        # API key
        api_key = get_openai_api_key()
        if api_key:
            self.api_key_input.setText(api_key)

        openrouter_api_key = get_openrouter_api_key()
        if openrouter_api_key:
            self.openrouter_api_key_input.setText(openrouter_api_key)
        self.summary_model_input.setText(self.settings.summary_model)

        model_index = self.transcription_model_combo.findData(
            self.settings.transcription_model
        )
        if model_index >= 0:
            self.transcription_model_combo.setCurrentIndex(model_index)

        # Audio settings
        sr_index = self.sample_rate_combo.findText(str(self.settings.sample_rate))
        if sr_index >= 0:
            self.sample_rate_combo.setCurrentIndex(sr_index)

        self.channels_combo.setCurrentIndex(0 if self.settings.channels == 1 else 1)

        if self.settings.audio_device_index is not None:
            for i in range(self.device_combo.count()):
                if self.device_combo.itemData(i) == self.settings.audio_device_index:
                    self.device_combo.setCurrentIndex(i)
                    break

        # Microphone settings
        mic_settings = get_microphone_settings()
        self.mic_enabled_checkbox.setChecked(mic_settings.get("enabled", True))
        self.mic_volume_spin.setValue(int(mic_settings.get("volume", 1.0) * 100))

        # Set microphone device
        device_index = mic_settings.get("device_index")
        if device_index is not None:
            for i in range(self.mic_device_combo.count()):
                if self.mic_device_combo.itemData(i) == device_index:
                    self.mic_device_combo.setCurrentIndex(i)
                    break

        # Update enabled state
        self._on_mic_enabled_changed(mic_settings.get("enabled", True))

        self.analytics_checkbox.setChecked(self.settings.anonymous_analytics_enabled)
        self.crash_reports_checkbox.setChecked(self.settings.crash_reports_enabled)
        self.update_checks_checkbox.setChecked(self.settings.update_checks_enabled)

        # Auto-trigger settings
        self.process_monitor_checkbox.setChecked(self.settings.process_monitor_enabled)
        self.vad_checkbox.setChecked(self.settings.vad_enabled)
        self.vad_aggressiveness.setValue(self.settings.vad_aggressiveness)
        self.speech_threshold.setValue(int(self.settings.vad_speech_threshold_seconds))
        self.silence_threshold.setValue(int(self.settings.vad_silence_threshold_seconds))

        # Set trigger mode
        trigger_mode = self.settings.trigger_mode
        for i in range(self.trigger_mode_combo.count()):
            if self.trigger_mode_combo.itemData(i) == trigger_mode:
                self.trigger_mode_combo.setCurrentIndex(i)
                break
        self._on_trigger_mode_changed(0)

    def _save_settings(self):
        """Save settings and close dialog."""
        # Save API key to secure storage
        api_key = self.api_key_input.text().strip()
        if api_key:
            set_openai_api_key(api_key)

        openrouter_api_key = self.openrouter_api_key_input.text().strip()
        if openrouter_api_key:
            set_openrouter_api_key(openrouter_api_key)

        # Save microphone settings
        mic_enabled = self.mic_enabled_checkbox.isChecked()
        mic_device_index = self.mic_device_combo.currentData()
        mic_volume = self.mic_volume_spin.value() / 100.0
        set_microphone_settings(mic_enabled, mic_device_index, mic_volume)

        trigger_mode = self.trigger_mode_combo.currentData()
        save_env_settings(
            {
                "SAMPLE_RATE": int(self.sample_rate_combo.currentText()),
                "CHANNELS": 1 if self.channels_combo.currentIndex() == 0 else 2,
                "AUDIO_DEVICE_INDEX": self.device_combo.currentData(),
                "APP_LANGUAGE": self.language_combo.currentData(),
                "TRANSCRIPTION_MODEL": self.transcription_model_combo.currentData(),
                "SUMMARY_MODEL": self.summary_model_input.text().strip()
                or self.settings.summary_model,
                "TRIGGER_MODE": trigger_mode,
                "AUTO_TRIGGER_ENABLED": trigger_mode != "manual",
                "PROCESS_MONITOR_ENABLED": self.process_monitor_checkbox.isChecked(),
                "VAD_ENABLED": self.vad_checkbox.isChecked(),
                "VAD_AGGRESSIVENESS": self.vad_aggressiveness.value(),
                "VAD_SPEECH_THRESHOLD_SECONDS": self.speech_threshold.value(),
                "VAD_SILENCE_THRESHOLD_SECONDS": self.silence_threshold.value(),
                "PRIVACY_CHOICE_COMPLETED": True,
                "ANONYMOUS_ANALYTICS_ENABLED": self.analytics_checkbox.isChecked(),
                "CRASH_REPORTS_ENABLED": self.crash_reports_checkbox.isChecked(),
                "UPDATE_CHECKS_ENABLED": self.update_checks_checkbox.isChecked(),
            }
        )

        self.accept()

    def _toggle_key_visibility(self, show: bool):
        """Toggle API key visibility."""
        if show:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_key_button.setText(tr("Скрыть"))
        else:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_key_button.setText(tr("Показать"))

    def _toggle_openrouter_key_visibility(self, show: bool):
        """Toggle OpenRouter API key visibility."""
        if show:
            self.openrouter_api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_openrouter_key_button.setText(tr("Скрыть"))
        else:
            self.openrouter_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_openrouter_key_button.setText(tr("Показать"))

    def _test_api_connection(self):
        """Test OpenAI API connection."""
        api_key = self.api_key_input.text().strip()
        if not api_key:
            QMessageBox.warning(self, tr("Ошибка"), tr("Введите API ключ"))
            return

        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            # Simple test - list models
            models = client.models.list()

            QMessageBox.information(
                self,
                tr("Успех"),
                tr("Подключение к OpenAI API работает!"),
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                tr("Ошибка подключения"),
                tr("Не удалось подключиться к API:\n{error}", error=str(e)),
            )

    def _test_openrouter_connection(self):
        """Test OpenRouter API connection."""
        api_key = self.openrouter_api_key_input.text().strip()
        if not api_key:
            QMessageBox.warning(self, tr("Ошибка"), tr("Введите OpenRouter API ключ"))
            return

        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                base_url=self.settings.openrouter_base_url,
                default_headers={"X-Title": "Meeting Note"},
            )
            client.chat.completions.create(
                model=self.summary_model_input.text().strip()
                or self.settings.summary_model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )

            QMessageBox.information(
                self,
                tr("Успех"),
                tr("Подключение к OpenRouter работает!"),
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                tr("Ошибка подключения"),
                tr("Не удалось подключиться к OpenRouter:\n{error}", error=str(e)),
            )

    def _test_audio_devices(self):
        """Run a short audio-device probe."""
        if self._audio_test_worker and self._audio_test_worker.isRunning():
            return

        self.audio_test_button.setEnabled(False)
        self.audio_test_button.setText(tr("Проверяю..."))
        self.audio_test_label.setText(tr("Слушаю выбранные устройства 3 секунды..."))

        self._audio_test_worker = AudioTestWorker(
            output_dir=self.settings.recordings_dir,
            sample_rate=int(self.sample_rate_combo.currentText()),
            channels=1 if self.channels_combo.currentIndex() == 0 else 2,
            audio_device_index=self.device_combo.currentData(),
            microphone_enabled=self.mic_enabled_checkbox.isChecked(),
            microphone_device_index=self.mic_device_combo.currentData(),
            microphone_volume=self.mic_volume_spin.value() / 100.0,
        )
        self._audio_test_worker.finished.connect(self._on_audio_test_finished)
        self._audio_test_worker.start()

    def _on_audio_test_finished(self, result):
        """Show audio probe result."""
        self.audio_test_button.setEnabled(True)
        self.audio_test_button.setText(tr("Проверить звук (3 сек)"))

        worker = self._audio_test_worker
        self._audio_test_worker = None
        if worker:
            worker.deleteLater()

        if isinstance(result, Exception):
            self.audio_test_label.setText(tr("Проверка не удалась"))
            QMessageBox.warning(self, tr("Ошибка проверки звука"), str(result))
            return

        system_pct = int((result.get("system") or 0.0) * 100)
        mic_level = result.get("microphone")
        mic_text = tr("выключен")
        if mic_level is not None:
            mic_text = f"{int(mic_level * 100)}%"

        if system_pct < 1 and (mic_level is None or mic_level < 0.01):
            self.audio_test_label.setText(
                tr("Сигнал почти не обнаружен. Системный звук: {system_pct}%, микрофон: {mic_text}.", system_pct=system_pct, mic_text=mic_text)
            )
        else:
            self.audio_test_label.setText(
                tr("Сигнал есть. Системный звук: {system_pct}%, микрофон: {mic_text}.", system_pct=system_pct, mic_text=mic_text)
            )
