import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.ui import taskbar_identity


class TaskbarIdentityTests(unittest.TestCase):
    def test_frozen_exe_keeps_its_embedded_identity(self):
        window = Mock()
        with (
            patch.object(taskbar_identity.sys, "platform", "win32"),
            patch.object(taskbar_identity.sys, "frozen", True, create=True),
            patch.object(taskbar_identity, "_set_window_properties") as set_properties,
        ):
            taskbar_identity.apply_to_window(window)

        window.winId.assert_not_called()
        set_properties.assert_not_called()

    def test_other_platforms_are_left_alone(self):
        window = Mock()
        with (
            patch.object(taskbar_identity.sys, "platform", "darwin"),
            patch.object(taskbar_identity, "_set_window_properties") as set_properties,
        ):
            taskbar_identity.apply_to_window(window)

        set_properties.assert_not_called()

    def test_source_run_sets_window_identity(self):
        window = Mock()
        window.winId.return_value = 4242
        with (
            patch.object(taskbar_identity.sys, "platform", "win32"),
            patch.object(taskbar_identity, "_set_window_properties") as set_properties,
        ):
            taskbar_identity.apply_to_window(window)

        hwnd, properties = set_properties.call_args.args
        self.assertEqual(hwnd, 4242)
        self.assertEqual(properties[-1], (taskbar_identity._PID_ID, taskbar_identity.APP_USER_MODEL_ID))

    def test_shell_failure_does_not_stop_startup(self):
        window = Mock()
        window.winId.return_value = 4242
        with (
            patch.object(taskbar_identity.sys, "platform", "win32"),
            patch.object(taskbar_identity, "_set_window_properties", side_effect=OSError("no shell")),
        ):
            taskbar_identity.apply_to_window(window)

    def test_pinned_button_relaunches_the_app_with_its_icon(self):
        properties = dict(taskbar_identity.window_properties())

        command = properties[taskbar_identity._PID_RELAUNCH_COMMAND]
        self.assertTrue(command.endswith(f'"{taskbar_identity.PROJECT_ROOT / "run.py"}"'))
        self.assertEqual(properties[taskbar_identity._PID_RELAUNCH_NAME], "Meeting Note")

        icon_path, index = properties[taskbar_identity._PID_RELAUNCH_ICON].rsplit(",", 1)
        self.assertEqual(index, "0")
        self.assertTrue(Path(icon_path).is_file())


if __name__ == "__main__":
    unittest.main()
