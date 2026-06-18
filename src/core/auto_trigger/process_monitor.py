"""Process monitoring for automatic recording trigger."""

import threading
from dataclasses import dataclass
from typing import Callable, Optional, Set

import psutil
from loguru import logger

try:
    import win32gui
    import win32process

    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    logger.warning("pywin32 not installed, window title detection disabled")


@dataclass
class MonitoredApp:
    """Configuration for a monitored application."""

    process_name: str
    title_keywords: Optional[list[str]] = None


# Default list of meeting applications to monitor
DEFAULT_MEETING_APPS = [
    # Desktop apps - need to check for active meeting via window title
    MonitoredApp("Zoom.exe", ["meeting", "звонок", "call", "zapi:", "zoom meeting"]),
    MonitoredApp("Teams.exe", ["meeting", "звонок", "call", "teams meeting"]),
    MonitoredApp("slack.exe", ["huddle", "call", "звонок", "meeting"]),
    MonitoredApp("Discord.exe", ["voice", "call", "звонок", "voice connected"]),
    # Browsers - need to check window title
    MonitoredApp(
        "chrome.exe",
        ["телемост", "telemost", "zoom", "meet", "teams", "meeting", "звонок", "конференция"],
    ),
    MonitoredApp(
        "msedge.exe",
        ["телемост", "telemost", "teams", "meet", "meeting", "звонок", "конференция"],
    ),
    MonitoredApp(
        "firefox.exe",
        ["телемост", "telemost", "zoom", "meet", "meeting", "звонок", "конференция"],
    ),
    MonitoredApp(
        "yandex.exe",  # Yandex Browser
        ["телемост", "telemost", "meeting", "звонок", "конференция"],
    ),
    MonitoredApp(
        "browser.exe",  # Yandex Browser alternative name
        ["телемост", "telemost", "meeting", "звонок", "конференция"],
    ),
]


class ProcessMonitor:
    """
    Monitor running processes to detect meeting applications.

    Triggers callbacks when meeting apps start or stop.
    """

    def __init__(
        self,
        apps: Optional[list[MonitoredApp]] = None,
        on_meeting_start: Optional[Callable[[str], None]] = None,
        on_meeting_end: Optional[Callable[[str], None]] = None,
        check_interval: float = 5.0,
    ):
        """
        Initialize process monitor.

        Args:
            apps: List of apps to monitor (uses defaults if None)
            on_meeting_start: Callback when meeting app detected
            on_meeting_end: Callback when meeting app closed
            check_interval: Seconds between checks
        """
        self.apps = apps or DEFAULT_MEETING_APPS
        self.on_meeting_start = on_meeting_start
        self.on_meeting_end = on_meeting_end
        self.check_interval = check_interval

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._active_meetings: Set[str] = set()

    def start(self) -> None:
        """Start monitoring processes."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("Process monitor started")

    def stop(self) -> None:
        """Stop monitoring processes."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Process monitor stopped")

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                current_meetings = self._detect_meetings()

                # Check for new meetings
                new_meetings = current_meetings - self._active_meetings
                for meeting in new_meetings:
                    logger.info(f"Meeting detected: {meeting}")
                    if self.on_meeting_start:
                        self.on_meeting_start(meeting)

                # Check for ended meetings
                ended_meetings = self._active_meetings - current_meetings
                for meeting in ended_meetings:
                    logger.info(f"Meeting ended: {meeting}")
                    if self.on_meeting_end:
                        self.on_meeting_end(meeting)

                self._active_meetings = current_meetings

            except Exception as e:
                logger.error(f"Process monitor error: {e}")

            self._stop_event.wait(self.check_interval)

    def _detect_meetings(self) -> Set[str]:
        """Detect currently running meeting applications."""
        meetings = set()

        # Get all running processes
        running_processes = {}
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = proc.info["name"].lower()
                running_processes[proc.info["pid"]] = name
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        for app in self.apps:
            process_name_lower = app.process_name.lower()

            # Find matching processes
            for pid, name in running_processes.items():
                if name == process_name_lower:
                    # All apps now require window title check to detect active meeting
                    # (not just running app in tray)
                    if HAS_WIN32 and app.title_keywords:
                        if self._check_window_titles(pid, app.title_keywords):
                            meetings.add(f"{app.process_name} (meeting)")
                            break

        return meetings

    def _check_window_titles(self, pid: int, keywords: list[str]) -> bool:
        """
        Check if any window of process contains meeting keywords.

        Checks all windows including minimized ones - the meeting window title
        contains meeting-specific keywords even when minimized to tray.
        """
        if not HAS_WIN32:
            return False

        matching_windows = []

        def enum_callback(hwnd, _):
            try:
                _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
                if window_pid == pid:
                    title = win32gui.GetWindowText(hwnd)
                    # Check if window has a title (exclude empty/generic windows)
                    # Meeting windows have descriptive titles with meeting details
                    if title and len(title) > 5:  # Skip short generic titles like "Zoom"
                        title_lower = title.lower()
                        for keyword in keywords:
                            if keyword.lower() in title_lower:
                                matching_windows.append(title)
                                logger.debug(f"Found meeting window: '{title}'")
                                return True  # Stop enumeration
            except Exception:
                pass
            return True  # Continue enumeration

        try:
            win32gui.EnumWindows(enum_callback, None)
        except Exception as e:
            logger.debug(f"Error enumerating windows: {e}")

        return len(matching_windows) > 0

    def is_meeting_active(self) -> bool:
        """Check if any meeting is currently active."""
        return len(self._active_meetings) > 0

    def get_active_meetings(self) -> Set[str]:
        """Get set of currently active meeting applications."""
        return self._active_meetings.copy()
