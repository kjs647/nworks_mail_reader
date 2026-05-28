import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nworks_mail_mcp.imap_client import MailBody, MailReadResult, MailSummary
from nworks_mail_mcp.server import (
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

    def test_rejects_invalid_limits(self):
        for invalid_limit in (0, -1, 501):
            with self.subTest(limit=invalid_limit):
                with self.assertRaises(ValueError):
                    read_messages(folder="INBOX", limit=invalid_limit)
                with self.assertRaises(ValueError):
                    read_new_messages(folder="INBOX", limit=invalid_limit)

    def test_read_message_body_returns_mail_body_dict(self):
        with patch("nworks_mail_mcp.server.imap_get_message_body") as get_body:
            get_body.return_value = MailBody(
                uid="121",
                subject="Body mail",
                sender="sender@example.com",
                date="Thu, 28 May 2026 10:00:00 +0900",
                body="본문 내용입니다.",
                body_text_type="plain",
                truncated=False,
            )

            result = read_message_body(folder="INBOX", uid="121", max_chars=1000)

        self.assertEqual(result["uid"], "121")
        self.assertEqual(result["body"], "본문 내용입니다.")
        self.assertEqual(result["body_text_type"], "plain")
        self.assertFalse(result["truncated"])
        get_body.assert_called_once_with("INBOX", "121", 1000)

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
        search.assert_called_once_with("INBOX", "keyword", 3, 20, 2000)

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
