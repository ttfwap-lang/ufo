"""Privacy-first message redaction for the Telegram automaton.

Design principle: the AI NEVER reads message content for context. All
message text passes through :class:`PrivacyRedactor`, which:

- **Redacts (never stores/returns) message content** unless the message
  contains an error/failure indicator keyword.
- Only error/failure messages may be read and learned from (fail, error,
  sorry, unable, cannot, denied, timeout, retry, ... plus Chinese
  equivalents) - because those are operationally necessary to learn
  recovery behavior.
- Non-error content is replaced with a fixed placeholder so nothing
  leaks into memory, skills, logs, or verification evidence.

This applies to every place the automaton might otherwise ingest text:
message reading, chat previews, verification details, skill learning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

# Error/failure indicator keywords (English + Chinese + common shop terms)
ERROR_KEYWORDS: List[str] = [
    # English
    "fail", "failed", "failure", "error", "exception", "sorry", "unable",
    "cannot", "can't", "could not", "could not be", "denied", "declined",
    "timeout", "time out", "retry", "blocked", "invalid", "insufficient",
    "wrong", "incorrect", "unsupported", "not available", "not found",
    "problem", "issue", "broken", "timed", "too many", "rate limit",
    "sold out", "out of stock", "no results", "please try again",
    "something went wrong", "try later", "please wait",
    # Chinese (error-related)
    "失败", "错误", "无法", "不能", "拒绝", "重试", "超时", "卡密",
    "余额不足", "未找到", "无效", "耐心等待", "没有返回", "不存在",
    "卖完", "过时", "请等待", "稍后", "订单失败", "异常",
]

# The placeholder that replaces all redacted (non-error) content.
REDACTED = "[REDACTED - message content not logged]"


@dataclass
class RedactionResult:
    """Result of redacting a message."""
    is_error: bool                 # True only if error keywords matched
    safe_text: str                 # REDACTED placeholder, or the error text
    matched_keyword: Optional[str] = None  # first keyword that matched


class PrivacyRedactor:
    """Redacts message content unless it is an error/failure message."""

    def __init__(self, extra_keywords: Optional[List[str]] = None):
        """Initialize with optional extra keywords appended to the default set."""
        self._keywords = list(ERROR_KEYWORDS)
        if extra_keywords:
            self._keywords.extend(extra_keywords)

    def classify(self, text: Optional[str] = None) -> bool:
        """Return True if text is an error/failure message (may be read)."""
        if not text:
            return False
        low = text.lower()
        for kw in self._keywords:
            if kw.lower() in low:
                return True
        return False

    def redact(self, text: Optional[str] = None) -> RedactionResult:
        """Redact message text per the privacy policy.

        - Error/failure text: returned as-is with keyword noted (the ONLY
          content the AI is ever allowed to read).
        - Everything else: replaced with REDACTED placeholder.
        """
        if not text:
            return RedactionResult(is_error=False, safe_text=REDACTED)
        low = text.lower()
        for kw in self._keywords:
            if kw.lower() in low:
                return RedactionResult(
                    is_error=True, safe_text=text[:2000], matched_keyword=kw
                )
        return RedactionResult(is_error=False, safe_text=REDACTED)

    def safe_preview(self, text: Optional[str] = None) -> str:
        """Always-redacted preview (for chat list/metadata)."""
        if not text:
            return REDACTED
        return REDACTED

    def error_phrase(self, text: Optional[str] = None) -> Optional[str]:
        """Extract a short error phrase for learning (error messages only)."""
        res = self.redact(text)
        if not res.is_error:
            return None
        # Keep only the sentence containing the keyword - enough to learn
        # the error shape without storing the full body.
        sentences = re.split(r"(?<=[.!?。！？])", res.safe_text)
        for s in sentences:
            if res.matched_keyword and res.matched_keyword.lower() in s.lower():
                return s.strip()[:200]
        return res.safe_text[:200]
