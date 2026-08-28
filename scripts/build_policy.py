"""Deterministic Windows packaging policy for Meeting Note."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Iterable, Mapping, Sequence


BinaryEntry = tuple[str, str, str]

PYSIDE_MSVC_RUNTIME_DLLS = (
    "concrt140.dll",
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "msvcp140_codecvt_ids.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
)

_WINDOWS_SYSTEM_DLL_PATTERNS = (
    re.compile(r"api-ms-win-.*\.dll", re.IGNORECASE),
    re.compile(r"ext-ms-win-.*\.dll", re.IGNORECASE),
    re.compile(r"icu(?:dt\d*|in|uc)\.dll", re.IGNORECASE),
    re.compile(r"ucrtbase\.dll", re.IGNORECASE),
)

_REQUIRED_ARCHIVE_MEMBERS = frozenset(
    {
        "PySide6\\QtCore.pyd",
        "PySide6\\Qt6Core.dll",
        "PySide6\\QtWidgets.pyd",
        "shiboken6\\shiboken6.abi3.dll",
    }
)

_OTHER_QT_BINDINGS = ("PyQt5\\", "PyQt6\\", "PySide2\\")
_LOCKED_REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")


def assert_locked_environment(lock_file: str | Path) -> None:
    """Require every release dependency to match its hash-locked version."""
    lock_path = Path(lock_file).resolve()
    mismatches: list[str] = []
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        match = _LOCKED_REQUIREMENT.match(line)
        if not match:
            continue

        package, expected = match.groups()
        try:
            actual = version(package)
        except PackageNotFoundError:
            actual = "missing"
        if actual != expected:
            mismatches.append(f"- {package}: expected {expected}, found {actual}")

    if mismatches:
        raise RuntimeError(
            "The build environment does not match requirements-lock.txt. Run "
            "'python -m pip install --require-hashes -r requirements-lock.txt' "
            "before building:\n" + "\n".join(mismatches)
        )


def sanitized_build_environment(
    environ: Mapping[str, str] | None = None,
    *,
    python_executable: str | Path | None = None,
) -> dict[str, str]:
    """Return an environment whose DLL lookup cannot inherit developer tools."""
    source = dict(os.environ if environ is None else environ)
    python_path = Path(python_executable or sys.executable).resolve()
    windows_root = Path(source.get("SystemRoot", r"C:\Windows")).resolve()

    path_entries = (
        python_path.parent,
        Path(sys.base_prefix).resolve(),
        windows_root / "System32",
        windows_root,
    )
    unique_entries: list[str] = []
    seen: set[str] = set()
    for entry in path_entries:
        normalized = os.path.normcase(str(entry))
        if normalized not in seen:
            unique_entries.append(str(entry))
            seen.add(normalized)

    source["PATH"] = os.pathsep.join(unique_entries)
    source["PYTHONNOUSERSITE"] = "1"
    for name in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        source.pop(name, None)
    return source


def assert_trusted_binary_sources(
    binaries: Iterable[BinaryEntry],
    trusted_roots: Iterable[str | Path],
) -> None:
    """Reject DLLs resolved from tools outside the project build environment."""
    roots = tuple(Path(root).resolve() for root in trusted_roots)
    untrusted: list[BinaryEntry] = []

    for destination, source, kind in binaries:
        source_path = Path(source).resolve()
        is_stale_package = any(part.startswith("~") for part in source_path.parts)
        if is_stale_package or not any(
            _is_relative_to(source_path, root) for root in roots
        ):
            untrusted.append((destination, source, kind))

    if not untrusted:
        return

    details = "\n".join(
        f"- {destination} <- {source}" for destination, source, _ in untrusted
    )
    raise RuntimeError(
        "Untrusted DLL sources were found. Build with scripts/build_windows.py "
        "so PATH cannot leak developer-tool binaries into the release:\n"
        f"{details}"
    )


def normalize_windows_binaries(
    binaries: Sequence[BinaryEntry],
    *,
    pyside_directory: str | Path,
) -> list[BinaryEntry]:
    """Remove Windows-owned DLLs and pin one compatible MSVC runtime set."""
    pyside_path = Path(pyside_directory).resolve()
    runtime_names = {name.casefold() for name in PYSIDE_MSVC_RUNTIME_DLLS}
    normalized: list[BinaryEntry] = []

    for entry in binaries:
        destination = entry[0].replace("/", "\\")
        if _is_root_member(destination):
            filename = Path(destination).name
            if _is_windows_system_dll(filename):
                continue
            if filename.casefold() in runtime_names:
                continue
        normalized.append(entry)

    for filename in PYSIDE_MSVC_RUNTIME_DLLS:
        source = pyside_path / filename
        if not source.is_file():
            raise RuntimeError(f"PySide6 runtime DLL is missing: {source}")
        normalized.append((filename, str(source), "BINARY"))

    return normalized


def validate_frozen_archive(executable: str | Path) -> None:
    """Validate the final one-file archive, not only PyInstaller's analysis."""
    from PyInstaller.archive.readers import CArchiveReader

    executable_path = Path(executable).resolve()
    members = set(CArchiveReader(str(executable_path)).toc)

    missing = sorted(_REQUIRED_ARCHIVE_MEMBERS - members)
    forbidden = sorted(
        member
        for member in members
        if (
            (_is_root_member(member) and _is_windows_system_dll(Path(member).name))
            or member.startswith(_OTHER_QT_BINDINGS)
        )
    )
    if missing or forbidden:
        problems: list[str] = []
        if missing:
            problems.append("missing: " + ", ".join(missing))
        if forbidden:
            problems.append("forbidden: " + ", ".join(forbidden))
        raise RuntimeError("Invalid frozen archive (" + "; ".join(problems) + ")")


def run_frozen_smoke_test(executable: str | Path, *, timeout: int = 30) -> None:
    """Import and initialize the bundled Qt runtime in the finished executable."""
    executable_path = Path(executable).resolve()
    result = subprocess.run(
        [str(executable_path), "--runtime-smoke-test"],
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Frozen runtime smoke test failed with exit code {result.returncode}: "
            f"{executable_path}"
        )


def trusted_build_roots(project_root: str | Path) -> tuple[Path, ...]:
    """Return the only roots from which release binaries may be collected."""
    windows_root = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()
    return (
        Path(project_root).resolve(),
        Path(sys.prefix).resolve(),
        Path(sys.base_prefix).resolve(),
        windows_root,
    )


def _is_windows_system_dll(filename: str) -> bool:
    return any(pattern.fullmatch(filename) for pattern in _WINDOWS_SYSTEM_DLL_PATTERNS)


def _is_root_member(path: str) -> bool:
    return "\\" not in path.replace("/", "\\")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
