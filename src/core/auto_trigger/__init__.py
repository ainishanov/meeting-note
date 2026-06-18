"""Auto-trigger functionality for automatic recording start/stop."""

from src.core.auto_trigger.trigger_manager import TriggerManager, TriggerMode
from src.core.auto_trigger.process_monitor import ProcessMonitor
from src.core.auto_trigger.vad_detector import VoiceActivityDetector

__all__ = [
    "TriggerManager",
    "TriggerMode",
    "ProcessMonitor",
    "VoiceActivityDetector",
]
