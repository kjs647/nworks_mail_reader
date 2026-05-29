import email
import imaplib
import base64
import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import Message
from email import policy

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
class MailBody:
    uid: str
    subject: str
    sender: str
    date: str
    body: str
    body_text_type: str
    truncated: bool


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

    def get_message_body(
        self,
        folder: str = "INBOX",
        uid: str = "",
        max_chars: int | None = 20000,
    ) -> MailBody:
        conn = self._require_conn()

        status, _ = conn.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Failed to select folder: {folder}")

        return self._fetch_message_body(uid, max_chars=max_chars)

    def get_message_summary(
        self,
        folder: str = "INBOX",
        uid: str = "",
    ) -> MailSummary:
        conn = self._require_conn()

        status, _ = conn.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Failed to select folder: {folder}")

        message = self._fetch_message_summary(uid)
        if message is None:
            raise RuntimeError(f"Failed to fetch message summary for UID: {uid}")
        return message

    def search_messages_by_body(
        self,
        folder: str = "INBOX",
        query: str = "",
        limit: int = 20,
        max_scan: int = 200,
        max_body_chars: int | None = 2000,
        skip_subject_keywords: Sequence[str] | None = None,
    ) -> list[MailBody]:
        conn = self._require_conn()

        status, _ = conn.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Failed to select folder: {folder}")

        status, data = conn.uid("search", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []

        query_text = query.casefold()
        uids = data[0].decode().split()
        recent_uids = list(reversed(uids))[:max_scan]
        matches: list[MailBody] = []

        for uid in recent_uids:
            if skip_subject_keywords:
                summary = self._fetch_message_summary(uid)
                if summary is None:
                    continue
                if _contains_keyword(summary.subject, skip_subject_keywords):
                    continue
            try:
                message = self._fetch_message_body(uid, max_chars=None)
            except RuntimeError:
                continue
            if query_text in message.body.casefold():
                matches.append(
                    _limit_mail_body(message, max_body_chars)
                    if max_body_chars is not None
                    else message
                )
                if len(matches) >= limit:
                    break

        return matches

    def _fetch_message_summary(self, uid: str) -> MailSummary | None:
        conn = self._require_conn()
        status, msg_data = conn.uid(
            "fetch",
            uid,
            "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])",
        )

        if status != "OK" or not msg_data:
            return None

        msg = self._parse_header(msg_data)
        if msg is None:
            return None

        return MailSummary(
            uid=uid,
            subject=str(make_header(decode_header(msg.get("Subject", "")))),
            sender=str(make_header(decode_header(msg.get("From", "")))),
            date=msg.get("Date", ""),
        )

    def _fetch_message_summaries(
        self,
        uids: Sequence[str],
        stop_on_failure: bool = False,
    ) -> list[MailSummary]:
        messages: list[MailSummary] = []

        for uid in uids:
            message = self._fetch_message_summary(uid)
            if message is None:
                if stop_on_failure:
                    break
                continue

            messages.append(message)

        return messages

    def _fetch_message_body(self, uid: str, max_chars: int | None) -> MailBody:
        conn = self._require_conn()
        status, msg_data = conn.uid("fetch", uid, "(BODY.PEEK[])")
        if status != "OK" or not msg_data:
            raise RuntimeError(f"Failed to fetch message body for UID: {uid}")

        raw_message = _extract_first_tuple_payload(msg_data)
        if raw_message is None:
            raise RuntimeError(f"Failed to parse message body for UID: {uid}")

        msg = email.message_from_bytes(raw_message, policy=policy.default)
        body, body_text_type = _extract_body_text(msg)
        body = _normalize_text(body)
        truncated = max_chars is not None and len(body) > max_chars
        if truncated:
            body = body[:max_chars]

        return MailBody(
            uid=uid,
            subject=_decode_header_value(msg.get("Subject", "")),
            sender=_decode_header_value(msg.get("From", "")),
            date=msg.get("Date", ""),
            body=body,
            body_text_type=body_text_type,
            truncated=truncated,
        )

    def _parse_header(self, msg_data) -> Message | None:
        raw_header = _extract_first_tuple_payload(msg_data)
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


def get_message_body(
    folder: str = "INBOX",
    uid: str = "",
    max_chars: int | None = 20000,
) -> MailBody:
    with NworksImapClient() as client:
        return client.get_message_body(
            folder=folder,
            uid=uid,
            max_chars=max_chars,
        )


def get_message_summary(folder: str = "INBOX", uid: str = "") -> MailSummary:
    with NworksImapClient() as client:
        return client.get_message_summary(folder=folder, uid=uid)


def search_messages_by_body(
    folder: str = "INBOX",
    query: str = "",
    limit: int = 20,
    max_scan: int = 200,
    max_body_chars: int | None = 2000,
    skip_subject_keywords: Sequence[str] | None = None,
) -> list[MailBody]:
    with NworksImapClient() as client:
        return client.search_messages_by_body(
            folder=folder,
            query=query,
            limit=limit,
            max_scan=max_scan,
            max_body_chars=max_body_chars,
            skip_subject_keywords=skip_subject_keywords,
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


def _extract_first_tuple_payload(msg_data) -> bytes | None:
    for item in msg_data:
        if isinstance(item, tuple):
            return item[1]
    return None


def _decode_header_value(value: str | None) -> str:
    return str(make_header(decode_header(value or "")))


def _extract_body_text(msg: Message) -> tuple[str, str]:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.is_multipart():
            continue
        if _is_attachment(part):
            continue

        content_type = part.get_content_type()
        if content_type == "text/plain":
            plain_parts.append(_part_text(part))
        elif content_type == "text/html":
            html_parts.append(_html_to_text(_part_text(part)))

    if plain_parts:
        return "\n".join(plain_parts), "plain"
    if html_parts:
        return "\n".join(html_parts), "html"
    return "", "none"


def _is_attachment(part: Message) -> bool:
    return part.get_content_disposition() == "attachment" or bool(part.get_filename())


def _part_text(part: Message) -> str:
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError):
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")

    return content if isinstance(content, str) else ""


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p\s*>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return html.unescape(text)


def _normalize_text(value: str) -> str:
    lines = [" ".join(line.split()) for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _contains_keyword(value: str, keywords: Sequence[str]) -> bool:
    folded = value.casefold()
    return any(keyword.casefold() in folded for keyword in keywords)


def _limit_mail_body(message: MailBody, max_chars: int) -> MailBody:
    truncated = len(message.body) > max_chars
    return MailBody(
        uid=message.uid,
        subject=message.subject,
        sender=message.sender,
        date=message.date,
        body=message.body[:max_chars] if truncated else message.body,
        body_text_type=message.body_text_type,
        truncated=message.truncated or truncated,
    )
