import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from nworks_mail_mcp.imap_client import MailIndexMessage, MailUidList
from nworks_mail_mcp.index_sync import sync_mail_index
from nworks_mail_mcp.mail_index import MailIndexStore


class FakeIndexClient:
    def __init__(self, uids, uidvalidity=777):
        self.uids = uids
        self.uidvalidity = uidvalidity
        self.requested_uids = []
        self.uid_ranges = []
        self.skip_subject_keywords = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def list_message_uids(self, folder="INBOX", uid_range="ALL"):
        self.uid_ranges.append(uid_range)
        return MailUidList(uids=self.uids, uidvalidity=self.uidvalidity)

    def get_messages_for_index(
        self,
        folder,
        uids,
        skip_subject_keywords=None,
        block_reason=None,
    ):
        self.requested_uids.extend(uids)
        self.skip_subject_keywords = skip_subject_keywords
        messages = []
        for uid in uids:
            blocked = skip_subject_keywords is not None and uid == "3"
            messages.append(
                MailIndexMessage(
                    uid=uid,
                    subject="성과급 안내" if blocked else f"Mail {uid}",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="" if blocked else f"body {uid}",
                    body_text_type="blocked" if blocked else "plain",
                    truncated=False,
                    body_index_blocked=blocked,
                    block_reason=block_reason if blocked else None,
                )
            )
        return messages


class GapIndexClient(FakeIndexClient):
    def get_messages_for_index(
        self,
        folder,
        uids,
        skip_subject_keywords=None,
        block_reason=None,
    ):
        self.requested_uids.extend(uids)
        messages = []
        for uid in uids:
            if uid == "11":
                continue
            messages.append(
                MailIndexMessage(
                    uid=uid,
                    subject=f"Mail {uid}",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body=f"body {uid}",
                    body_text_type="plain",
                    truncated=False,
                    body_index_blocked=False,
                    block_reason=None,
                )
            )
        return messages


