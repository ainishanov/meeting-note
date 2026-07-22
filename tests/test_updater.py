import hashlib
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from src.utils.updater import (
    _find_checksum,
    _version_tuple,
    download_verified_update,
    parse_release,
    should_check_for_updates,
)


class UpdaterTest(unittest.TestCase):
    def _release(self, version="0.3.0"):
        base = "https://github.com/ainishanov/meeting-note/releases/download/v0.3.0/"
        return {
            "tag_name": f"v{version}",
            "html_url": "https://github.com/ainishanov/meeting-note/releases/tag/v0.3.0",
            "assets": [
                {
                    "name": f"MeetingNoteSetup-v{version}.exe",
                    "browser_download_url": base + f"MeetingNoteSetup-v{version}.exe",
                },
                {
                    "name": "SHA256SUMS.txt",
                    "browser_download_url": base + "SHA256SUMS.txt",
                },
            ],
        }

    def test_new_installer_is_selected(self):
        update = parse_release(self._release(), "0.2.0")
        self.assertIsNotNone(update)
        self.assertEqual(update.version, "0.3.0")
        self.assertEqual(update.asset.name, "MeetingNoteSetup-v0.3.0.exe")

    def test_same_version_has_no_update(self):
        self.assertIsNone(parse_release(self._release(), "0.3.0"))

    def test_missing_checksum_blocks_update(self):
        release = self._release()
        release["assets"] = release["assets"][:1]
        with self.assertRaises(ValueError):
            parse_release(release, "0.2.0")

    def test_checksum_parser_accepts_standard_format(self):
        digest = "A" * 64
        text = f"{digest} *MeetingNoteSetup-v0.3.0.exe\n"
        self.assertEqual(
            _find_checksum(text, "MeetingNoteSetup-v0.3.0.exe"), digest
        )

    def test_semver_and_daily_check(self):
        self.assertLess(_version_tuple("0.2.9"), _version_tuple("0.3.0"))
        self.assertFalse(should_check_for_updates(100, now=100 + 60))
        self.assertTrue(should_check_for_updates(100, now=100 + 24 * 60 * 60))

    def test_cancelled_download_leaves_no_partial_file(self):
        update = parse_release(self._release(), "0.2.0")
        self.assertIsNotNone(update)
        checksum = hashlib.sha256(b"payload").hexdigest()

        class Response:
            def __init__(self, content):
                self.content = content

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size=-1):
                return self.content

        with tempfile.TemporaryDirectory() as directory:
            responses = [
                Response(
                    f"{checksum} *MeetingNoteSetup-v0.3.0.exe\n".encode()
                ),
                Response(b"payload"),
            ]
            with patch("urllib.request.urlopen", side_effect=responses):
                with self.assertRaises(InterruptedError):
                    download_verified_update(
                        update,
                        Path(directory),
                        cancel_requested=lambda: True,
                    )

            self.assertFalse(
                (Path(directory) / "MeetingNoteSetup-v0.3.0.exe.part").exists()
            )


if __name__ == "__main__":
    unittest.main()
