from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from .config import load_state_path
from .imap_client import (
    get_message_body as imap_get_message_body,
    get_message_summary as imap_get_message_summary,
    list_folders as imap_list_folders,
    list_messages as imap_list_messages,
    list_messages_since_uid as imap_list_messages_since_uid,
    search_messages_by_body as imap_search_messages_by_body,
)
from .redaction import (
    redact_mail_body_dict,
    redact_mail_summary_dict,
    validate_redaction_config,
)
from .state import MailStateStore


mcp = FastMCP("nmail-reader")
MAX_LIMIT = 500
MAX_BODY_CHARS = 100000
MAX_SCAN = 5000
COMPENSATION_SUBJECT_KEYWORDS = (
    "연봉",
    "성과급",
    "보너스",
    "인센티브",
    "보상",
    "급여",
    "임금",
)
COMPENSATION_BLOCK_REASON = "COMPENSATION_SUBJECT"
COMPENSATION_BLOCK_BODY = "[BLOCKED:COMPENSATION_SUBJECT]"
validate_redaction_config()


@mcp.tool()
def list_folders() -> list[dict[str, str]]:
    return [asdict(folder) for folder in imap_list_folders()]


@mcp.tool()
def read_messages(folder: str = "INBOX", limit: int = 10) -> list[dict]:
    _validate_limit(limit)
    return [_message_summary_response(message) for message in imap_list_messages(folder, limit)]


@mcp.tool()
def read_new_messages(folder: str = "INBOX", limit: int = 50) -> dict:
    _validate_limit(limit)
    store = MailStateStore(load_state_path())
    checkpoint = store.get_checkpoint(folder)
    previous_last_uid = checkpoint.last_uid
    result = imap_list_messages_since_uid(
        folder,
        previous_last_uid,
        limit,
        expected_uidvalidity=checkpoint.uidvalidity,
    )

    new_last_uid = previous_last_uid
    if result.messages:
        new_last_uid = max(int(message.uid) for message in result.messages)
        store.update_checkpoint(
            folder=folder,
            last_uid=new_last_uid,
            uidvalidity=result.uidvalidity,
        )

    return {
        "folder": folder,
        "uidvalidity": result.uidvalidity,
        "previous_last_uid": previous_last_uid,
        "new_last_uid": new_last_uid,
        "messages": [_message_summary_response(message) for message in result.messages],
    }


@mcp.tool()
def read_message_body(
    folder: str = "INBOX",
    uid: str = "",
    max_chars: int = 20000,
    allow_blocked_body: bool = False,
) -> dict[str, str | bool | None]:
    _validate_text(uid, "uid")
    _validate_max_chars(max_chars)
    summary = imap_get_message_summary(folder, uid)
    if _is_body_read_blocked(summary.subject) and not allow_blocked_body:
        return _blocked_body_response(summary)

    message = imap_get_message_body(folder, uid, None)
    return _message_body_response(message, max_chars)


@mcp.tool()
def search_messages_by_body(
    folder: str = "INBOX",
    query: str = "",
    limit: int = 20,
    max_scan: int = 200,
    max_body_chars: int = 2000,
    allow_blocked_body: bool = False,
) -> list[dict[str, str | bool | None]]:
    _validate_text(query, "query")
    _validate_limit(limit)
    _validate_max_scan(max_scan)
    _validate_max_chars(max_body_chars)
    skip_subject_keywords = None if allow_blocked_body else COMPENSATION_SUBJECT_KEYWORDS
    return [
        _message_body_response(message, max_body_chars)
        for message in imap_search_messages_by_body(
            folder,
            query,
            limit,
            max_scan,
            None,
            skip_subject_keywords,
        )
    ]


def main() -> None:
    mcp.run(transport="stdio")


def _validate_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be greater than 0")
    if limit > MAX_LIMIT:
        raise ValueError(f"limit must be less than or equal to {MAX_LIMIT}")


def _validate_max_chars(max_chars: int) -> None:
    if max_chars < 1:
        raise ValueError("max_chars must be greater than 0")
    if max_chars > MAX_BODY_CHARS:
        raise ValueError(f"max_chars must be less than or equal to {MAX_BODY_CHARS}")


def _validate_max_scan(max_scan: int) -> None:
    if max_scan < 1:
        raise ValueError("max_scan must be greater than 0")
    if max_scan > MAX_SCAN:
        raise ValueError(f"max_scan must be less than or equal to {MAX_SCAN}")


def _validate_text(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be empty")


def _message_summary_response(message) -> dict:
    response = asdict(message)
    blocked = _is_body_read_blocked(message.subject)
    response["body_read_blocked"] = blocked
    response["block_reason"] = COMPENSATION_BLOCK_REASON if blocked else None
    return redact_mail_summary_dict(response)


def _message_body_response(message, max_chars: int) -> dict:
    response = asdict(message)
    response["blocked"] = False
    response["can_override"] = False
    response["block_reason"] = None
    return redact_mail_body_dict(response, max_chars=max_chars)


def _blocked_body_response(summary) -> dict[str, str | bool | None]:
    response = {
        "uid": summary.uid,
        "subject": summary.subject,
        "sender": summary.sender,
        "date": summary.date,
        "body": COMPENSATION_BLOCK_BODY,
        "body_text_type": "blocked",
        "truncated": False,
        "blocked": True,
        "can_override": True,
        "block_reason": COMPENSATION_BLOCK_REASON,
    }
    return redact_mail_body_dict(response)


def _is_body_read_blocked(subject: str) -> bool:
    folded = subject.casefold()
    return any(keyword.casefold() in folded for keyword in COMPENSATION_SUBJECT_KEYWORDS)
