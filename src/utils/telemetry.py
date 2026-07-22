"""Opt-in, privacy-scrubbed product analytics and crash reporting."""

from __future__ import annotations

import json
import queue
import re
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from src import __version__
from src.build_config import SENTRY_DSN as BUILD_SENTRY_DSN


_WINDOWS_USER_PATH = re.compile(r"(?i)[a-z]:\\users\\[^\\\s]+")
_API_KEY = re.compile(r"(?i)\b(?:sk|sk-or-v1)-[a-z0-9_-]{12,}\b")
_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{12,}")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_ALLOWED_PROPERTY_TYPES = (bool, int, float, str)
_EVENT_FORM_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLScIYICS72SDQ8utre_QU5dVDMDQBvqwVaQPZJzEQ1y1-QM2nA/formResponse"
)
_EVENT_NAME_FIELD = "entry.1029522403"
_APP_VERSION_FIELD = "entry.1342283318"
_INSTALL_ID_FIELD = "entry.870054504"
_PROPERTIES_FIELD = "entry.631486295"

_client_ready = False
_analytics_enabled = False
_crash_reports_enabled = False
_install_id: Optional[str] = None
_event_queue: queue.Queue[tuple[str, dict[str, object]]] = queue.Queue(maxsize=100)
_event_worker: Optional[threading.Thread] = None


def setup_telemetry(settings: Any) -> bool:
    """Initialize the optional Sentry-compatible client without collecting PII."""
    global _client_ready, _analytics_enabled, _crash_reports_enabled, _install_id

    _analytics_enabled = bool(settings.anonymous_analytics_enabled)
    _crash_reports_enabled = bool(settings.crash_reports_enabled)
    _install_id = None
    if _analytics_enabled or _crash_reports_enabled:
        _install_id = _get_or_create_install_id(settings.app_data_dir)
        _ensure_event_worker()
    else:
        _clear_event_queue()

    dsn = (settings.sentry_dsn or BUILD_SENTRY_DSN or "").strip()
    if not dsn:
        _client_ready = False
        logger.info("Sentry-compatible crash tracing is not configured for this build")
        return False

    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            release=f"meeting-note@{__version__}",
            environment="production",
            send_default_pii=False,
            include_local_variables=False,
            include_source_context=False,
            attach_stacktrace=False,
            traces_sample_rate=0.0,
            profiles_sample_rate=0.0,
            server_name="meeting-note-desktop",
            before_send=_scrub_event,
            default_integrations=False,
            shutdown_timeout=1.0,
        )
        sentry_sdk.set_tag("app_version", __version__)
        if _install_id:
            sentry_sdk.set_user({"id": _install_id})
        _client_ready = True
        logger.info("Privacy-safe telemetry client initialized")
        return True
    except Exception as error:
        _client_ready = False
        logger.warning(f"Telemetry initialization failed: {sanitize_text(str(error))}")
        return False


def telemetry_is_configured() -> bool:
    """Return whether this build has an active remote telemetry client."""
    return _client_ready


def track_event(name: str, **properties: object) -> Optional[str]:
    """Send one allow-listed product event when anonymous analytics is enabled."""
    if not _analytics_enabled:
        return None

    safe_name = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")[:64]
    if not safe_name:
        return None

    safe_properties = {
        re.sub(r"[^a-z0-9_]+", "_", key.lower()).strip("_")[:40]: _safe_property(value)
        for key, value in properties.items()
        if key and isinstance(value, _ALLOWED_PROPERTY_TYPES)
    }

    queued = _queue_google_event(safe_name, safe_properties)
    if not _client_ready:
        return "queued" if queued else None

    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            scope.set_tag("event_type", "product")
            scope.set_tag("product_event", safe_name)
            for key, value in safe_properties.items():
                scope.set_extra(key, value)
            return str(sentry_sdk.capture_message(f"product_event:{safe_name}", level="info"))
    except Exception as error:
        logger.debug(f"Product event delivery failed: {sanitize_text(str(error))}")
        return "queued" if queued else None


def capture_exception(error: BaseException, stage: str) -> Optional[str]:
    """Send an exception without logs, meeting content, local variables, or host identity."""
    if not _crash_reports_enabled:
        return None

    safe_stage = re.sub(r"[^a-z0-9_]+", "_", stage.lower()).strip("_")[:40]
    queued = _queue_google_event(
        "crash_reported",
        {
            "stage": safe_stage or "unknown",
            "error_type": type(error).__name__[:80],
        },
    )
    if not _client_ready:
        return "queued" if queued else None
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            scope.set_tag("event_type", "crash")
            scope.set_tag("stage", safe_stage or "unknown")
            return str(sentry_sdk.capture_exception(error))
    except Exception as delivery_error:
        logger.debug(
            f"Crash report delivery failed: {sanitize_text(str(delivery_error))}"
        )
        return "queued" if queued else None


