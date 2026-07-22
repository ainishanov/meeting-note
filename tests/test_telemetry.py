import unittest

from src.utils.telemetry import _scrub_event, duration_bucket, sanitize_text


class TelemetryPrivacyTest(unittest.TestCase):
    def test_duration_is_coarsened(self):
        self.assertEqual(duration_bucket(None), "unknown")
        self.assertEqual(duration_bucket(30), "under_1m")
        self.assertEqual(duration_bucket(120), "1_to_5m")
        self.assertEqual(duration_bucket(900), "15_to_30m")
        self.assertEqual(duration_bucket(7200), "over_60m")

    def test_sensitive_strings_are_redacted(self):
        raw = (
            r"C:\Users\private-user\meeting.txt "
            "person@example.com sk-secretvalue1234567890 "
            "Bearer tokenvalue1234567890"
        )
        sanitized = sanitize_text(raw)

        self.assertNotIn("private-user", sanitized)
        self.assertNotIn("person@example.com", sanitized)
        self.assertNotIn("secretvalue", sanitized)
        self.assertNotIn("tokenvalue", sanitized)

    def test_final_scrubber_keeps_only_anonymous_user_id(self):
        event = {
            "server_name": "DESKTOP-PERSONAL",
            "request": {"url": "file:///private"},
            "breadcrumbs": ["private log"],
            "user": {
                "id": "anon_0123456789abcdef0123456789abcdef",
                "email": "person@example.com",
            },
            "message": r"Failure in C:\Users\private-user\meeting.txt",
        }

        scrubbed = _scrub_event(event, {})

        self.assertNotIn("server_name", scrubbed)
        self.assertNotIn("request", scrubbed)
        self.assertNotIn("breadcrumbs", scrubbed)
        self.assertEqual(
            scrubbed["user"],
            {"id": "anon_0123456789abcdef0123456789abcdef"},
        )
        self.assertNotIn("private-user", scrubbed["message"])

    def test_non_anonymous_user_is_removed(self):
        scrubbed = _scrub_event({"user": {"id": "real-person"}}, {})
        self.assertNotIn("user", scrubbed)


if __name__ == "__main__":
    unittest.main()
