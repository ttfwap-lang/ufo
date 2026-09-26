"""
Mask secrets before text is written to logs or files.

Covers the WebSocket ``?token=`` query value (device server URLs), API-key
style assignments, bearer tokens, and structured credentials that need no
surrounding keyword (Telegram bot tokens, OpenRouter/OpenAI/Anthropic/Google/
GitHub/AWS keys). Used by the logging handlers, the session FileWriter and the
WebSocket transport's connection errors.
"""
import logging
import re
from typing import Any

MASK = "***"
_PATTERNS = [
    (re.compile(r"(token=)[^&\s\"'\\]+", re.I), r"\1" + MASK),
    (re.compile(r"((?:api[_-]?key|x-api-key|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\s,\"'&}]+", re.I), r"\1" + MASK),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}", re.I), r"\1" + MASK),
    # Structured credentials: recognisable by shape alone, with no key-name
    # prefix - exactly how they appear in a pasted BotFather message or a dump.
    (re.compile(r"\b(\d{8,10}):[A-Za-z0-9_-]{35}\b"), r"\1:" + MASK),          # Telegram bot token
    (re.compile(r"\b(sk-(?:or-v1-|ant-)?)[A-Za-z0-9_-]{20,}"), r"\1" + MASK),   # OpenRouter/Anthropic/OpenAI
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), "AIza" + MASK),                   # Google
    (re.compile(r"\bghp_[A-Za-z0-9]{36}\b"), "ghp_" + MASK),                    # GitHub
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA" + MASK),                       # AWS
]


def redact(text: Any) -> Any:
    """Return text with secrets masked; non-strings are returned unchanged."""
    if not isinstance(text, str):
        return text
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    """Logging filter that masks secrets in the FORMATTED message.

    It used to redact ``msg`` and ``args`` separately. For
    ``logger.info("token=%s", tok)`` that turned the format string into
    ``"token=***"`` while ``tok`` stayed in ``args``: formatting then failed
    ("not all arguments converted"), and logging's error handler printed the
    raw arguments - the secret - to stderr. A secret split across msg and args
    (``"key: %s"``) was never matched at all. Formatting first and redacting the
    result handles both.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - malformed call: keep the parts, masked
            message = " ".join(
                [str(redact(record.msg))] + [str(redact(a)) for a in (
                    record.args if isinstance(record.args, tuple) else [record.args])])
        record.msg = redact(message)
        record.args = None
        return True
