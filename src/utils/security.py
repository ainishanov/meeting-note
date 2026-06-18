"""Secure credential storage using Windows Credential Manager."""

from typing import Optional

import keyring
from loguru import logger

SERVICE_NAME = "MeetingNote"


def store_api_key(key_name: str, api_key: str) -> bool:
    """
    Securely store an API key in Windows Credential Manager.

    Args:
        key_name: Name/identifier for the key (e.g., "openai")
        api_key: The API key value to store

    Returns:
        True if stored successfully, False otherwise
    """
    try:
        keyring.set_password(SERVICE_NAME, key_name, api_key)
        logger.info(f"API key '{key_name}' stored securely")
        return True
    except Exception as e:
        logger.error(f"Failed to store API key '{key_name}': {e}")
        return False


def get_api_key(key_name: str) -> Optional[str]:
    """
    Retrieve an API key from Windows Credential Manager.

    Args:
        key_name: Name/identifier for the key (e.g., "openai")

    Returns:
        The API key value or None if not found
    """
    try:
        api_key = keyring.get_password(SERVICE_NAME, key_name)
        if api_key:
            logger.debug(f"API key '{key_name}' retrieved from secure storage")
        return api_key
    except Exception as e:
        logger.error(f"Failed to retrieve API key '{key_name}': {e}")
        return None


def delete_api_key(key_name: str) -> bool:
    """
    Delete an API key from Windows Credential Manager.

    Args:
        key_name: Name/identifier for the key (e.g., "openai")

    Returns:
        True if deleted successfully, False otherwise
    """
    try:
        keyring.delete_password(SERVICE_NAME, key_name)
        logger.info(f"API key '{key_name}' deleted from secure storage")
        return True
    except keyring.errors.PasswordDeleteError:
        logger.warning(f"API key '{key_name}' not found in secure storage")
        return False
    except Exception as e:
        logger.error(f"Failed to delete API key '{key_name}': {e}")
        return False


def get_openai_api_key() -> Optional[str]:
    """
    Get OpenAI API key from secure storage or environment.

    Checks:
    1. Windows Credential Manager
    2. Environment variable (via config)

    Returns:
        OpenAI API key or None if not configured
    """
    # First try secure storage
    api_key = get_api_key("openai")
    if api_key:
        return api_key

    # Fall back to environment variable
    from src.utils.config import get_settings

    settings = get_settings()
    return settings.get_openai_key()


def set_openai_api_key(api_key: str) -> bool:
    """
    Store OpenAI API key in secure storage.

    Args:
        api_key: The OpenAI API key to store

    Returns:
        True if stored successfully
    """
    return store_api_key("openai", api_key)


def get_google_api_key() -> Optional[str]:
    """
    Get Google API key from secure storage or environment.

    Checks:
    1. Windows Credential Manager
    2. Environment variable (via config)

    Returns:
        Google API key or None if not configured
    """
    # First try secure storage
    api_key = get_api_key("google")
    if api_key:
        return api_key

    # Fall back to environment variable
    from src.utils.config import get_settings

    settings = get_settings()
    return settings.get_google_key()


def set_google_api_key(api_key: str) -> bool:
    """
    Store Google API key in secure storage.

    Args:
        api_key: The Google API key to store

    Returns:
        True if stored successfully
    """
    return store_api_key("google", api_key)


def get_openrouter_api_key() -> Optional[str]:
    """
    Get OpenRouter API key from secure storage or environment.

    Checks:
    1. Windows Credential Manager
    2. Environment variable (via config)

    Returns:
        OpenRouter API key or None if not configured
    """
    api_key = get_api_key("openrouter")
    if api_key:
        return api_key

    from src.utils.config import get_settings

    settings = get_settings()
    return settings.get_openrouter_key()


def set_openrouter_api_key(api_key: str) -> bool:
    """
    Store OpenRouter API key in secure storage.

    Args:
        api_key: The OpenRouter API key to store

    Returns:
        True if stored successfully
    """
    return store_api_key("openrouter", api_key)


# Microphone settings storage
import json


def get_microphone_settings() -> dict:
    """
    Get microphone settings from storage.

    Returns:
        Dict with microphone settings: enabled, device_index, volume
    """
    defaults = {
        "enabled": True,
        "device_index": None,
        "volume": 1.0,
    }
    try:
        settings_json = keyring.get_password(SERVICE_NAME, "microphone_settings")
        if settings_json:
            settings = json.loads(settings_json)
            # Merge with defaults to ensure all keys exist
            return {**defaults, **settings}
        return defaults
    except Exception as e:
        logger.error(f"Failed to get microphone settings: {e}")
        return defaults


def set_microphone_settings(enabled: bool, device_index: Optional[int] = None, volume: float = 1.0) -> bool:
    """
    Save microphone settings to storage.

    Args:
        enabled: Whether microphone recording is enabled
        device_index: Microphone device index (None for default)
        volume: Microphone volume multiplier (0.0 - 2.0)

    Returns:
        True if saved successfully
    """
    try:
        settings = {
            "enabled": enabled,
            "device_index": device_index,
            "volume": volume,
        }
        keyring.set_password(SERVICE_NAME, "microphone_settings", json.dumps(settings))
        logger.info(f"Microphone settings saved: enabled={enabled}, device={device_index}, volume={volume}")
        return True
    except Exception as e:
        logger.error(f"Failed to save microphone settings: {e}")
        return False
