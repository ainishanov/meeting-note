import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.build_policy import (
    PYSIDE_MSVC_RUNTIME_DLLS,
    assert_locked_environment,
    assert_trusted_binary_sources,
    normalize_windows_binaries,
    run_frozen_smoke_test,
    sanitized_build_environment,
    validate_frozen_archive,
)


class BuildPolicyTests(unittest.TestCase):
    def test_lock_mismatch_stops_the_build(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock_file = Path(temporary_directory) / "requirements-lock.txt"
            lock_file.write_text("example-package==2.0.0 \\\n", encoding="utf-8")

            with (
                patch("scripts.build_policy.version", return_value="1.0.0"),
                self.assertRaisesRegex(RuntimeError, "expected 2.0.0, found 1.0.0"),
            ):
                assert_locked_environment(lock_file)

    def test_build_environment_drops_external_dll_and_python_overrides(self):
        environment = sanitized_build_environment(
            {
                "SystemRoot": r"C:\Windows",
                "PATH": r"C:\foreign-tools;C:\more-tools",
                "PYTHONPATH": r"C:\foreign-python",
                "PYTHONHOME": r"C:\wrong-python",
                "QT_PLUGIN_PATH": r"C:\wrong-qt",
                "QML2_IMPORT_PATH": r"C:\wrong-qml",
            },
            python_executable=r"C:\project\venv\Scripts\python.exe",
        )

        path_entries = environment["PATH"].split(os.pathsep)
        self.assertNotIn(r"C:\foreign-tools", path_entries)
        self.assertNotIn(r"C:\more-tools", path_entries)
        self.assertEqual(environment["PYTHONNOUSERSITE"], "1")
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("PYTHONHOME", environment)
        self.assertNotIn("QT_PLUGIN_PATH", environment)
        self.assertNotIn("QML2_IMPORT_PATH", environment)

    def test_untrusted_binary_source_stops_the_build(self):
        with tempfile.TemporaryDirectory() as trusted_directory:
            binaries = [
                (
                    "icuuc.dll",
                    r"C:\developer-tools\poppler\icuuc.dll",
                    "BINARY",
                )
            ]

            with self.assertRaisesRegex(RuntimeError, "Untrusted DLL sources"):
                assert_trusted_binary_sources(binaries, [trusted_directory])

    def test_stale_pip_directory_stops_the_build_inside_trusted_root(self):
        with tempfile.TemporaryDirectory() as trusted_directory:
            stale_source = Path(trusted_directory) / "~umpy.libs" / "old.dll"
            binaries = [("old.dll", str(stale_source), "BINARY")]

            with self.assertRaisesRegex(RuntimeError, "old.dll"):
                assert_trusted_binary_sources(binaries, [trusted_directory])

    def test_binary_normalization_removes_windows_dlls_and_pins_msvc(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            pyside_directory = Path(temporary_directory)
            for filename in PYSIDE_MSVC_RUNTIME_DLLS:
                (pyside_directory / filename).write_bytes(b"runtime")

            result = normalize_windows_binaries(
                [
                    ("icuuc.dll", r"C:\foreign\icuuc.dll", "BINARY"),
                    ("api-ms-win-core-file-l1-1-0.dll", r"C:\foreign\api.dll", "BINARY"),
                    ("VCRUNTIME140.dll", r"C:\old\VCRUNTIME140.dll", "BINARY"),
                    ("PySide6\\VCRUNTIME140.dll", r"C:\qt\VCRUNTIME140.dll", "BINARY"),
                    ("PySide6\\Qt6Core.dll", r"C:\qt\Qt6Core.dll", "BINARY"),
                ],
                pyside_directory=pyside_directory,
            )

            destinations = [entry[0] for entry in result]
            self.assertNotIn("icuuc.dll", destinations)
            self.assertNotIn("api-ms-win-core-file-l1-1-0.dll", destinations)
            self.assertIn("PySide6\\VCRUNTIME140.dll", destinations)
            self.assertIn("PySide6\\Qt6Core.dll", destinations)
            for filename in PYSIDE_MSVC_RUNTIME_DLLS:
                self.assertEqual(destinations.count(filename), 1)

    def test_archive_validation_rejects_foreign_icu(self):
        archive = Mock()
        archive.toc = {
            "PySide6\\QtCore.pyd": (),
            "PySide6\\Qt6Core.dll": (),
            "PySide6\\QtWidgets.pyd": (),
            "shiboken6\\shiboken6.abi3.dll": (),
            "icuuc.dll": (),
        }
        with patch("PyInstaller.archive.readers.CArchiveReader", return_value=archive):
            with self.assertRaisesRegex(RuntimeError, "icuuc.dll"):
                validate_frozen_archive("MeetingNote.exe")

    def test_frozen_smoke_test_requires_zero_exit_code(self):
        completed = Mock(returncode=127)
        with patch("scripts.build_policy.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "exit code 127"):
                run_frozen_smoke_test("MeetingNote.exe")


if __name__ == "__main__":
    unittest.main()
