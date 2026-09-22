"""
Mask secrets before text is written to logs or files.

Covers the WebSocket ``?token=`` query value (device server URLs), API-key
style assignments and bearer tokens. Used by the logging handlers, the
session FileWriter and the WebSocket transport's connection errors.
"""
import logging
import re
from typing import Any

MASK = "***"
_PATTERNS = [
    (re.compile(r"(token=)[^&\s\"'\\]+", re.I), r"\1" + MASK),
    (re.compile(r"((?:api[_-]?key|x-api-key|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\s,\"'&}]+", re.I), r"\1" + MASK),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}", re.I), r"\1" + MASK),
]


def redact(text: Any) -> Any:
    """Return text with secrets masked; non-strings are returned unchanged."""
    if not isinstance(text, str):
        return text
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    """Logging filter that masks secrets in the message and its arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact(v) for k, v in record.args.items()}
        return True
