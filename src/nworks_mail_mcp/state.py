import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .config import load_state_path


@dataclass(frozen=True)
class MailCheckpoint:
    last_uid: int | None
    uidvalidity: int | None


class MailStateStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else load_state_path()

    def get_checkpoint(self, folder: str) -> MailCheckpoint:
        folder_state = self._read().get("folders", {}).get(folder)
        if not folder_state:
            return MailCheckpoint(last_uid=None, uidvalidity=None)

        last_uid = folder_state.get("last_uid")
        uidvalidity = folder_state.get("uidvalidity")
        return MailCheckpoint(
            last_uid=int(last_uid) if last_uid is not None else None,
            uidvalidity=int(uidvalidity) if uidvalidity is not None else None,
        )

    def get_last_uid(self, folder: str) -> int | None:
        return self.get_checkpoint(folder).last_uid

    def update_last_uid(self, folder: str, last_uid: int) -> None:
        checkpoint = self.get_checkpoint(folder)
        self.update_checkpoint(
            folder=folder,
            last_uid=last_uid,
            uidvalidity=checkpoint.uidvalidity,
        )

    def update_checkpoint(
        self,
        folder: str,
        last_uid: int | None,
        uidvalidity: int | None,
    ) -> None:
        state = self._read()
        folders = state.setdefault("folders", {})
        folders[folder] = {
            "last_uid": int(last_uid) if last_uid is not None else None,
            "uidvalidity": int(uidvalidity) if uidvalidity is not None else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write(state)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"folders": {}}

        with self.path.open("r", encoding="utf-8") as state_file:
            try:
                data = json.load(state_file)
            except JSONDecodeError as exc:
                raise RuntimeError(
                    f"Mail state file is not valid JSON: {self.path}"
                ) from exc

        if not isinstance(data, dict):
            return {"folders": {}}

        folders = data.get("folders")
        if not isinstance(folders, dict):
            data["folders"] = {}

        return data

    def _write(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        with temp_path.open("w", encoding="utf-8") as state_file:
            json.dump(state, state_file, ensure_ascii=True, indent=2)
            state_file.write("\n")
        os.replace(temp_path, self.path)
