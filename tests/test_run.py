import unittest
from unittest.mock import patch

import run


class RunEntryPointTests(unittest.TestCase):
    def test_runtime_smoke_flag_does_not_start_application(self):
        with patch("run.runtime_smoke_test", return_value=0) as smoke_test:
            self.assertEqual(run.main(["run.py", "--runtime-smoke-test"]), 0)

        smoke_test.assert_called_once_with()

    def test_runtime_smoke_failure_returns_stable_exit_code(self):
        with patch("run.runtime_smoke_test", side_effect=ImportError("broken Qt")):
            self.assertEqual(
                run.main(["run.py", "--runtime-smoke-test"]),
                run.RUNTIME_ERROR_EXIT_CODE,
            )

    def test_normal_startup_uses_native_recovery_when_qt_is_broken(self):
        with (
            patch("run.load_qt_runtime", side_effect=ImportError("broken Qt")),
            patch("run.show_runtime_recovery") as recovery,
        ):
            self.assertEqual(run.main(["run.py"]), run.RUNTIME_ERROR_EXIT_CODE)

        recovery.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
