"""Global hotkey support for Meeting Note."""

import threading
from typing import Callable, Dict, Optional

from loguru import logger

try:
    from pynput import keyboard

    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False
    logger.warning("pynput not installed, global hotkeys disabled")


class HotkeyManager:
    """
    Global hotkey manager using pynput.

    Allows registering keyboard shortcuts that work
    even when the application is not focused.
    """

    def __init__(self):
        self._hotkeys: Dict[str, Callable] = {}
        self._listener: Optional[keyboard.GlobalHotKeys] = None
        self._running = False

    def register(self, hotkey: str, callback: Callable) -> bool:
        """
        Register a global hotkey.

        Args:
            hotkey: Hotkey string (e.g., "<ctrl>+<shift>+r")
            callback: Function to call when hotkey is pressed

        Returns:
            True if registered successfully
        """
        if not HAS_PYNPUT:
            logger.warning("Cannot register hotkey - pynput not available")
            return False

        self._hotkeys[hotkey] = callback
        logger.info(f"Registered hotkey: {hotkey}")

        # Restart listener if running
        if self._running:
            self.stop()
            self.start()

        return True

    def unregister(self, hotkey: str) -> bool:
        """Unregister a hotkey."""
        if hotkey in self._hotkeys:
            del self._hotkeys[hotkey]
            logger.info(f"Unregistered hotkey: {hotkey}")

            # Restart listener if running
            if self._running:
                self.stop()
                self.start()
            return True
        return False

    def start(self) -> bool:
        """Start listening for hotkeys."""
        if not HAS_PYNPUT:
            return False

        if self._running:
            return True

        if not self._hotkeys:
            logger.warning("No hotkeys registered")
            return False

        try:
            self._listener = keyboard.GlobalHotKeys(self._hotkeys)
            self._listener.start()
            self._running = True
            logger.info("Hotkey listener started")
            return True
        except Exception as e:
            logger.error(f"Failed to start hotkey listener: {e}")
            return False

    def stop(self) -> None:
        """Stop listening for hotkeys."""
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        self._running = False
        logger.info("Hotkey listener stopped")

    def is_running(self) -> bool:
        """Check if listener is running."""
        return self._running


# Default hotkeys
DEFAULT_HOTKEYS = {
    "start_stop": "<ctrl>+<shift>+r",
    "pause": "<ctrl>+<shift>+p",
}


class AppHotkeys:
    """
    Application-specific hotkey bindings.

    Provides semantic hotkey registration for Meeting Note.
    """

    def __init__(
        self,
        on_toggle_recording: Optional[Callable] = None,
        on_pause_recording: Optional[Callable] = None,
    ):
        self._manager = HotkeyManager()
        self.on_toggle_recording = on_toggle_recording
        self.on_pause_recording = on_pause_recording

    def setup_default_hotkeys(self) -> None:
        """Set up default application hotkeys."""
        if self.on_toggle_recording:
            self._manager.register(
                DEFAULT_HOTKEYS["start_stop"],
                self._on_toggle_pressed,
            )

        if self.on_pause_recording:
            self._manager.register(
                DEFAULT_HOTKEYS["pause"],
                self._on_pause_pressed,
            )

    def _on_toggle_pressed(self) -> None:
        """Handle toggle hotkey."""
        logger.info("Toggle recording hotkey pressed")
        if self.on_toggle_recording:
            self.on_toggle_recording()

    def _on_pause_pressed(self) -> None:
        """Handle pause hotkey."""
        logger.info("Pause recording hotkey pressed")
        if self.on_pause_recording:
            self.on_pause_recording()

    def start(self) -> bool:
        """Start listening for hotkeys."""
        return self._manager.start()

    def stop(self) -> None:
        """Stop listening for hotkeys."""
        self._manager.stop()

    def set_toggle_hotkey(self, hotkey: str) -> bool:
        """Change the toggle recording hotkey."""
        self._manager.unregister(DEFAULT_HOTKEYS["start_stop"])
        return self._manager.register(hotkey, self._on_toggle_pressed)
