import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nworks_mail_mcp.imap_client import MailReadResult, MailSummary
from nworks_mail_mcp.server import read_messages, read_new_messages


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


if __name__ == "__main__":
    unittest.main()
