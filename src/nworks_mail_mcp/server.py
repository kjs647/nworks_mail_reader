from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from .config import load_state_path
from .imap_client import (
    list_folders as imap_list_folders,
    list_messages as imap_list_messages,
    list_messages_since_uid as imap_list_messages_since_uid,
)
from .state import MailStateStore


mcp = FastMCP("nmail-reader")
MAX_LIMIT = 500


@mcp.tool()
def list_folders() -> list[dict[str, str]]:
    return [asdict(folder) for folder in imap_list_folders()]


@mcp.tool()
def read_messages(folder: str = "INBOX", limit: int = 10) -> list[dict[str, str]]:
    _validate_limit(limit)
    return [asdict(message) for message in imap_list_messages(folder, limit)]


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
        "messages": [asdict(message) for message in result.messages],
    }


def main() -> None:
    mcp.run(transport="stdio")


def _validate_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be greater than 0")
    if limit > MAX_LIMIT:
        raise ValueError(f"limit must be less than or equal to {MAX_LIMIT}")
