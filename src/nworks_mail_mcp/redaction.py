import json
import os
import re
from functools import lru_cache
from re import Pattern
from typing import Any


EXTRA_PATTERNS_ENV = "NWORKS_REDACTION_EXTRA_PATTERNS_JSON"

_RRN_RE = re.compile(r"\b\d{6}-[1-8]\d{6}\b")
_JWT_RE = re.compile(
    r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
)
_BEARER_RE = re.compile(
    r"\bAuthorization\s*:\s*Bearer\s+[A-Za-z0-9._~+/=-]{8,}",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?<![?&])\b(?P<key>access[_-]?token|refresh[_-]?token|api[_-]?key|x-api-key|"
    r"password|passwd|secret|private[_-]?key)\b"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<quote>[\"']?)"
    r"(?P<value>[^\s\"';&]+)"
    r"(?P=quote)?",
    re.IGNORECASE,
)
_URL_SECRET_RE = re.compile(
    r"(?P<prefix>[?&](?:token|access_token|refresh_token|api_key|key|secret)=)"
    r"(?P<value>[^&#\s]+)",
    re.IGNORECASE,
)


def redact_text(value: str) -> str:
    redacted = _RRN_RE.sub("[REDACTED:RRN]", value)
    redacted = _BEARER_RE.sub("[REDACTED:BEARER_TOKEN]", redacted)
    redacted = _JWT_RE.sub("[REDACTED:JWT]", redacted)
    redacted = _URL_SECRET_RE.sub(
        lambda match: f"{match.group('prefix')}[REDACTED:URL_TOKEN]",
        redacted,
    )
    redacted = _SECRET_VALUE_RE.sub(_redact_secret_value, redacted)

    for pattern in _extra_patterns():
        redacted = pattern.sub("[REDACTED:CUSTOM]", redacted)

    return redacted


def redact_mail_summary_dict(message: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(message)
    redacted["subject"] = redact_text(str(redacted.get("subject", "")))
    redacted["sender"] = redact_text(str(redacted.get("sender", "")))
    return redacted


def redact_mail_body_dict(
    message: dict[str, Any],
    max_chars: int | None = None,
) -> dict[str, Any]:
    redacted = redact_mail_summary_dict(message)
    redacted["body"] = redact_text(str(redacted.get("body", "")))
    if max_chars is not None and len(redacted["body"]) > max_chars:
        redacted["body"] = redacted["body"][:max_chars]
        redacted["truncated"] = True
    return redacted


def validate_redaction_config() -> None:
    _extra_patterns()


def _redact_secret_value(match: re.Match[str]) -> str:
    quote = match.group("quote")
    return (
        f"{match.group('key')}{match.group('sep')}"
        f"{quote}[REDACTED:SECRET]{quote}"
    )


@lru_cache(maxsize=1)
def _extra_patterns() -> tuple[Pattern[str], ...]:
    raw = os.getenv(EXTRA_PATTERNS_ENV)
    if not raw:
        return ()

    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{EXTRA_PATTERNS_ENV} must be a JSON array") from exc

    if not isinstance(values, list) or not all(
        isinstance(value, str) for value in values
    ):
        raise ValueError(f"{EXTRA_PATTERNS_ENV} must be a JSON array of strings")

    try:
        return tuple(re.compile(value) for value in values)
    except re.error as exc:
        raise ValueError(f"{EXTRA_PATTERNS_ENV} contains an invalid regex") from exc
