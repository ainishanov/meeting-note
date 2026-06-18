"""Application configuration management using pydantic-settings."""

from pathlib import Path
from typing import Mapping, Optional

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    # OpenAI API (for Whisper transcription)
    openai_api_key: Optional[SecretStr] = Field(
        default=None,
        description="OpenAI API key for Whisper transcription",
    )

    # Legacy direct Google Gemini API (kept for backwards compatibility)
    google_api_key: Optional[SecretStr] = Field(
        default=None,
        description="Legacy Google API key",
    )
    openrouter_api_key: Optional[SecretStr] = Field(
        default=None,
        description="OpenRouter API key for summary generation",
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        description="OpenRouter-compatible API base URL",
    )
    summary_model: str = Field(
        default="google/gemini-2.5-flash-lite",
        description="OpenRouter model for summary generation",
    )

    # Paths
    app_data_dir: Path = Field(
        default=Path("./data"),
        description="Application data directory",
    )
    recordings_dir: Path = Field(
        default=Path("./data/recordings"),
        description="Directory for audio recordings",
    )
    database_path: Path = Field(
        default=Path("./data/database.db"),
        description="SQLite database path",
    )

    # Audio settings
    sample_rate: int = Field(
        default=16000,
        ge=8000,
        le=48000,
        description="Audio sample rate in Hz",
    )
    channels: int = Field(
        default=1,
        ge=1,
        le=2,
        description="Number of audio channels",
    )
    audio_device_index: Optional[int] = Field(
        default=None,
        description="System audio device index (None = default loopback device)",
    )

    # Microphone settings
    microphone_enabled: bool = Field(
        default=True,
        description="Enable microphone recording (in addition to system audio)",
    )
    microphone_device_index: Optional[int] = Field(
        default=None,
        description="Microphone device index (None = default input device)",
    )
    microphone_volume: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Microphone volume multiplier for mixing",
    )

    # Transcription settings
    transcription_language: Optional[str] = Field(
        default=None,
        description="Language for transcription in ISO-639-1 format (ru, en, etc.) or None for auto-detect",
    )
    transcription_model: str = Field(
        default="gpt-4o-mini-transcribe",
        description="OpenAI transcription model",
    )
    min_recording_duration: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Minimum recording duration in seconds to trigger transcription",
    )
    silence_threshold: int = Field(
        default=500,
        ge=100,
        le=5000,
        description="RMS threshold for silence detection (lower = more sensitive)",
    )

    # UI settings
    app_language: str = Field(
        default="en",
        description="Application interface language: en or ru",
    )

    # Auto-trigger settings
    trigger_mode: str = Field(
        default="notification",
        description="Auto-trigger mode: manual, notification, process, vad, combined",
    )
    auto_trigger_enabled: bool = Field(
        default=True,
        description="Enable automatic recording triggers",
    )
    vad_enabled: bool = Field(
        default=True,
        description="Enable Voice Activity Detection",
    )
    process_monitor_enabled: bool = Field(
        default=True,
        description="Enable process monitoring for auto-start",
    )

    # VAD settings
    vad_aggressiveness: int = Field(
        default=2,
        ge=0,
        le=3,
        description="VAD aggressiveness (0=least, 3=most aggressive)",
    )
    vad_speech_threshold_seconds: float = Field(
        default=10.0,
        ge=1.0,
        description="Seconds of speech before starting recording",
    )
    vad_silence_threshold_seconds: float = Field(
        default=30.0,
        ge=5.0,
        description="Seconds of silence before stopping recording",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )
    log_file: Optional[Path] = Field(
        default=Path("./data/meeting_note.log"),
        description="Log file path",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper_v = v.upper()
        if upper_v not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return upper_v

    @field_validator("app_language")
    @classmethod
    def validate_app_language(cls, v: str) -> str:
        language = (v or "en").lower()
        if language not in {"en", "ru"}:
            raise ValueError("Invalid app language. Must be 'en' or 'ru'.")
        return language

    def ensure_directories(self) -> None:
        """Create required directories if they don't exist."""
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        if self.database_path.parent:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)

    def get_openai_key(self) -> Optional[str]:
        """Get OpenAI API key as plain string."""
        if self.openai_api_key:
            return self.openai_api_key.get_secret_value()
        return None

    def get_google_key(self) -> Optional[str]:
        """Get Google API key as plain string."""
        if self.google_api_key:
            return self.google_api_key.get_secret_value()
        return None

    def get_openrouter_key(self) -> Optional[str]:
        """Get OpenRouter API key as plain string."""
        if self.openrouter_api_key:
            return self.openrouter_api_key.get_secret_value()
        return None


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_directories()
    return _settings


def reload_settings() -> Settings:
    """Reload settings from environment."""
    global _settings
    _settings = Settings()
    _settings.ensure_directories()
    return _settings


def save_env_settings(updates: Mapping[str, object], env_path: Path = Path(".env")) -> None:
    """Update application settings in .env while preserving unrelated lines."""
    existing_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    pending = {key.upper(): _format_env_value(value) for key, value in updates.items()}
    updated_lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            updated_lines.append(line)
            continue

        key, _ = line.split("=", 1)
        normalized_key = key.strip().upper()
        if normalized_key in pending:
            updated_lines.append(f"{key.strip()}={pending.pop(normalized_key)}")
        else:
            updated_lines.append(line)

    if pending:
        if updated_lines and updated_lines[-1].strip():
            updated_lines.append("")
        for key, value in pending.items():
            updated_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def _format_env_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
