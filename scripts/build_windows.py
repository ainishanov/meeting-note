"""Build and verify a deterministic Windows executable."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_policy import (
    assert_locked_environment,
    run_frozen_smoke_test,
    sanitized_build_environment,
    validate_frozen_archive,
)


def build_windows_executable(dist_path: Path, work_path: Path) -> Path:
    """Build MeetingNote.exe and enforce the frozen-runtime release contract."""
    assert_locked_environment(PROJECT_ROOT / "requirements-lock.txt")
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--distpath",
        str(dist_path),
        "--workpath",
        str(work_path),
        str(PROJECT_ROOT / "MeetingNote.spec"),
    ]
    subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=sanitized_build_environment(python_executable=sys.executable),
        check=True,
    )

    executable = dist_path.resolve() / "MeetingNote.exe"
    validate_frozen_archive(executable)
    run_frozen_smoke_test(executable)
    return executable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distpath", type=Path, default=PROJECT_ROOT / "dist")
    parser.add_argument(
        "--workpath", type=Path, default=PROJECT_ROOT / "build" / "pyinstaller"
    )
    args = parser.parse_args()

    executable = build_windows_executable(args.distpath, args.workpath)
    print(f"Verified Windows executable: {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
