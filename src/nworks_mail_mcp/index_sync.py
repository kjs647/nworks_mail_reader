from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Sequence

from .imap_client import NworksImapClient
from .mail_index import MailIndexStore, MailSearchResult


@dataclass(frozen=True)
class MailIndexSyncResult:
    folder: str
    uidvalidity: int | None
    indexed_count: int
    deleted_count: int
    last_uid: int | None
    reset: bool
    full_check: bool


def sync_mail_index(
    folder: str = "INBOX",
    initial_limit: int = 2000,
    incremental_limit: int = 100,
    full_check: bool = False,
    allow_blocked_body: bool = False,
    skip_subject_keywords: Sequence[str] | None = None,
    block_reason: str | None = None,
    index_path: Path | str | None = None,
) -> MailIndexSyncResult:
    store = MailIndexStore(index_path)
    store.initialize()

    with NworksImapClient() as client:
        state = store.get_folder_state(folder)
        first_uid_range = (
            f"{int(state.last_uid) + 1}:*"
            if state is not None and state.last_uid is not None
            else "ALL"
        )
        uid_list = client.list_message_uids(folder=folder, uid_range=first_uid_range)
        uidvalidity = uid_list.uidvalidity

        reset = _needs_reset(state, uidvalidity)
        active_uids = set() if reset else store.active_uids(folder)
        needs_backfill = (
            state is not None
            and state.last_uid is not None
            and len(active_uids) < initial_limit
        )
        needs_full_uid_list = (
            first_uid_range == "ALL"
            or reset
            or full_check
            or _full_check_due(state)
            or needs_backfill
        )
        if needs_full_uid_list and first_uid_range != "ALL":
            uid_list = client.list_message_uids(folder=folder, uid_range="ALL")
            uidvalidity = uid_list.uidvalidity
            reset = _needs_reset(state, uidvalidity)
            active_uids = set() if reset else store.active_uids(folder)

        if reset:
            store.reset_folder(folder, uidvalidity)
            state = store.get_folder_state(folder)

        if state is None or state.last_uid is None:
            uids_to_index = uid_list.uids[-initial_limit:]
            checkpoint_uids = uids_to_index
        else:
            new_uids_to_index = [
                uid
                for uid in uid_list.uids
                if int(uid) > int(state.last_uid)
            ][:incremental_limit]
            backfill_uids = []
            if needs_backfill:
                backfill_uids = [
                    uid
                    for uid in uid_list.uids[-initial_limit:]
                    if uid not in active_uids and uid not in new_uids_to_index
                ]
            blocked_reindex_uids = []
            if allow_blocked_body:
                already_queued = set(new_uids_to_index) | set(backfill_uids)
                blocked_reindex_uids = [
                    uid
                    for uid in store.active_blocked_uids(folder, limit=initial_limit)
                    if uid not in already_queued
                ]
            uids_to_index = new_uids_to_index + backfill_uids + blocked_reindex_uids
            checkpoint_uids = new_uids_to_index

        effective_skip_keywords = None if allow_blocked_body else skip_subject_keywords
        messages = client.get_messages_for_index(
            folder=folder,
            uids=uids_to_index,
            skip_subject_keywords=effective_skip_keywords,
            block_reason=block_reason,
        )
        for message in messages:
            store.upsert_message(folder, uidvalidity, message)

        last_uid = _max_uid(
            [state.last_uid if state else None]
            + _contiguous_indexed_uids(checkpoint_uids, messages)
        )
        store.update_folder_checkpoint(folder, uidvalidity, last_uid)

        did_full_check = full_check or _full_check_due(state)
        deleted_count = 0
        if did_full_check:
            deleted_count = store.mark_missing_deleted(folder, uid_list.uids)
            store.update_full_check_time(folder)

    return MailIndexSyncResult(
        folder=folder,
        uidvalidity=uidvalidity,
        indexed_count=len(messages),
        deleted_count=deleted_count,
        last_uid=last_uid,
        reset=reset,
        full_check=did_full_check,
    )


def search_mail_index(
    folder: str,
    query: str,
    limit: int = 20,
    index_path: Path | str | None = None,
) -> list[MailSearchResult]:
    store = MailIndexStore(index_path)
    store.initialize()
    return store.search(folder=folder, query=query, limit=limit)


def sync_result_dict(result: MailIndexSyncResult) -> dict:
    data = asdict(result)
    data["ok"] = True
    return data


def _needs_reset(state, uidvalidity: int | None) -> bool:
    if state is None:
        return False
    if state.uidvalidity is None or uidvalidity is None:
        return False
    return int(state.uidvalidity) != int(uidvalidity)


def _full_check_due(state) -> bool:
    if state is None or not state.last_full_check_at:
        return True
    try:
        last_check = datetime.fromisoformat(state.last_full_check_at)
    except ValueError:
        return True
    if last_check.tzinfo is None:
        last_check = last_check.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last_check >= timedelta(days=1)


def _max_uid(values: list[int | None]) -> int | None:
    concrete = [value for value in values if value is not None]
    return max(concrete) if concrete else None


def _contiguous_indexed_uids(requested_uids, messages) -> list[int]:
    indexed = {message.uid for message in messages}
    completed: list[int] = []
    for uid in requested_uids:
        if uid not in indexed:
            break
        completed.append(int(uid))
    return completed
