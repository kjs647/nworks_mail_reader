import unittest

from nworks_mail_mcp.config import ImapConfig
from nworks_mail_mcp.imap_client import NworksImapClient


class FakeImapConnection:
    def __init__(
        self,
        search_result: bytes = b"",
        failed_fetch_uids=None,
        list_rows=None,
        uidvalidity: bytes | None = b"777",
        messages=None,
        headers=None,
    ):
        self.search_result = search_result
        self.failed_fetch_uids = set(failed_fetch_uids or [])
        self.list_rows = list_rows or []
        self.uidvalidity = uidvalidity
        self.messages = messages or {}
        self.headers = headers or {}
        self.uid_calls = []
        self.selected = []

    def list(self):
        return "OK", self.list_rows

    def select(self, folder, readonly=True):
        self.selected.append((folder, readonly))
        return "OK", [b"3"]

    def response(self, code):
        if code == "UIDVALIDITY" and self.uidvalidity is not None:
            return "OK", [self.uidvalidity]
        return "OK", [None]

    def uid(self, command, *args):
        self.uid_calls.append((command, args))
        if command == "search":
            return "OK", [self.search_result]
        if command == "fetch":
            uid = args[0]
            fetch_spec = args[1]
            if uid in self.failed_fetch_uids:
                return "NO", []
            if fetch_spec == "(BODY.PEEK[])":
                return "OK", [(b"RFC822", self.messages[uid])]
            if uid in self.headers:
                return "OK", [(b"HEADER", self.headers[uid])]
            raw = (
                b"Subject: Test " + uid.encode("ascii") + b"\r\n"
                b"From: sender@example.com\r\n"
                b"Date: Thu, 28 May 2026 10:00:00 +0900\r\n"
                b"\r\n"
            )
            return "OK", [(b"HEADER", raw)]
        raise AssertionError(f"unexpected uid command: {command}")


