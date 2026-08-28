"""Verified GitHub Releases update discovery and download helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generic, Optional, TypeVar
from urllib.parse import urlparse


LATEST_RELEASE_API = "https://api.github.com/repos/ainishanov/meeting-note/releases/latest"
RELEASES_PAGE_URL = "https://github.com/ainishanov/meeting-note/releases/latest"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
_ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    release_url: str
    asset: ReleaseAsset
    checksums: ReleaseAsset


class UpdateStage(str, Enum):
    """User-visible stages of the update pipeline."""

    CHECK = "check"
    CHECKSUM = "checksum"
    DOWNLOAD = "download"
    VERIFY = "verify"
    SAVE = "save"
    LAUNCH = "launch"


class UpdateFailureKind(str, Enum):
    """Stable failure categories used by UI copy, retries, and telemetry."""

    NETWORK = "network"
    RELEASE = "release"
    INTEGRITY = "integrity"
    STORAGE = "storage"
    CANCELLED = "cancelled"
    LAUNCH = "launch"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class UpdateFailure:
    stage: UpdateStage
    kind: UpdateFailureKind
    detail: str
    retryable: bool
    cause: Optional[BaseException] = None


class UpdatePipelineError(RuntimeError):
    """An update failure that retains its exact pipeline stage."""

    def __init__(self, failure: UpdateFailure):
        super().__init__(failure.detail)
        self.failure = failure


ResultValue = TypeVar("ResultValue")


@dataclass(frozen=True)
class UpdateResult(Generic[ResultValue]):
    """Typed worker result; success and failure never share an ambiguous value."""

    value: Optional[ResultValue] = None
    failure: Optional[UpdateFailure] = None

    @classmethod
    def success(cls, value: Optional[ResultValue] = None) -> "UpdateResult[ResultValue]":
        return cls(value=value)

    @classmethod
    def failed(cls, failure: UpdateFailure) -> "UpdateResult[ResultValue]":
        return cls(failure=failure)


def should_check_for_updates(last_check_epoch: int, now: Optional[int] = None) -> bool:
    current = int(time.time()) if now is None else int(now)
    return current - int(last_check_epoch or 0) >= CHECK_INTERVAL_SECONDS


def check_for_update(current_version: str, timeout: float = 6.0) -> Optional[UpdateInfo]:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"MeetingNote/{current_version}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_payload = response.read()
    except Exception as error:
        raise _pipeline_error(
            UpdateStage.CHECK,
            _network_or_unknown(error),
            error,
            retryable=True,
        ) from error

    try:
        payload = json.loads(raw_payload.decode("utf-8"))
        return parse_release(payload, current_version)
    except UpdatePipelineError:
        raise
    except Exception as error:
        raise _pipeline_error(
            UpdateStage.CHECK,
            UpdateFailureKind.RELEASE,
            error,
            retryable=False,
        ) from error


def parse_release(payload: dict[str, Any], current_version: str) -> Optional[UpdateInfo]:
    tag = str(payload.get("tag_name") or "").strip()
    latest_version = tag.removeprefix("v")
    if not latest_version or _version_tuple(latest_version) <= _version_tuple(current_version):
        return None

    assets = {
        str(asset.get("name") or ""): ReleaseAsset(
            name=str(asset.get("name") or ""),
            url=str(asset.get("browser_download_url") or ""),
        )
        for asset in payload.get("assets") or []
        if asset.get("name") and asset.get("browser_download_url")
    }

    preferred_names = (
        f"MeetingNoteSetup-v{latest_version}.exe",
        f"MeetingNote-v{latest_version}-windows-x64.zip",
    )
    update_asset = next((assets[name] for name in preferred_names if name in assets), None)
    checksums = assets.get("SHA256SUMS.txt")
    if update_asset is None or checksums is None:
        raise ValueError("The latest release is missing an installer or SHA256SUMS.txt")

    _validate_download_url(update_asset.url)
    _validate_download_url(checksums.url)
    release_url = str(payload.get("html_url") or RELEASES_PAGE_URL)
    return UpdateInfo(
        version=latest_version,
        release_url=release_url,
        asset=update_asset,
        checksums=checksums,
    )


def download_verified_update(
    update: UpdateInfo,
    destination_dir: Path,
    timeout: float = 10.0,
    cancel_requested: Optional[Callable[[], bool]] = None,
) -> Path:
    """Download the selected release asset and verify it against SHA256SUMS.txt."""
    try:
        _validate_download_url(update.asset.url)
        _validate_download_url(update.checksums.url)
    except ValueError as error:
        raise _pipeline_error(
            UpdateStage.CHECKSUM,
            UpdateFailureKind.RELEASE,
            error,
            retryable=False,
        ) from error

    destination_dir = Path(destination_dir)
    try:
        destination_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise _pipeline_error(
            UpdateStage.SAVE,
            UpdateFailureKind.STORAGE,
            error,
            retryable=True,
        ) from error

    try:
        checksums_text = _download_bytes(
            update.checksums.url,
            timeout,
            stage=UpdateStage.CHECKSUM,
        ).decode("utf-8", errors="strict")
        expected_hash = _find_checksum(checksums_text, update.asset.name)
    except UpdatePipelineError:
        raise
    except (UnicodeDecodeError, ValueError) as error:
        raise _pipeline_error(
            UpdateStage.CHECKSUM,
            UpdateFailureKind.RELEASE,
            error,
            retryable=False,
        ) from error

    final_path = destination_dir / update.asset.name
    partial_path = final_path.with_suffix(final_path.suffix + ".part")
    digest = hashlib.sha256()
    try:
        request = urllib.request.Request(
            update.asset.url,
            headers={"User-Agent": "MeetingNote-Updater"},
        )
        try:
            response_context = urllib.request.urlopen(request, timeout=timeout)
        except Exception as error:
            raise _pipeline_error(
                UpdateStage.DOWNLOAD,
                _network_or_unknown(error),
                error,
                retryable=True,
            ) from error

        with response_context as response:
            try:
                output_context = partial_path.open("wb")
            except OSError as error:
                raise _pipeline_error(
                    UpdateStage.SAVE,
                    UpdateFailureKind.STORAGE,
                    error,
                    retryable=True,
                ) from error

            with output_context as output:
                while True:
                    if cancel_requested and cancel_requested():
                        error = InterruptedError("Update download was cancelled")
                        raise _pipeline_error(
                            UpdateStage.DOWNLOAD,
                            UpdateFailureKind.CANCELLED,
                            error,
                            retryable=False,
                        ) from error
                    try:
                        chunk = response.read(1024 * 1024)
                    except Exception as error:
                        raise _pipeline_error(
                            UpdateStage.DOWNLOAD,
                            _network_or_unknown(error),
                            error,
                            retryable=True,
                        ) from error
                    if not chunk:
                        break
                    digest.update(chunk)
                    try:
                        output.write(chunk)
                    except OSError as error:
                        raise _pipeline_error(
                            UpdateStage.SAVE,
                            UpdateFailureKind.STORAGE,
                            error,
                            retryable=True,
                        ) from error

        actual_hash = digest.hexdigest().upper()
        if actual_hash != expected_hash:
            error = ValueError("Downloaded update failed SHA-256 verification")
            raise _pipeline_error(
                UpdateStage.VERIFY,
                UpdateFailureKind.INTEGRITY,
                error,
                retryable=True,
            ) from error
        try:
            os.replace(partial_path, final_path)
        except OSError as error:
            raise _pipeline_error(
                UpdateStage.SAVE,
                UpdateFailureKind.STORAGE,
                error,
                retryable=True,
            ) from error
        return final_path
    finally:
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            pass


def classify_update_failure(
    error: BaseException,
    default_stage: UpdateStage,
) -> UpdateFailure:
    """Convert unexpected worker or installer errors to the stable UI contract."""
    if isinstance(error, UpdatePipelineError):
        return error.failure
    if isinstance(error, InterruptedError):
        return UpdateFailure(
            stage=default_stage,
            kind=UpdateFailureKind.CANCELLED,
            detail=str(error),
            retryable=False,
            cause=error,
        )

    kind = _network_or_unknown(error)
    if default_stage == UpdateStage.LAUNCH:
        kind = UpdateFailureKind.LAUNCH
    elif isinstance(error, OSError) and kind == UpdateFailureKind.UNKNOWN:
        kind = UpdateFailureKind.STORAGE
    return UpdateFailure(
        stage=default_stage,
        kind=kind,
        detail=str(error) or type(error).__name__,
        retryable=True,
        cause=error,
    )


def _download_bytes(url: str, timeout: float, *, stage: UpdateStage) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "MeetingNote-Updater"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as error:
        raise _pipeline_error(
            stage,
            _network_or_unknown(error),
            error,
            retryable=True,
        ) from error


def _find_checksum(checksums_text: str, asset_name: str) -> str:
    for line in checksums_text.splitlines():
        match = re.fullmatch(r"\s*([A-Fa-f0-9]{64})\s+\*?(.+?)\s*", line)
        if match and match.group(2).replace("\\", "/").split("/")[-1] == asset_name:
            return match.group(1).upper()
    raise ValueError(f"No SHA-256 entry found for {asset_name}")


def _version_tuple(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", version.strip())
    if not match:
        raise ValueError(f"Unsupported version: {version}")
    return tuple(int(part) for part in match.groups())


def _validate_download_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_DOWNLOAD_HOSTS:
        raise ValueError("Update URL is not an approved GitHub HTTPS download")


def _network_or_unknown(error: BaseException) -> UpdateFailureKind:
    if isinstance(
        error,
        (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            socket.timeout,
        ),
    ):
        return UpdateFailureKind.NETWORK
    return UpdateFailureKind.UNKNOWN


def _pipeline_error(
    stage: UpdateStage,
    kind: UpdateFailureKind,
    error: BaseException,
    *,
    retryable: bool,
) -> UpdatePipelineError:
    return UpdatePipelineError(
        UpdateFailure(
            stage=stage,
            kind=kind,
            detail=str(error) or type(error).__name__,
            retryable=retryable,
            cause=error,
        )
    )
