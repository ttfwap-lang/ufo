"""Canonical Telegram chat names.

WHY THIS EXISTS
---------------
Telegram's own chat is named **"Saved Messages"** - two words, with a space.
It is *not* "SavedMessages", and the two are not interchangeable anywhere that
matters:

  * Telegram's sidebar search is a plain substring match against the real chat
    name, so typing "SavedMessages" finds nothing. It is the single most common
    way an automation run derails at step one.
  * UIA window text for the row is "Saved Messages, <preview>"; a
    space-insensitive guess is required to read that first token reliably.
  * The name reaches this code from three untrusted directions: hard-coded
    strings in the repo, test harnesses, and LLM-generated tool arguments.
    An LLM that emits "SavedMessages" is not making an error we should have to
    debug at 3am.

So chat names are normalised in ONE place, permanently, and the canonical
spelling is what gets typed into the search box. Comparison is
whitespace-insensitive, so even a name we failed to canonicalise still matches
the real sidebar row.

The canonical form of a chat name is the name exactly as Telegram displays it.
`canonical_chat_name` returns that; `chat_key` returns the loose key used for
matching.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Optional

# The self-chat. Always spelled with the space - this is the one constant every
# caller, test and tool should import rather than retyping.
SAVED_MESSAGES = "Saved Messages"


# Aliases seen in the wild (LLM output, older tests, ad-hoc scripts) mapped to
# the exact spelling Telegram displays. Keys are compared via `chat_key`, so
# case and spacing in the alias do not matter.
_ALIASES: Dict[str, str] = {
    "savedmessages": SAVED_MESSAGES,
    "myaccount": SAVED_MESSAGES,
    "cloudchats": "Cloud Chats",
    "telegramdesktop": "Telegram Desktop",
}

# A boundary between two words: lower->Upper ("savedMessages"), and
# Upper->Upper->lower inside an acronym run ("TelegramDesktop" -> "Telegram
# Desktop"). A digit run also separates.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WS = re.compile(r"\s+")

# Telegram separates the unread count in the window title with an EN DASH
# (U+2013), not a hyphen: "Saved Messages \u2013 (3166)". Matching only the
# ASCII hyphen leaves the whole unread suffix attached to the name. Accept
# every dash a UI toolkit realistically emits, plus the Unicode minus sign.
_DASHES = "--\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
_UNREAD_SUFFIX = re.compile(rf"\s*[{_DASHES}]\s*\(\d+\s*\)\s*$")

# Invisible characters that survive NFKC. U+200E LEFT-TO-RIGHT MARK leads the
# real window title ("\u200eSaved Messages"), and U+200B..U+200D / U+FEFF /
# U+2060 turn up in scraped text. NFKC does NOT remove them - they are format
# characters, category Cf - so they have to go explicitly. This matters most
# for canonical_chat_name(), whose output is TYPED into Telegram's search box:
# a stray LRM in the query makes the search match nothing, which is the exact
# failure this module exists to prevent.
_INVISIBLE = frozenset("".join(
    chr(c) for c in range(0x110000) if unicodedata.category(chr(c)) in ("Cf", "Cc")
))


def _nfkc(value: str) -> str:
    """Normalise unicode so lookalike spaces/case cannot smuggle in a mismatch."""
    text = unicodedata.normalize("NFKC", value or "").replace("\u00a0", " ")
    # Collapse real whitespace FIRST, then drop invisible characters. Doing it
    # the other way round would delete the newlines/tabs in a multi-line scrape
    # and silently join the words on either side.
    text = _WS.sub(" ", text)
    return "".join(c for c in text if c not in _INVISIBLE)


def _base_name(value: str) -> str:
    """Strip Telegram's decorations from a raw scraped/title name.

    A sidebar row reads "<chat name>, <message preview>" and the window title
    reads "<chat name> - (n)" for the unread count (with an en dash). Both
    decorations must go before anything else, otherwise a scraped name never
    matches the clean spelling a caller passes in.
    """
    cleaned = _UNREAD_SUFFIX.split(value)[0].strip()
    return cleaned.split(",", 1)[0].strip()


def _split_camel(value: str) -> str:
    """Insert word boundaries in a run-on name: SavedMessages -> Saved Messages."""
    if " " in value:
        return value
    return _CAMEL_BOUNDARY.sub(" ", value)


def canonical_chat_name(name: Optional[str]) -> str:
    """Return the exact spelling Telegram displays for `name`.

    Resolution order:
      1. strip Telegram's own decorations (", preview", "- (n)"),
      2. known alias table (self-chat, Cloud Chats, ...),
      3. split run-together CamelCase word boundaries,
      4. collapse stray whitespace.

    An empty/None name returns "" so callers can test the result directly.
    """
    if not name:
        return ""

    cleaned = _WS.sub(" ", _nfkc(name)).strip()
    if not cleaned:
        return ""

    cleaned = _base_name(cleaned)
    if not cleaned:
        return ""

    alias = _ALIASES.get(_WS.sub("", cleaned).casefold())
    if alias:
        return alias

    return _split_camel(cleaned).strip()


def chat_key(name: Optional[str]) -> str:
    """Loose key for comparing chat names, for MATCHING only.

    Every spelling that means the same chat collapses to one key: the display
    spelling with all whitespace and case removed. So "Saved Messages",
    "saved  messages", "SavedMessages", "My Account" and the scraped row
    "Saved Messages, ping 12" all key to ``savedmessages``, and matching
    against the sidebar is forgiving even when the caller spelled it wrong.

    For *typing into the search box* use `canonical_chat_name` instead - the
    search box does a substring match on the real name and needs the real
    spelling.
    """
    canonical = canonical_chat_name(name)
    if not canonical:
        return ""
    return _WS.sub("", canonical).casefold()


def is_saved_messages(name: Optional[str]) -> bool:
    """True when `name` refers to the self-chat, however it was spelled."""
    return chat_key(name) == chat_key(SAVED_MESSAGES)


def pick_best_match(query: str, candidates: Iterable[str]) -> Optional[str]:
    """Choose the candidate that best matches `query`, spacing-agnostically.

    Used to reconcile a caller-supplied name against the names actually visible
    in the sidebar: a canonical hit wins, then a whitespace-insensitive hit,
    then a unique substring hit. Returns None when nothing is close enough to
    act on - guessing here means clicking the wrong chat.

    Preserves the caller's original spelling of the winner, because that is the
    text Telegram will accept in its search box.
    """
    cands: List[str] = [c for c in candidates if c]
    if not cands:
        return None

    q_key = chat_key(query)
    if not q_key:
        return None

    # 1. Exact match on the canonical spelling.
    canonical = canonical_chat_name(query)
    for c in cands:
        if canonical_chat_name(c).casefold() == canonical.casefold():
            return c

    # 2. Exact match ignoring spacing/case.
    for c in cands:
        if chat_key(c) == q_key:
            return c

    # 3. Substring, but only if it is unambiguous.
    hits = [c for c in cands if q_key in chat_key(c)]
    if len(hits) == 1:
        return hits[0]
    return None
