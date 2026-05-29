import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nworks_mail_mcp.imap_client import MailIndexMessage
from nworks_mail_mcp.mail_index import MailIndexStore


class MailIndexStoreTest(unittest.TestCase):
    def test_uses_index_path_env_and_initializes_idempotently(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "mail.sqlite"
            with patch.dict(os.environ, {"NWORKS_INDEX_PATH": str(index_path)}):
                store = MailIndexStore()
                store.initialize()
                store.initialize()

            self.assertTrue(index_path.exists())

    def test_search_matches_korean_body_and_excludes_deleted_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MailIndexStore(Path(tmpdir) / "mail.sqlite")
            store.initialize()
            store.upsert_message(
                "INBOX",
                777,
                MailIndexMessage(
                    uid="121",
                    subject="프로젝트 회의",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="다음 주 일정과 예산을 논의합니다.",
                    body_text_type="plain",
                    truncated=False,
                    body_index_blocked=False,
                    block_reason=None,
                ),
            )
            store.upsert_message(
                "INBOX",
                777,
                MailIndexMessage(
                    uid="122",
                    subject="삭제된 일정",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 11:00:00 +0900",
                    body="다음 주 일정입니다.",
                    body_text_type="plain",
                    truncated=False,
                    body_index_blocked=False,
                    block_reason=None,
                ),
            )

            deleted_count = store.mark_missing_deleted("INBOX", {"121"})
            results = store.search("INBOX", "다음 주 일정", limit=20)

        self.assertEqual(deleted_count, 1)
        self.assertEqual([result.uid for result in results], ["121"])

    def test_search_fallback_matches_korean_terms_across_particles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MailIndexStore(Path(tmpdir) / "mail.sqlite")
            store.initialize()
            store.upsert_message(
                "INBOX",
                777,
                MailIndexMessage(
                    uid="121",
                    subject="프로젝트 회의",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="다음 주 일정과 예산을 논의합니다.",
                    body_text_type="plain",
                    truncated=False,
                    body_index_blocked=False,
                    block_reason=None,
                ),
            )

            results = store.search("INBOX", "일정 예산", limit=20)

        self.assertEqual([result.uid for result in results], ["121"])


if __name__ == "__main__":
    unittest.main()
