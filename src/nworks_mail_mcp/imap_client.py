import email
import imaplib
import base64
import re
from collections.abc import Sequence
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import Message

from .config import ImapConfig, load_imap_config


@dataclass(frozen=True)
class MailFolder:
    name: str


@dataclass(frozen=True)
class MailSummary:
    uid: str
    subject: str
    sender: str
    date: str


@dataclass(frozen=True)
class MailReadResult:
    messages: list[MailSummary]
    uidvalidity: int | None


class NworksImapClient:
    def __init__(self, config: ImapConfig | None = None):
        self.config = config or load_imap_config()
        self.conn: imaplib.IMAP4_SSL | None = None

    def __enter__(self):
        self.conn = imaplib.IMAP4_SSL(self.config.host, self.config.port)
        self.conn.login(self.config.username, self.config.password)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.conn is not None:
            try:
                self.conn.logout()
            finally:
                self.conn = None

    def _require_conn(self) -> imaplib.IMAP4_SSL:
        if self.conn is None:
            raise RuntimeError("IMAP client is not connected")
        return self.conn

    def list_folders(self) -> list[MailFolder]:
        conn = self._require_conn()
        status, rows = conn.list()

        if status != "OK":
            raise RuntimeError("Failed to list IMAP folders")

        folders: list[MailFolder] = []

        for row in rows:
            if not row:
                continue

            text = row.decode("ascii", errors="replace")
            name = _decode_modified_utf7(_extract_mailbox_name(text))
            folders.append(MailFolder(name=name))

        return folders

    def list_messages(self, folder: str = "INBOX", limit: int = 10) -> list[MailSummary]:
        conn = self._require_conn()

        status, _ = conn.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Failed to select folder: {folder}")

        status, data = conn.uid("search", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []

        uids = data[0].decode().split()
        recent_uids = list(reversed(uids))[:limit]

        return self._fetch_message_summaries(recent_uids)

    def list_messages_since_uid(
        self,
        folder: str = "INBOX",
        last_uid: int | None = None,
        limit: int = 50,
        expected_uidvalidity: int | None = None,
    ) -> MailReadResult:
        conn = self._require_conn()

        status, _ = conn.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Failed to select folder: {folder}")

        uidvalidity = _read_uidvalidity(conn)
        can_resume = (
            last_uid is not None
            and uidvalidity is not None
            and expected_uidvalidity is not None
            and uidvalidity == expected_uidvalidity
        )
        start_uid = int(last_uid) + 1 if can_resume else 1
        status, data = conn.uid("search", None, "UID", f"{start_uid}:*")
        if status != "OK" or not data or not data[0]:
            return MailReadResult(messages=[], uidvalidity=uidvalidity)

        uids = data[0].decode().split()
        messages = self._fetch_message_summaries(uids[:limit], stop_on_failure=True)
        return MailReadResult(messages=messages, uidvalidity=uidvalidity)

    def _fetch_message_summaries(
        self,
        uids: Sequence[str],
        stop_on_failure: bool = False,
    ) -> list[MailSummary]:
        conn = self._require_conn()
        messages: list[MailSummary] = []

        for uid in uids:
            status, msg_data = conn.uid(
                "fetch",
                uid,
                "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])",
            )

            if status != "OK" or not msg_data:
                if stop_on_failure:
                    break
                continue

            msg = self._parse_header(msg_data)
            if msg is None:
                if stop_on_failure:
                    break
                continue

            messages.append(
                MailSummary(
                    uid=uid,
                    subject=str(make_header(decode_header(msg.get("Subject", "")))),
                    sender=str(make_header(decode_header(msg.get("From", "")))),
                    date=msg.get("Date", ""),
                )
            )

        return messages

    def _parse_header(self, msg_data) -> Message | None:
        raw_header = None
        for item in msg_data:
            if isinstance(item, tuple):
                raw_header = item[1]
                break

        if raw_header is None:
            return None

        return email.message_from_bytes(raw_header)


def list_folders() -> list[MailFolder]:
    with NworksImapClient() as client:
        return client.list_folders()


def list_messages(folder: str = "INBOX", limit: int = 10) -> list[MailSummary]:
    with NworksImapClient() as client:
        return client.list_messages(folder=folder, limit=limit)


def list_messages_since_uid(
    folder: str = "INBOX",
    last_uid: int | None = None,
    limit: int = 50,
    expected_uidvalidity: int | None = None,
) -> MailReadResult:
    with NworksImapClient() as client:
        return client.list_messages_since_uid(
            folder=folder,
            last_uid=last_uid,
            limit=limit,
            expected_uidvalidity=expected_uidvalidity,
        )


def _extract_mailbox_name(list_response: str) -> str:
    text = list_response.rstrip()
    if text.endswith('"'):
        start = text.rfind('"', 0, len(text) - 1)
        if start != -1:
            return text[start + 1 : -1].replace(r"\"", '"').replace(r"\\", "\\")

    return text.split()[-1].strip('"')


def _decode_modified_utf7(value: str) -> str:
    parts: list[str] = []
    index = 0

    for match in re.finditer(r"&([^-]*)-", value):
        parts.append(value[index : match.start()])
        encoded = match.group(1)
        if encoded == "":
            parts.append("&")
        else:
            padded = encoded.replace(",", "/")
            padded += "=" * (-len(padded) % 4)
            parts.append(base64.b64decode(padded).decode("utf-16-be"))
        index = match.end()

    parts.append(value[index:])
    return "".join(parts)


def _read_uidvalidity(conn: imaplib.IMAP4_SSL) -> int | None:
    response = getattr(conn, "response", None)
    if response is None:
        return None

    status, data = response("UIDVALIDITY")
    if status != "OK" or not data:
        return None

    for item in data:
        if item is None:
            continue
        text = (
            item.decode("ascii", errors="ignore")
            if isinstance(item, bytes)
            else str(item)
        )
        match = re.search(r"\d+", text)
        if match:
            return int(match.group(0))

    return None
