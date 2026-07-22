"""Verified GitHub Releases update discovery and download helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
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
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return parse_release(payload, current_version)


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
    _validate_download_url(update.asset.url)
    _validate_download_url(update.checksums.url)
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)

    checksums_text = _download_bytes(update.checksums.url, timeout).decode(
        "utf-8", errors="strict"
    )
    expected_hash = _find_checksum(checksums_text, update.asset.name)

    final_path = destination_dir / update.asset.name
    partial_path = final_path.with_suffix(final_path.suffix + ".part")
    digest = hashlib.sha256()
    try:
        request = urllib.request.Request(
            update.asset.url,
            headers={"User-Agent": "MeetingNote-Updater"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            with partial_path.open("wb") as output:
                while True:
                    if cancel_requested and cancel_requested():
                        raise InterruptedError("Update download was cancelled")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    output.write(chunk)

        actual_hash = digest.hexdigest().upper()
        if actual_hash != expected_hash:
            raise ValueError("Downloaded update failed SHA-256 verification")
        os.replace(partial_path, final_path)
        return final_path
    finally:
        if partial_path.exists():
            partial_path.unlink(missing_ok=True)


def _download_bytes(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "MeetingNote-Updater"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


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