def flush(timeout: float = 1.0) -> None:
    """Give the background transport a short chance to finish during shutdown."""
    deadline = time.monotonic() + max(0.0, timeout)
    while _event_queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.02)
    if not _client_ready:
        return
    try:
        import sentry_sdk

        sentry_sdk.flush(timeout=timeout)
    except Exception:
        pass


def duration_bucket(seconds: Optional[float]) -> str:
    """Return a coarse duration bucket instead of sending an exact meeting length."""
    if seconds is None or seconds < 0:
        return "unknown"
    if seconds < 60:
        return "under_1m"
    if seconds < 5 * 60:
        return "1_to_5m"
    if seconds < 15 * 60:
        return "5_to_15m"
    if seconds < 30 * 60:
        return "15_to_30m"
    if seconds < 60 * 60:
        return "30_to_60m"
    return "over_60m"


def sanitize_text(value: str) -> str:
    """Remove common local identifiers and credentials from outbound strings."""
    sanitized = _WINDOWS_USER_PATH.sub("<user_path>", value)
    sanitized = _API_KEY.sub("<api_key>", sanitized)
    sanitized = _BEARER.sub("Bearer <token>", sanitized)
    sanitized = _EMAIL.sub("<email>", sanitized)
    return sanitized[:2000]


def _safe_property(value: object) -> object:
    if isinstance(value, str):
        return sanitize_text(value)[:120]
    return value


def _scrub_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """Final outbound guard that strips identity, breadcrumbs, and sensitive strings."""
    event.pop("request", None)
    event.pop("breadcrumbs", None)
    event.pop("server_name", None)
    event.pop("modules", None)

    user = event.get("user")
    if not isinstance(user, dict) or not str(user.get("id", "")).startswith("anon_"):
        event.pop("user", None)
    else:
        event["user"] = {"id": str(user["id"])[:45]}

    return _sanitize_tree(event)


def _sanitize_tree(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [_sanitize_tree(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_tree(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _sanitize_tree(item) for key, item in value.items()}
    return value


def _get_or_create_install_id(app_data_dir: Path) -> str:
    path = Path(app_data_dir) / "anonymous_install_id"
    try:
        if path.exists():
            existing = path.read_text(encoding="ascii").strip()
            if re.fullmatch(r"anon_[a-f0-9]{32}", existing):
                return existing
        identifier = f"anon_{uuid.uuid4().hex}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(identifier, encoding="ascii")
        return identifier
    except Exception:
        return f"anon_{uuid.uuid4().hex}"


def _queue_google_event(name: str, properties: dict[str, object]) -> bool:
    if not _install_id:
        return False
    try:
        _event_queue.put_nowait((name, properties))
        _ensure_event_worker()
        return True
    except queue.Full:
        logger.debug("Anonymous event queue is full; dropping event")
        return False


def _ensure_event_worker() -> None:
    global _event_worker
    if _event_worker and _event_worker.is_alive():
        return
    _event_worker = threading.Thread(
        target=_event_worker_loop,
        name="meeting-note-anonymous-events",
        daemon=True,
    )
    _event_worker.start()


def _event_worker_loop() -> None:
    while True:
        name, properties = _event_queue.get()
        try:
            for attempt in range(3):
                try:
                    _send_google_event(name, properties)
                    break
                except Exception as error:
                    if attempt == 2:
                        logger.debug(
                            "Anonymous event delivery failed after retries: "
                            f"{sanitize_text(str(error))}"
                        )
                    else:
                        time.sleep(0.5 * (attempt + 1))
        finally:
            _event_queue.task_done()


def _send_google_event(name: str, properties: dict[str, object]) -> None:
    payload = urllib.parse.urlencode(
        {
            _EVENT_NAME_FIELD: name,
            _APP_VERSION_FIELD: __version__,
            _INSTALL_ID_FIELD: _install_id or "",
            _PROPERTIES_FIELD: json.dumps(
                properties,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )[:1200],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _EVENT_FORM_URL,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": f"MeetingNote/{__version__}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=8.0) as response:
        response.read(256)


def _clear_event_queue() -> None:
    while True:
        try:
            _event_queue.get_nowait()
            _event_queue.task_done()
        except queue.Empty:
            return
