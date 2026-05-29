import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nworks_mail_mcp.imap_client import MailBody, MailReadResult, MailSummary
from nworks_mail_mcp.server import (
    COMPENSATION_BLOCK_BODY,
    COMPENSATION_BLOCK_REASON,
    read_message_body,
    read_messages,
    read_new_messages,
    search_messages_by_body,
)


class ServerToolTest(unittest.TestCase):
    def test_read_new_messages_uses_checkpoint_and_updates_after_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"

            with patch("nworks_mail_mcp.server.load_state_path", return_value=state_path):
                with patch("nworks_mail_mcp.server.imap_list_messages_since_uid") as list_since:
                    list_since.return_value = MailReadResult(
                        messages=[
                            MailSummary(
                                uid="121",
                                subject="New mail",
                                sender="sender@example.com",
                                date="Thu, 28 May 2026 10:00:00 +0900",
                            )
                        ],
                        uidvalidity=777,
                    )

                    first = read_new_messages(folder="INBOX", limit=50)
                    second = read_new_messages(folder="INBOX", limit=50)

            self.assertEqual(first["previous_last_uid"], None)
            self.assertEqual(first["new_last_uid"], 121)
            self.assertEqual(first["uidvalidity"], 777)
            self.assertEqual(second["previous_last_uid"], 121)
            self.assertEqual(second["new_last_uid"], 121)
            self.assertEqual(list_since.call_args_list[0].args, ("INBOX", None, 50))
            self.assertEqual(list_since.call_args_list[1].args, ("INBOX", 121, 50))

    def test_read_new_messages_resets_checkpoint_when_uidvalidity_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"

            with patch("nworks_mail_mcp.server.load_state_path", return_value=state_path):
                with patch("nworks_mail_mcp.server.imap_list_messages_since_uid") as list_since:
                    list_since.side_effect = [
                        MailReadResult(messages=[], uidvalidity=777),
                        MailReadResult(messages=[], uidvalidity=888),
                    ]

                    read_new_messages(folder="INBOX", limit=50)
                    read_new_messages(folder="INBOX", limit=50)

            self.assertEqual(list_since.call_args_list[0].args, ("INBOX", None, 50))
            self.assertEqual(list_since.call_args_list[1].args, ("INBOX", None, 50))

    def test_read_new_messages_keeps_checkpoint_when_no_new_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"

            with patch("nworks_mail_mcp.server.load_state_path", return_value=state_path):
                with patch("nworks_mail_mcp.server.imap_list_messages_since_uid") as list_since:
                    list_since.side_effect = [
                        MailReadResult(
                            messages=[
                                MailSummary(
                                    uid="121",
                                    subject="New mail",
                                    sender="sender@example.com",
                                    date="Thu, 28 May 2026 10:00:00 +0900",
                                )
                            ],
                            uidvalidity=777,
                        ),
                        MailReadResult(messages=[], uidvalidity=777),
                    ]

                    read_new_messages(folder="INBOX", limit=50)
                    second = read_new_messages(folder="INBOX", limit=50)

            self.assertEqual(second["previous_last_uid"], 121)
            self.assertEqual(second["new_last_uid"], 121)

    def test_read_messages_marks_compensation_subjects_as_blocked(self):
        with patch("nworks_mail_mcp.server.imap_list_messages") as list_messages:
            list_messages.return_value = [
                MailSummary(
                    uid="121",
                    subject="2026 연봉 안내",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                )
            ]

            result = read_messages(folder="INBOX", limit=10)

        self.assertTrue(result[0]["body_read_blocked"])
        self.assertEqual(result[0]["block_reason"], COMPENSATION_BLOCK_REASON)
        self.assertEqual(result[0]["subject"], "2026 연봉 안내")

    def test_read_new_messages_marks_only_message_entries_as_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"

            with patch("nworks_mail_mcp.server.load_state_path", return_value=state_path):
                with patch("nworks_mail_mcp.server.imap_list_messages_since_uid") as list_since:
                    list_since.return_value = MailReadResult(
                        messages=[
                            MailSummary(
                                uid="121",
                                subject="성과급 지급 안내",
                                sender="sender@example.com",
                                date="Thu, 28 May 2026 10:00:00 +0900",
                            )
                        ],
                        uidvalidity=777,
                    )

                    result = read_new_messages(folder="INBOX", limit=50)

        self.assertEqual(result["uidvalidity"], 777)
        self.assertEqual(result["new_last_uid"], 121)
        self.assertTrue(result["messages"][0]["body_read_blocked"])
        self.assertEqual(
            result["messages"][0]["block_reason"],
            COMPENSATION_BLOCK_REASON,
        )

    def test_rejects_invalid_limits(self):
        for invalid_limit in (0, -1, 501):
            with self.subTest(limit=invalid_limit):
                with self.assertRaises(ValueError):
                    read_messages(folder="INBOX", limit=invalid_limit)
                with self.assertRaises(ValueError):
                    read_new_messages(folder="INBOX", limit=invalid_limit)

    def test_read_message_body_returns_mail_body_dict(self):
        with patch("nworks_mail_mcp.server.imap_get_message_summary") as get_summary:
            with patch("nworks_mail_mcp.server.imap_get_message_body") as get_body:
                get_summary.return_value = MailSummary(
                    uid="121",
                    subject="Body mail",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                )
                get_body.return_value = MailBody(
                    uid="121",
                    subject="Body mail",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="본문 내용입니다. password=secret-value",
                    body_text_type="plain",
                    truncated=False,
                )

                result = read_message_body(folder="INBOX", uid="121", max_chars=1000)

        self.assertEqual(result["uid"], "121")
        self.assertEqual(result["body"], "본문 내용입니다. password=[REDACTED:SECRET]")
        self.assertEqual(result["body_text_type"], "plain")
        self.assertFalse(result["truncated"])
        self.assertFalse(result["blocked"])
        self.assertFalse(result["can_override"])
        get_body.assert_called_once_with("INBOX", "121", None)

    def test_read_message_body_blocks_compensation_subject_without_fetching_body(self):
        with patch("nworks_mail_mcp.server.imap_get_message_summary") as get_summary:
            with patch("nworks_mail_mcp.server.imap_get_message_body") as get_body:
                get_summary.return_value = MailSummary(
                    uid="121",
                    subject="2026 연봉 안내",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                )

                result = read_message_body(folder="INBOX", uid="121", max_chars=1000)

        self.assertEqual(result["body"], COMPENSATION_BLOCK_BODY)
        self.assertEqual(result["body_text_type"], "blocked")
        self.assertTrue(result["blocked"])
        self.assertTrue(result["can_override"])
        self.assertEqual(result["block_reason"], COMPENSATION_BLOCK_REASON)
        get_body.assert_not_called()

    def test_read_message_body_allows_explicit_compensation_override(self):
        with patch("nworks_mail_mcp.server.imap_get_message_summary") as get_summary:
            with patch("nworks_mail_mcp.server.imap_get_message_body") as get_body:
                get_summary.return_value = MailSummary(
                    uid="121",
                    subject="2026 연봉 안내",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                )
                get_body.return_value = MailBody(
                    uid="121",
                    subject="2026 연봉 안내",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="확인된 내용입니다.",
                    body_text_type="plain",
                    truncated=False,
                )

                result = read_message_body(
                    folder="INBOX",
                    uid="121",
                    max_chars=1000,
                    allow_blocked_body=True,
                )

        self.assertEqual(result["body"], "확인된 내용입니다.")
        self.assertFalse(result["blocked"])
        get_body.assert_called_once_with("INBOX", "121", None)

    def test_read_message_body_truncates_after_redaction(self):
        with patch("nworks_mail_mcp.server.imap_get_message_summary") as get_summary:
            with patch("nworks_mail_mcp.server.imap_get_message_body") as get_body:
                get_summary.return_value = MailSummary(
                    uid="121",
                    subject="Body mail",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                )
                get_body.return_value = MailBody(
                    uid="121",
                    subject="Body mail",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="password=secret-value",
                    body_text_type="plain",
                    truncated=False,
                )

                result = read_message_body(folder="INBOX", uid="121", max_chars=10)

        self.assertEqual(result["body"], "password=[")
        self.assertTrue(result["truncated"])

    def test_read_message_body_redacts_before_truncating(self):
        with patch("nworks_mail_mcp.server.imap_get_message_summary") as get_summary:
            with patch("nworks_mail_mcp.server.imap_get_message_body") as get_body:
                get_summary.return_value = MailSummary(
                    uid="121",
                    subject="Body mail",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                )
                get_body.return_value = MailBody(
                    uid="121",
                    subject="Body mail",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="Authorization: Bearer abcdefghijklmnop",
                    body_text_type="plain",
                    truncated=False,
                )

                result = read_message_body(folder="INBOX", uid="121", max_chars=22)

        self.assertEqual(result["body"], "[REDACTED:BEARER_TOKEN")
        self.assertTrue(result["truncated"])
        self.assertNotIn("Bearer abc", result["body"])

    def test_read_message_body_keeps_email_and_phone_unmasked(self):
        with patch("nworks_mail_mcp.server.imap_get_message_summary") as get_summary:
            with patch("nworks_mail_mcp.server.imap_get_message_body") as get_body:
                get_summary.return_value = MailSummary(
                    uid="121",
                    subject="Body mail",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                )
                get_body.return_value = MailBody(
                    uid="121",
                    subject="Body mail",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="sender@example.com 010-1234-5678",
                    body_text_type="plain",
                    truncated=False,
                )

                result = read_message_body(folder="INBOX", uid="121", max_chars=1000)

        self.assertEqual(result["sender"], "sender@example.com")
        self.assertEqual(result["body"], "sender@example.com 010-1234-5678")

    def test_search_messages_by_body_skips_compensation_subjects_by_default(self):
        with patch("nworks_mail_mcp.server.imap_search_messages_by_body") as search:
            search.return_value = [
                MailBody(
                    uid="121",
                    subject="Body mail",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="본문 내용입니다.",
                    body_text_type="plain",
                    truncated=False,
                )
            ]

            result = search_messages_by_body(
                folder="INBOX",
                query="keyword",
                limit=3,
                max_scan=20,
                max_body_chars=2000,
            )

        self.assertEqual(result[0]["uid"], "121")
        self.assertIn("연봉", search.call_args.args[5])

    def test_search_messages_by_body_returns_matching_body_dicts(self):
        with patch("nworks_mail_mcp.server.imap_search_messages_by_body") as search:
            search.return_value = [
                MailBody(
                    uid="122",
                    subject="Match",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="Project keyword update",
                    body_text_type="plain",
                    truncated=False,
                )
            ]

            result = search_messages_by_body(
                folder="INBOX",
                query="keyword",
                limit=3,
                max_scan=20,
                max_body_chars=2000,
            )

        self.assertEqual(result[0]["uid"], "122")
        self.assertEqual(result[0]["body"], "Project keyword update")
        search.assert_called_once_with(
            "INBOX",
            "keyword",
            3,
            20,
            None,
            (
                "연봉",
                "성과급",
                "보너스",
                "인센티브",
                "보상",
                "급여",
                "임금",
            ),
        )

    def test_search_messages_by_body_allows_blocked_subject_override(self):
        with patch("nworks_mail_mcp.server.imap_search_messages_by_body") as search:
            search.return_value = [
                MailBody(
                    uid="122",
                    subject="성과급 안내",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="keyword password=secret-value",
                    body_text_type="plain",
                    truncated=False,
                )
            ]

            result = search_messages_by_body(
                folder="INBOX",
                query="keyword",
                limit=3,
                max_scan=20,
                max_body_chars=2000,
                allow_blocked_body=True,
            )

        self.assertEqual(result[0]["body"], "keyword password=[REDACTED:SECRET]")
        search.assert_called_once_with("INBOX", "keyword", 3, 20, None, None)

    def test_rejects_invalid_body_read_parameters(self):
        for invalid_uid in ("", "   "):
            with self.subTest(uid=invalid_uid):
                with self.assertRaises(ValueError):
                    read_message_body(folder="INBOX", uid=invalid_uid, max_chars=1000)

        for invalid_max_chars in (0, -1, 100001):
            with self.subTest(max_chars=invalid_max_chars):
                with self.assertRaises(ValueError):
                    read_message_body(folder="INBOX", uid="121", max_chars=invalid_max_chars)

        for invalid_limit in (0, -1, 501):
            with self.subTest(limit=invalid_limit):
                with self.assertRaises(ValueError):
                    search_messages_by_body(folder="INBOX", query="x", limit=invalid_limit)

        for invalid_max_scan in (0, -1, 5001):
            with self.subTest(max_scan=invalid_max_scan):
                with self.assertRaises(ValueError):
                    search_messages_by_body(
                        folder="INBOX",
                        query="x",
                        max_scan=invalid_max_scan,
                    )

        for invalid_max_body_chars in (0, -1, 100001):
            with self.subTest(max_body_chars=invalid_max_body_chars):
                with self.assertRaises(ValueError):
                    search_messages_by_body(
                        folder="INBOX",
                        query="x",
                        max_body_chars=invalid_max_body_chars,
                    )

        with self.assertRaises(ValueError):
            search_messages_by_body(folder="INBOX", query="   ")


if __name__ == "__main__":
    unittest.main()