class MailIndexSyncTest(unittest.TestCase):
    def test_initial_sync_indexes_recent_limit_and_blocks_sensitive_body(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client = FakeIndexClient(["1", "2", "3"])
            index_path = Path(tmpdir) / "mail.sqlite"

            with patch("nworks_mail_mcp.index_sync.NworksImapClient", return_value=client):
                result = sync_mail_index(
                    folder="INBOX",
                    initial_limit=2,
                    incremental_limit=100,
                    skip_subject_keywords=("성과급",),
                    block_reason="COMPENSATION_SUBJECT",
                    index_path=index_path,
                )

            store = MailIndexStore(index_path)
            blocked = store.search("INBOX", "성과급", limit=20)

        self.assertEqual(client.requested_uids, ["2", "3"])
        self.assertEqual(result.indexed_count, 2)
        self.assertEqual(result.last_uid, 3)
        self.assertEqual(blocked[0].uid, "3")
        self.assertTrue(blocked[0].body_index_blocked)
        self.assertEqual(blocked[0].block_reason, "COMPENSATION_SUBJECT")

    def test_incremental_sync_limits_new_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "mail.sqlite"
            store = MailIndexStore(index_path)
            store.initialize()
            store.upsert_message(
                "INBOX",
                777,
                MailIndexMessage(
                    uid="10",
                    subject="Existing",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="existing body",
                    body_text_type="plain",
                    truncated=False,
                    body_index_blocked=False,
                    block_reason=None,
                ),
            )
            store.update_folder_checkpoint("INBOX", 777, 10)
            store.update_full_check_time("INBOX")
            client = FakeIndexClient(["9", "10", "11", "12", "13"])

            with patch("nworks_mail_mcp.index_sync.NworksImapClient", return_value=client):
                result = sync_mail_index(
                    folder="INBOX",
                    initial_limit=1,
                    incremental_limit=2,
                    index_path=index_path,
                )

        self.assertEqual(client.requested_uids, ["11", "12"])
        self.assertEqual(client.uid_ranges, ["11:*"])
        self.assertEqual(result.indexed_count, 2)
        self.assertEqual(result.last_uid, 12)

    def test_incremental_sync_does_not_advance_past_failed_uid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "mail.sqlite"
            store = MailIndexStore(index_path)
            store.initialize()
            store.upsert_message(
                "INBOX",
                777,
                MailIndexMessage(
                    uid="10",
                    subject="Existing",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="existing body",
                    body_text_type="plain",
                    truncated=False,
                    body_index_blocked=False,
                    block_reason=None,
                ),
            )
            store.update_folder_checkpoint("INBOX", 777, 10)
            store.update_full_check_time("INBOX")
            client = GapIndexClient(["10", "11", "12"])

            with patch("nworks_mail_mcp.index_sync.NworksImapClient", return_value=client):
                result = sync_mail_index(
                    folder="INBOX",
                    initial_limit=1,
                    incremental_limit=10,
                    index_path=index_path,
                )

        self.assertEqual(client.requested_uids, ["11", "12"])
        self.assertEqual(result.indexed_count, 1)
        self.assertEqual(result.last_uid, 10)

    def test_manual_initial_sync_backfills_after_small_context_sync(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "mail.sqlite"
            store = MailIndexStore(index_path)
            store.initialize()
            for uid in ("8", "9", "10"):
                store.upsert_message(
                    "INBOX",
                    777,
                    MailIndexMessage(
                        uid=uid,
                        subject=f"Mail {uid}",
                        sender="sender@example.com",
                        date="Thu, 28 May 2026 10:00:00 +0900",
                        body=f"body {uid}",
                        body_text_type="plain",
                        truncated=False,
                        body_index_blocked=False,
                        block_reason=None,
                    ),
                )
            store.update_folder_checkpoint("INBOX", 777, 10)
            store.update_full_check_time("INBOX")
            client = FakeIndexClient([str(uid) for uid in range(1, 11)])

            with patch("nworks_mail_mcp.index_sync.NworksImapClient", return_value=client):
                result = sync_mail_index(
                    folder="INBOX",
                    initial_limit=5,
                    incremental_limit=100,
                    index_path=index_path,
                )

        self.assertEqual(client.uid_ranges, ["11:*", "ALL"])
        self.assertEqual(client.requested_uids, ["6", "7"])
        self.assertEqual(result.indexed_count, 2)
        self.assertEqual(result.last_uid, 10)

    def test_uidvalidity_change_resets_folder_and_removes_stale_fts_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "mail.sqlite"
            store = MailIndexStore(index_path)
            store.initialize()
            store.upsert_message(
                "INBOX",
                777,
                MailIndexMessage(
                    uid="1",
                    subject="Old stale",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="stale body",
                    body_text_type="plain",
                    truncated=False,
                    body_index_blocked=False,
                    block_reason=None,
                ),
            )
            store.update_folder_checkpoint("INBOX", 777, 1)
            client = FakeIndexClient(["1", "2"], uidvalidity=888)

            with patch("nworks_mail_mcp.index_sync.NworksImapClient", return_value=client):
                result = sync_mail_index(
                    folder="INBOX",
                    initial_limit=10,
                    index_path=index_path,
                )
            stale_results = store.search("INBOX", "stale", limit=20)
            body_results = store.search("INBOX", "body 2", limit=20)

        self.assertTrue(result.reset)
        self.assertEqual(client.uid_ranges, ["2:*", "ALL"])
        self.assertEqual(stale_results, [])
        self.assertEqual([item.uid for item in body_results], ["2"])

    def test_full_check_true_runs_immediately(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "mail.sqlite"
            store = MailIndexStore(index_path)
            store.initialize()
            store.update_folder_checkpoint("INBOX", 777, 10)
            client = FakeIndexClient(["10", "11"])

            with patch("nworks_mail_mcp.index_sync.NworksImapClient", return_value=client):
                result = sync_mail_index(
                    folder="INBOX",
                    full_check=True,
                    index_path=index_path,
                )

        self.assertTrue(result.full_check)
        self.assertEqual(client.uid_ranges, ["11:*", "ALL"])

    def test_full_check_is_skipped_before_daily_interval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "mail.sqlite"
            store = MailIndexStore(index_path)
            store.initialize()
            store.upsert_message(
                "INBOX",
                777,
                MailIndexMessage(
                    uid="10",
                    subject="Existing",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="existing body",
                    body_text_type="plain",
                    truncated=False,
                    body_index_blocked=False,
                    block_reason=None,
                ),
            )
            store.update_folder_checkpoint("INBOX", 777, 10)
            store.update_full_check_time("INBOX")
            client = FakeIndexClient(["10", "11"])

            with patch("nworks_mail_mcp.index_sync.NworksImapClient", return_value=client):
                result = sync_mail_index(
                    folder="INBOX",
                    initial_limit=1,
                    index_path=index_path,
                )

        self.assertFalse(result.full_check)
        self.assertEqual(client.uid_ranges, ["11:*"])

    def test_allow_blocked_body_indexes_sensitive_body(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client = FakeIndexClient(["3"])
            index_path = Path(tmpdir) / "mail.sqlite"

            with patch("nworks_mail_mcp.index_sync.NworksImapClient", return_value=client):
                sync_mail_index(
                    folder="INBOX",
                    allow_blocked_body=True,
                    skip_subject_keywords=("성과급",),
                    block_reason="COMPENSATION_SUBJECT",
                    index_path=index_path,
                )

            store = MailIndexStore(index_path)
            results = store.search("INBOX", "body 3", limit=20)

        self.assertIsNone(client.skip_subject_keywords)
        self.assertEqual([item.uid for item in results], ["3"])
        self.assertFalse(results[0].body_index_blocked)

    def test_allow_blocked_body_reindexes_existing_blocked_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client = FakeIndexClient(["3"])
            index_path = Path(tmpdir) / "mail.sqlite"

            with patch("nworks_mail_mcp.index_sync.NworksImapClient", return_value=client):
                sync_mail_index(
                    folder="INBOX",
                    initial_limit=1,
                    skip_subject_keywords=("성과급",),
                    block_reason="COMPENSATION_SUBJECT",
                    index_path=index_path,
                )
                sync_mail_index(
                    folder="INBOX",
                    initial_limit=1,
                    allow_blocked_body=True,
                    skip_subject_keywords=("성과급",),
                    block_reason="COMPENSATION_SUBJECT",
                    index_path=index_path,
                )

            store = MailIndexStore(index_path)
            results = store.search("INBOX", "body 3", limit=20)

        self.assertEqual(client.requested_uids, ["3", "3"])
        self.assertEqual([item.uid for item in results], ["3"])
        self.assertFalse(results[0].body_index_blocked)

    def test_full_check_runs_after_daily_interval_and_marks_deleted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "mail.sqlite"
            store = MailIndexStore(index_path)
            store.initialize()
            store.upsert_message(
                "INBOX",
                777,
                MailIndexMessage(
                    uid="1",
                    subject="Old",
                    sender="sender@example.com",
                    date="Thu, 28 May 2026 10:00:00 +0900",
                    body="old body",
                    body_text_type="plain",
                    truncated=False,
                    body_index_blocked=False,
                    block_reason=None,
                ),
            )
            store.update_folder_checkpoint("INBOX", 777, 1)
            with store._connect() as conn:
                conn.execute(
                    "UPDATE folders SET last_full_check_at = ? WHERE folder = ?",
                    (
                        (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                        "INBOX",
                    ),
                )

            client = FakeIndexClient([])
            with patch("nworks_mail_mcp.index_sync.NworksImapClient", return_value=client):
                result = sync_mail_index(folder="INBOX", index_path=index_path)
            remaining = store.search("INBOX", "old", limit=20)

        self.assertTrue(result.full_check)
        self.assertEqual(result.deleted_count, 1)
        self.assertEqual(remaining, [])


if __name__ == "__main__":
    unittest.main()
