"""Telegram chat names are canonicalised once, permanently.

The self-chat is "Saved Messages" (two words). "SavedMessages" is not the same
string to Telegram's search box, which does a substring match on the real name -
so the run-on spelling silently finds nothing. These tests pin the guard that
makes that impossible, for every spelling that reaches the controller from
hand-written code, older scripts, and LLM-generated tool arguments.
"""

import pytest

from ufo.automator.app_apis.telegram.chat_names import (
    SAVED_MESSAGES,
    canonical_chat_name,
    chat_key,
    is_saved_messages,
    pick_best_match,
)
from ufo.automator.app_apis.telegram.telegram_gui import TelegramGUIController

# Every spelling observed in the wild.
RUN_ON = [
    "SavedMessages",
    "savedMessages",
    "SAVEDMESSAGES",
    "savedmessages",
    "Saved messages",
]
DECORATED = [
    "Saved Messages",
    "  Saved   Messages  ",
    "Saved\u00a0Messages",           # non-breaking space
    "My Account",                     # what the UI calls it elsewhere
    "myaccount",
    "Saved Messages, you can send messages",   # sidebar row
    "Saved Messages - (3)",                    # window title + unread
    # The REAL window title read off a live Telegram window on 2026-09-26. It
    # carries an en dash (U+2013), not a hyphen, and a U+200E LEFT-TO-RIGHT
    # MARK at the front. NFKC removes neither, and canonical_chat_name() is what
    # gets typed into the search box - so a leftover LRM makes the search match
    # nothing, which is the exact failure this module exists to prevent.
    "\u200eSaved Messages \u2013 (3166)",
    "\u200eSaved Messages \u2013 (1)",
    "\ufeffSaved Messages \u2013 (2)",          # stray BOM
    "\u200bSaved\u200bMessages",
]

# Titles of OTHER chats, one per dash flavour, to prove the unread suffix is
# stripped for everyone and not just for the self-chat.
OTHER_TITLES = [
    ("Cloud Chats \u2013 (12)", "Cloud Chats"),      # en dash
    ("Cloud Chats \u2014 (12)", "Cloud Chats"),      # em dash
    ("Work Group \u2212 (7)", "Work Group"),         # unicode minus
    ("Telegram - (0)", "Telegram"),                  # ascii hyphen
]
SIDEBAR = [
    "Saved Messages, ping 12",
    "General Horoscopes, today",
    "Telegram, welcome",
    "Cloud Chats, 3 online",
    "Work Group, standup at 10",
]


def test_constant_is_the_real_spelling():
    assert SAVED_MESSAGES == "Saved Messages"
    # Explicitly: the run-together form is NOT the real name.
    assert SAVED_MESSAGES != "SavedMessages"
    assert SAVED_MESSAGES.count(" ") == 1


@pytest.mark.parametrize("variant", RUN_ON)
def test_run_together_spelling_is_canonicalised(variant):
    """The bug this module exists to prevent."""
    assert canonical_chat_name(variant) == SAVED_MESSAGES


@pytest.mark.parametrize("variant", DECORATED)
def test_decorated_names_are_canonicalised(variant):
    assert canonical_chat_name(variant) == SAVED_MESSAGES


@pytest.mark.parametrize("variant", RUN_ON + DECORATED)
def test_every_spelling_shares_one_key(variant):
    assert chat_key(variant) == chat_key(SAVED_MESSAGES)


@pytest.mark.parametrize("variant", RUN_ON + DECORATED)
def test_is_saved_messages_recognises_all_spellings(variant):
    assert is_saved_messages(variant)


def test_pick_best_match_finds_the_row_from_a_wrong_spelling():
    assert pick_best_match("SavedMessages", SIDEBAR) == "Saved Messages, ping 12"
    assert pick_best_match("Saved Messages", SIDEBAR) == "Saved Messages, ping 12"


def test_pick_best_match_never_guesses():
    """A wrong chat is far worse than a miss - ambiguity must return None."""
    assert pick_best_match("Nonexistent Chat", SIDEBAR) is None
    assert pick_best_match("o", SIDEBAR) is None      # ambiguous substring
    assert pick_best_match("", SIDEBAR) is None
    assert pick_best_match("Saved Messages", []) is None


def test_other_chats_are_left_alone():
    assert canonical_chat_name("Telegram") == "Telegram"
    assert canonical_chat_name("General Horoscopes") == "General Horoscopes"
    assert canonical_chat_name("Work Group, standup at 10") == "Work Group"
    assert canonical_chat_name("CloudChats") == "Cloud Chats"


def test_empty_input():
    assert canonical_chat_name("") == ""
    assert canonical_chat_name(None) == ""
    assert chat_key(None) == ""
    assert is_saved_messages(None) is False


def test_controller_exposes_the_constant():
    assert TelegramGUIController.SAVED_MESSAGES == SAVED_MESSAGES


def test_canonical_output_is_safe_to_type():
    """canonical_chat_name() is what gets TYPED into Telegram's search box.

    Telegram matches that query as a substring of the real chat name, so any
    invisible character surviving normalisation is a silent search miss. Every
    code point in the result must be printable.
    """
    import unicodedata

    for variant in RUN_ON + DECORATED:
        out = canonical_chat_name(variant)
        bad = [c for c in out if unicodedata.category(c) in ("Cf", "Cc", "Co", "Cn")]
        assert not bad, f"{variant!r} -> {out!r} kept invisible chars {bad!r}"


def test_real_window_title_canonicalises_exactly():
    """Regression: the live title is '\\u200eSaved Messages \\u2013 (3166)'.

    It used to return the title verbatim - en dash unmatched, LRM kept - which
    meant open_chat() typed an unmatchable query.
    """
    live = "\u200eSaved Messages \u2013 (3166)"
    assert canonical_chat_name(live) == SAVED_MESSAGES
    assert chat_key(live) == chat_key(SAVED_MESSAGES)


@pytest.mark.parametrize("title,expected", OTHER_TITLES)
def test_unread_suffix_is_stripped_for_every_dash_flavour(title, expected):
    assert canonical_chat_name(title) == expected


def test_title_verification_survives_a_wrong_spelling():
    """open_chat() verifies via the retitled window; a spelling difference
    must not make verification fail and trigger pointless retries."""
    match = TelegramGUIController._title_matches_chat
    assert match(TelegramGUIController, "Saved Messages - (2)", "SavedMessages") is True
    assert match(TelegramGUIController, "Saved Messages - (2)", "Saved Messages") is True
    assert match(TelegramGUIController, "Saved Messages - (2)", "Cloud Chats") is False
    assert match(TelegramGUIController, "", "Saved Messages") is False
    # The real observed title, LRM and en dash included.
    assert match(TelegramGUIController, "\u200eSaved Messages \u2013 (3166)",
                 "SavedMessages") is True
