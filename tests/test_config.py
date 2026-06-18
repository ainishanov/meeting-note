import tempfile
import unittest
from pathlib import Path

from src.utils.config import save_env_settings


class SaveEnvSettingsTest(unittest.TestCase):
    def test_updates_existing_lines_and_formats_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "SAMPLE_RATE=44100\n"
                "AUDIO_DEVICE_INDEX=12\n"
                "# keep this\n",
                encoding="utf-8",
            )

            save_env_settings(
                {
                    "SAMPLE_RATE": 16000,
                    "AUDIO_DEVICE_INDEX": None,
                    "AUTO_TRIGGER_ENABLED": False,
                },
                env_path=env_path,
            )

            content = env_path.read_text(encoding="utf-8")
            self.assertIn("SAMPLE_RATE=16000", content)
            self.assertIn("AUDIO_DEVICE_INDEX=\n", content)
            self.assertIn("AUTO_TRIGGER_ENABLED=false", content)
            self.assertIn("# keep this", content)


if __name__ == "__main__":
    unittest.main()
