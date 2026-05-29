import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import load_index_path
from .imap_client import MailIndexMessage


@dataclass(frozen=True)
class FolderIndexState:
    folder: str
    uidvalidity: int | None
    last_uid: int | None
    last_full_check_at: str | None


@dataclass(frozen=True)
class MailSearchResult:
    uid: str
    folder: str
    subject: str
    sender: str
    date: str
    excerpt: str
    score: float
    is_deleted: bool
    body_index_blocked: bool
    block_reason: str | None


class MailIndexStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else load_index_path()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS folders (
                    folder TEXT PRIMARY KEY,
                    uidvalidity INTEGER,
                    last_uid INTEGER,
                    last_full_check_at TEXT
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder TEXT NOT NULL,
                    uid TEXT NOT NULL,
                    uid_int INTEGER NOT NULL,
                    uidvalidity INTEGER,
                    subject TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    date TEXT NOT NULL,
                    body TEXT NOT NULL,
                    body_text_type TEXT NOT NULL,
                    truncated INTEGER NOT NULL DEFAULT 0,
                    body_index_blocked INTEGER NOT NULL DEFAULT 0,
                    block_reason TEXT,
                    is_deleted INTEGER NOT NULL DEFAULT 0,
                    synced_at TEXT NOT NULL,
                    deleted_at TEXT,
                    UNIQUE(folder, uid)
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS mail_fts
                USING fts5(subject, body, tokenize='unicode61');
                """
            )

    def get_folder_state(self, folder: str) -> FolderIndexState | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT folder, uidvalidity, last_uid, last_full_check_at
                FROM folders
                WHERE folder = ?
                """,
                (folder,),
            ).fetchone()
        if row is None:
            return None
        return FolderIndexState(
            folder=row["folder"],
            uidvalidity=row["uidvalidity"],
            last_uid=row["last_uid"],
            last_full_check_at=row["last_full_check_at"],
        )

    def reset_folder(self, folder: str, uidvalidity: int | None) -> None:
        with self._connect() as conn:
            ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM messages WHERE folder = ?",
                    (folder,),
                )
            ]
            conn.executemany("DELETE FROM mail_fts WHERE rowid = ?", [(id_,) for id_ in ids])
            conn.execute("DELETE FROM messages WHERE folder = ?", (folder,))
            conn.execute(
                """
                INSERT INTO folders(folder, uidvalidity, last_uid, last_full_check_at)
                VALUES (?, ?, NULL, NULL)
                ON CONFLICT(folder) DO UPDATE SET
                    uidvalidity = excluded.uidvalidity,
                    last_uid = NULL,
                    last_full_check_at = NULL
                """,
                (folder, uidvalidity),
            )

    def upsert_message(
        self,
        folder: str,
        uidvalidity: int | None,
        message: MailIndexMessage,
    ) -> None:
        now = _utc_now()
        uid_int = int(message.uid)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM messages WHERE folder = ? AND uid = ?",
                (folder, message.uid),
            ).fetchone()
            values = (
                uidvalidity,
                message.subject,
                message.sender,
                message.date,
                message.body,
                message.body_text_type,
                int(message.truncated),
                int(message.body_index_blocked),
                message.block_reason,
                now,
                uid_int,
                folder,
                message.uid,
            )
            if row is None:
                conn.execute(
                    """
                    INSERT INTO messages(
                        uidvalidity, subject, sender, date, body, body_text_type,
                        truncated, body_index_blocked, block_reason, synced_at,
                        uid_int, folder, uid
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                row = conn.execute(
                    "SELECT id FROM messages WHERE folder = ? AND uid = ?",
                    (folder, message.uid),
                ).fetchone()
            else:
                conn.execute(
                    """
                    UPDATE messages
                    SET uidvalidity = ?, subject = ?, sender = ?, date = ?,
                        body = ?, body_text_type = ?, truncated = ?,
                        body_index_blocked = ?, block_reason = ?, synced_at = ?,
                        uid_int = ?, is_deleted = 0, deleted_at = NULL
                    WHERE folder = ? AND uid = ?
                    """,
                    values,
                )

            conn.execute("DELETE FROM mail_fts WHERE rowid = ?", (row["id"],))
            conn.execute(
                "INSERT INTO mail_fts(rowid, subject, body) VALUES (?, ?, ?)",
                (row["id"], message.subject, message.body),
            )

    def update_folder_checkpoint(
        self,
        folder: str,
        uidvalidity: int | None,
        last_uid: int | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO folders(folder, uidvalidity, last_uid, last_full_check_at)
                VALUES (?, ?, ?, NULL)
                ON CONFLICT(folder) DO UPDATE SET
                    uidvalidity = excluded.uidvalidity,
                    last_uid = excluded.last_uid
                """,
                (folder, uidvalidity, last_uid),
            )

    def update_full_check_time(self, folder: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO folders(folder, last_full_check_at)
                VALUES (?, ?)
                ON CONFLICT(folder) DO UPDATE SET
                    last_full_check_at = excluded.last_full_check_at
                """,
                (folder, _utc_now()),
            )

    def active_uids(self, folder: str) -> set[str]:
        with self._connect() as conn:
            return {
                row["uid"]
                for row in conn.execute(
                    "SELECT uid FROM messages WHERE folder = ? AND is_deleted = 0",
                    (folder,),
                )
            }

    def active_blocked_uids(self, folder: str, limit: int | None = None) -> list[str]:
        sql = """
            SELECT uid
            FROM messages
            WHERE folder = ?
              AND is_deleted = 0
              AND body_index_blocked = 1
            ORDER BY uid_int DESC
        """
        params: tuple[str] | tuple[str, int] = (folder,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (folder, limit)

        with self._connect() as conn:
            return [row["uid"] for row in conn.execute(sql, params)]

    def mark_missing_deleted(self, folder: str, current_uids: Iterable[str]) -> int:
        current = set(current_uids)
        active = self.active_uids(folder)
        missing = active - current
        if not missing:
            return 0

        now = _utc_now()
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE messages
                SET is_deleted = 1, deleted_at = ?
                WHERE folder = ? AND uid = ?
                """,
                [(now, folder, uid) for uid in missing],
            )
        return len(missing)

    def search(self, folder: str, query: str, limit: int = 20) -> list[MailSearchResult]:
        fts_query = _fts_query(query)
        if not fts_query:
            return []

        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT m.uid, m.folder, m.subject, m.sender, m.date,
                           snippet(mail_fts, 1, '', '', '...', 18) AS excerpt,
                           bm25(mail_fts) AS score,
                           m.is_deleted, m.body_index_blocked, m.block_reason
                    FROM mail_fts
                    JOIN messages AS m ON m.id = mail_fts.rowid
                    WHERE mail_fts MATCH ?
                      AND m.folder = ?
                      AND m.is_deleted = 0
                    ORDER BY score ASC
                    LIMIT ?
                    """,
                    (fts_query, folder, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []

            if not rows:
                tokens = _query_tokens(query)
                conditions = []
                params: list[str | int] = [folder]
                for token in tokens:
                    like = f"%{token}%"
                    conditions.append("(subject LIKE ? OR body LIKE ?)")
                    params.extend([like, like])
                params.append(limit)

                rows = conn.execute(
                    """
                    SELECT uid, folder, subject, sender, date, body AS excerpt,
                           0.0 AS score, is_deleted, body_index_blocked, block_reason
                    FROM messages
                    WHERE folder = ?
                      AND is_deleted = 0
                      AND """ + " AND ".join(conditions) + """
                    ORDER BY uid_int DESC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()

        return [
            MailSearchResult(
                uid=row["uid"],
                folder=row["folder"],
                subject=row["subject"],
                sender=row["sender"],
                date=row["date"],
                excerpt=_shorten(row["excerpt"] or ""),
                score=float(row["score"]),
                is_deleted=bool(row["is_deleted"]),
                body_index_blocked=bool(row["body_index_blocked"]),
                block_reason=row["block_reason"],
            )
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fts_query(query: str) -> str:
    tokens = _query_tokens(query)
    return " ".join(f'"{token}"' for token in tokens)


def _query_tokens(query: str) -> list[str]:
    return re.findall(r"\w+", query, flags=re.UNICODE)


def _shorten(value: str, max_chars: int = 500) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "..."
