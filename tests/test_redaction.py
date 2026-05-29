import os
import unittest
from unittest.mock import patch

from nworks_mail_mcp import redaction
from nworks_mail_mcp.redaction import redact_text


class RedactionTest(unittest.TestCase):
    def tearDown(self):
        redaction._extra_patterns.cache_clear()

    def test_redacts_default_sensitive_values(self):
        token = (
            "eyJhbGciOiJIUzI1NiJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        text = (
            "rrn 900101-1234567 "
            f"jwt {token} "
            "Authorization: Bearer abcdefghijklmnop "
            "password='open-sesame' "
            "https://example.test/callback?access_token=secret-token&ok=1"
        )

        result = redact_text(text)

        self.assertIn("[REDACTED:RRN]", result)
        self.assertIn("[REDACTED:JWT]", result)
        self.assertIn("[REDACTED:BEARER_TOKEN]", result)
        self.assertIn("password='[REDACTED:SECRET]'", result)
        self.assertIn("access_token=[REDACTED:URL_TOKEN]", result)
        self.assertNotIn("900101-1234567", result)
        self.assertNotIn("open-sesame", result)
        self.assertNotIn("secret-token", result)

    def test_does_not_redact_email_phone_or_ordinary_numbers(self):
        text = (
            "sender@example.com 010-1234-5678 "
            "2026-05-29 UID 121 order 202605290001"
        )

        self.assertEqual(redact_text(text), text)

    def test_applies_extra_json_patterns(self):
        with patch.dict(
            os.environ,
            {"NWORKS_REDACTION_EXTRA_PATTERNS_JSON": '["Project-[0-9]+"]'},
        ):
            redaction._extra_patterns.cache_clear()

            self.assertEqual(
                redact_text("Project-123 is confidential"),
                "[REDACTED:CUSTOM] is confidential",
            )

    def test_rejects_invalid_extra_json(self):
        with patch.dict(
            os.environ,
            {"NWORKS_REDACTION_EXTRA_PATTERNS_JSON": "not-json"},
        ):
            redaction._extra_patterns.cache_clear()

            with self.assertRaises(ValueError):
                redact_text("hello")

    def test_rejects_invalid_extra_regex(self):
        with patch.dict(
            os.environ,
            {"NWORKS_REDACTION_EXTRA_PATTERNS_JSON": '["["]'},
        ):
            redaction._extra_patterns.cache_clear()

            with self.assertRaises(ValueError):
                redact_text("hello")


if __name__ == "__main__":
    unittest.main()
