from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int
    username: str
    password: str


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def load_imap_config() -> ImapConfig:
    return ImapConfig(
        host=os.getenv("NWORKS_IMAP_HOST", "imap.worksmobile.com"),
        port=int(os.getenv("NWORKS_IMAP_PORT", "993")),
        username=_required_env("NWORKS_MAIL_ADDRESS"),
        password=_required_env("NWORKS_APP_PASSWORD"),
    )


def load_state_path() -> Path:
    return Path(os.getenv("NWORKS_STATE_PATH", ".nworks_mail_state.json"))


def load_index_path() -> Path:
    return Path(os.getenv("NWORKS_INDEX_PATH", ".nworks_mail_index.sqlite"))