class NworksImapClientTest(unittest.TestCase):
    def make_client(self, conn):
        config = ImapConfig(
            host="imap.example.com",
            port=993,
            username="user@example.com",
            password="secret",
        )
        client = NworksImapClient(config)
        client.conn = conn
        return client

    def test_list_messages_since_uid_searches_newer_uid_range(self):
        conn = FakeImapConnection(b"121 122 123")
        client = self.make_client(conn)

        result = client.list_messages_since_uid(
            "INBOX",
            last_uid=120,
            limit=10,
            expected_uidvalidity=777,
        )

        self.assertEqual([message.uid for message in result.messages], ["121", "122", "123"])
        self.assertEqual(result.uidvalidity, 777)
        self.assertEqual(conn.selected, [("INBOX", True)])
        self.assertEqual(conn.uid_calls[0], ("search", (None, "UID", "121:*")))

    def test_list_messages_since_uid_restarts_when_uidvalidity_is_unknown(self):
        conn = FakeImapConnection(b"1 2 3")
        client = self.make_client(conn)

        result = client.list_messages_since_uid("INBOX", last_uid=120, limit=10)

        self.assertEqual([message.uid for message in result.messages], ["1", "2", "3"])
        self.assertEqual(conn.uid_calls[0], ("search", (None, "UID", "1:*")))

    def test_list_messages_since_uid_restarts_when_uidvalidity_changes(self):
        conn = FakeImapConnection(b"1 2 3", uidvalidity=b"888")
        client = self.make_client(conn)

        result = client.list_messages_since_uid(
            "INBOX",
            last_uid=120,
            limit=10,
            expected_uidvalidity=777,
        )

        self.assertEqual([message.uid for message in result.messages], ["1", "2", "3"])
        self.assertEqual(result.uidvalidity, 888)
        self.assertEqual(conn.uid_calls[0], ("search", (None, "UID", "1:*")))

    def test_list_messages_since_uid_limits_oldest_first_to_avoid_skipping(self):
        conn = FakeImapConnection(b"121 122 123 124")
        client = self.make_client(conn)

        result = client.list_messages_since_uid("INBOX", last_uid=120, limit=2)

        self.assertEqual([message.uid for message in result.messages], ["121", "122"])

    def test_list_messages_since_uid_stops_at_first_failed_fetch(self):
        conn = FakeImapConnection(b"121 122 123", failed_fetch_uids={"122"})
        client = self.make_client(conn)

        result = client.list_messages_since_uid("INBOX", last_uid=120, limit=10)

        self.assertEqual([message.uid for message in result.messages], ["121"])
        self.assertNotIn(("fetch", ("123", "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")), conn.uid_calls)

    def test_list_folders_preserves_quoted_names_with_spaces(self):
        conn = FakeImapConnection(
            list_rows=[b'(\\HasNoChildren) "/" "Project A"']
        )
        client = self.make_client(conn)

        folders = client.list_folders()

        self.assertEqual([folder.name for folder in folders], ["Project A"])

    def test_list_folders_decodes_modified_utf7_names(self):
        conn = FakeImapConnection(
            list_rows=[b'(\\HasNoChildren) "/" "&0UzCpNK4-"']
        )
        client = self.make_client(conn)

        folders = client.list_folders()

        self.assertEqual([folder.name for folder in folders], ["테스트"])

    def test_list_messages_since_uid_allows_missing_uidvalidity(self):
        conn = FakeImapConnection(b"121", uidvalidity=None)
        client = self.make_client(conn)

        result = client.list_messages_since_uid("INBOX", last_uid=120, limit=10)

        self.assertIsNone(result.uidvalidity)
        self.assertEqual([message.uid for message in result.messages], ["121"])

    def test_list_message_uids_returns_uidvalidity(self):
        conn = FakeImapConnection(b"121 122", uidvalidity=b"777")
        client = self.make_client(conn)

        result = client.list_message_uids("INBOX")

        self.assertEqual(result.uids, ["121", "122"])
        self.assertEqual(result.uidvalidity, 777)
        self.assertEqual(conn.uid_calls[0], ("search", (None, "ALL")))

    def test_get_messages_for_index_skips_blocked_body_fetch(self):
        headers = {
            "121": (
                b"Subject: 2026 salary\r\nFrom: sender@example.com\r\n"
                b"Date: Thu, 28 May 2026 09:00:00 +0900\r\n\r\n"
            ),
            "122": (
                b"Subject: General\r\nFrom: sender@example.com\r\n"
                b"Date: Thu, 28 May 2026 10:00:00 +0900\r\n\r\n"
            ),
        }
        messages = {
            "122": (
                b"Subject: General\r\nFrom: sender@example.com\r\n"
                b"Date: Thu, 28 May 2026 10:00:00 +0900\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n\r\nbody"
            ),
        }
        conn = FakeImapConnection(headers=headers, messages=messages)
        client = self.make_client(conn)

        results = client.get_messages_for_index(
            "INBOX",
            ["121", "122"],
            skip_subject_keywords=("salary",),
            block_reason="COMPENSATION_SUBJECT",
        )

        self.assertTrue(results[0].body_index_blocked)
        self.assertEqual(results[0].block_reason, "COMPENSATION_SUBJECT")
        self.assertEqual(results[1].body, "body")
        self.assertNotIn(("fetch", ("121", "(BODY.PEEK[])")), conn.uid_calls)

    def test_get_message_body_reads_plain_text_without_marking_seen(self):
        raw_message = (
            b"Subject: Body mail\r\n"
            b"From: sender@example.com\r\n"
            b"Date: Thu, 28 May 2026 10:00:00 +0900\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"\r\n" +
            "본문 내용입니다.".encode("utf-8")
        )
        conn = FakeImapConnection(messages={"121": raw_message})
        client = self.make_client(conn)

        message = client.get_message_body("INBOX", "121", max_chars=100)

        self.assertEqual(message.uid, "121")
        self.assertEqual(message.subject, "Body mail")
        self.assertEqual(message.sender, "sender@example.com")
        self.assertEqual(message.body, "본문 내용입니다.")
        self.assertEqual(message.body_text_type, "plain")
        self.assertFalse(message.truncated)
        self.assertEqual(conn.selected, [("INBOX", True)])
        self.assertIn(("fetch", ("121", "(BODY.PEEK[])")), conn.uid_calls)

    def test_get_message_summary_fetches_header_without_body(self):
        raw_header = (
            b"Subject: Header only\r\n"
            b"From: sender@example.com\r\n"
            b"Date: Thu, 28 May 2026 10:00:00 +0900\r\n"
            b"\r\n"
        )
        conn = FakeImapConnection(headers={"121": raw_header})
        client = self.make_client(conn)

        message = client.get_message_summary("INBOX", "121")

        self.assertEqual(message.uid, "121")
        self.assertEqual(message.subject, "Header only")
        self.assertEqual(conn.selected, [("INBOX", True)])
        self.assertNotIn(("fetch", ("121", "(BODY.PEEK[])")), conn.uid_calls)

    def test_get_message_body_prefers_plain_text_and_skips_attachments(self):
        raw_message = (
            b"Subject: Multipart\r\n"
            b"From: sender@example.com\r\n"
            b"Date: Thu, 28 May 2026 10:00:00 +0900\r\n"
            b"Content-Type: multipart/mixed; boundary=abc\r\n"
            b"\r\n"
            b"--abc\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"\r\n"
            b"<p>HTML body</p>\r\n"
            b"--abc\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"\r\n"
            b"Plain body\r\n"
            b"--abc\r\n"
            b"Content-Type: text/plain; name=notes.txt\r\n"
            b"Content-Disposition: attachment; filename=notes.txt\r\n"
            b"\r\n"
            b"Attachment text\r\n"
            b"--abc--\r\n"
        )
        conn = FakeImapConnection(messages={"122": raw_message})
        client = self.make_client(conn)

        message = client.get_message_body("INBOX", "122", max_chars=100)

        self.assertEqual(message.body, "Plain body")
        self.assertEqual(message.body_text_type, "plain")

    def test_get_message_body_falls_back_to_html_text_and_truncates(self):
        raw_message = (
            b"Subject: Html only\r\n"
            b"From: sender@example.com\r\n"
            b"Date: Thu, 28 May 2026 10:00:00 +0900\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"\r\n"
            b"<html><body><h1>Hello</h1><p>World &amp; Team</p></body></html>"
        )
        conn = FakeImapConnection(messages={"123": raw_message})
        client = self.make_client(conn)

        message = client.get_message_body("INBOX", "123", max_chars=12)

        self.assertEqual(message.body, "Hello World ")
        self.assertEqual(message.body_text_type, "html")
        self.assertTrue(message.truncated)

    def test_search_messages_by_body_scans_recent_messages_and_returns_matches(self):
        messages = {
            "121": (
                b"Subject: Old\r\nFrom: sender@example.com\r\nDate: Thu, 28 May 2026 09:00:00 +0900\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n\r\nalpha"
            ),
            "122": (
                b"Subject: Match\r\nFrom: sender@example.com\r\nDate: Thu, 28 May 2026 10:00:00 +0900\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n\r\nProject KEYWORD update"
            ),
            "123": (
                b"Subject: Recent\r\nFrom: sender@example.com\r\nDate: Thu, 28 May 2026 11:00:00 +0900\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n\r\nnothing here"
            ),
        }
        conn = FakeImapConnection(search_result=b"121 122 123", messages=messages)
        client = self.make_client(conn)

        results = client.search_messages_by_body(
            "INBOX",
            query="keyword",
            limit=5,
            max_scan=2,
            max_body_chars=10,
        )

        self.assertEqual([message.uid for message in results], ["122"])
        self.assertEqual(results[0].subject, "Match")
        self.assertEqual(results[0].body, "Project KE")
        self.assertTrue(results[0].truncated)
        self.assertNotIn(("fetch", ("121", "(BODY.PEEK[])")), conn.uid_calls)

    def test_search_messages_by_body_skips_blocked_subjects_before_body_fetch(self):
        headers = {
            "121": (
                b"Subject: 2026 salary\r\nFrom: sender@example.com\r\n"
                b"Date: Thu, 28 May 2026 09:00:00 +0900\r\n\r\n"
            ),
            "122": (
                b"Subject: General\r\nFrom: sender@example.com\r\n"
                b"Date: Thu, 28 May 2026 10:00:00 +0900\r\n\r\n"
            ),
        }
        messages = {
            "121": (
                b"Subject: 2026 salary\r\nFrom: sender@example.com\r\n"
                b"Date: Thu, 28 May 2026 09:00:00 +0900\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n\r\nkeyword"
            ),
            "122": (
                b"Subject: General\r\nFrom: sender@example.com\r\n"
                b"Date: Thu, 28 May 2026 10:00:00 +0900\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n\r\nkeyword"
            ),
        }
        conn = FakeImapConnection(
            search_result=b"121 122",
            messages=messages,
            headers=headers,
        )
        client = self.make_client(conn)

        results = client.search_messages_by_body(
            "INBOX",
            query="keyword",
            limit=5,
            max_scan=2,
            max_body_chars=100,
            skip_subject_keywords=("salary",),
        )

        self.assertEqual([message.uid for message in results], ["122"])
        self.assertNotIn(("fetch", ("121", "(BODY.PEEK[])")), conn.uid_calls)


if __name__ == "__main__":
    unittest.main()
