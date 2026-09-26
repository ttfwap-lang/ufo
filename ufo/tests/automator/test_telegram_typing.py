"""Free text must reach Telegram verbatim, and a failed chat search must be inert.

Two defects pinned here, both found by reading how pywinauto parses keys:

1. `send_keys` DROPS spaces by default and treats `% + ^ ~ ( ) { }` as syntax.
   The runner typed "Saved Messages" as "SavedMessages" (the real cause of the
   run-on spelling) and "50% off" as 5, 0, ALT+o, f, f.
2. The Ctrl+F fallback returned True unconditionally: with the focus in the
   wrong place it typed the chat name into the OPEN chat and pressed Enter,
   sending it as a message.

Nothing here injects input: `parse_keys` only builds the key list, and the
controller is driven with a stub that records what it was asked to type.
"""

import asyncio

import pytest

kb = pytest.importorskip("pywinauto.keyboard")

from ufo.automator.app_apis.telegram.telegram_gui import TelegramGUIController

# Modifier / control events that must never appear when typing plain text.
_CONTROL = ("VK_MENU", "VK_SHIFT", "VK_CONTROL", "VK_RETURN", "VK_TAB")


def _typed(text: str) -> str:
    """What send_keys would type for `text` through the literal path."""
    keys = kb.parse_keys(TelegramGUIController._literal_keys(text), with_spaces=True)
    out = []
    for k in keys:
        s = str(k)
        assert not any(c in s for c in _CONTROL), f"{text!r} produced control key {s}"
        # Character events render as "<c>"; the escaped ones ("{+}") as
        # "<+>" or via a KEsc wrapper carrying the character.
        out.append(s[1:-1] if s.startswith("<") and s.endswith(">") else s)
    return "".join(out)


@pytest.mark.parametrize(
    "text",
    [
        "Saved Messages",
        "50% off",
        "a+b (c)",
        "x^2 ~ y",
        "{braces}",
        "hello world, how are you?",
        "Ünïcödé ✓",
    ],
)
def test_literal_text_round_trips_exactly(text):
    typed = _typed(text)
    # KEsc wrappers render the character inside; compare on the characters.
    assert typed.replace("KEsc ", "") == text


def test_space_is_kept_and_default_behaviour_is_what_broke_it():
    default = "".join(str(k) for k in kb.parse_keys("Saved Messages"))
    assert " " not in default.replace("<", "").replace(">", "")  # the bug
    assert _typed("Saved Messages").count(" ") == 1  # the fix


def test_percent_is_not_an_alt_chord_any_more():
    broken = [str(k) for k in kb.parse_keys("50% off")]
    assert any("VK_MENU" in s for s in broken)  # what the runner used to do
    _typed("50% off")  # asserts no control keys inside


class _Stub(TelegramGUIController):
    """Controller with every side effect replaced by a recorder."""

    def __init__(self, field):
        super().__init__(desktop=object())
        self._window = object()
        self.typed_keys, self.typed_text, self.shots = [], [], []
        self._field = field

    async def _find_sidebar_search(self):
        return self._field

    async def troubleshoot_screenshot(self, label="troubleshoot"):
        self.shots.append(label)
        return None

    async def _click_at_rect(self, rect):
        return True

    async def _type_keys_safe(self, keys, literal=False):
        (self.typed_text if literal else self.typed_keys).append(keys)
        return True

    async def _ensure_window_fresh(self):
        return True


def test_search_refuses_to_type_when_the_field_is_missing():
    c = _Stub(field=None)
    assert asyncio.run(c._open_chat_by_keyboard("Saved Messages")) is False
    # Nothing at all was typed: not the name, not Enter.
    assert c.typed_keys == [] and c.typed_text == []
    assert c.shots == ["search_field_missing"]


def test_search_reports_failure_when_the_title_never_matches():
    from ufo.automation.desktop import Element, Rect

    class _Win:
        name = "Some Other Chat"

    field = Element(handle=object(), name="Search", class_name="Ui::InputField",
                    rect=Rect(left=10, top=10, right=200, bottom=40))
    c = _Stub(field=field)
    c._window = _Win()
    assert asyncio.run(c._open_chat_by_keyboard("Saved Messages")) is False
    assert c.typed_text == ["Saved Messages"]  # typed once, spaces intact
    assert "open_chat_search_failed" in c.shots  # Rule 3: evidence captured
    assert c.typed_keys[-1] == c.SHORTCUTS["escape"]  # search cleaned up


def test_search_succeeds_only_when_the_title_proves_it_and_does_not_escape():
    from ufo.automation.desktop import Element, Rect

    class _Win:
        name = "Saved Messages - (1)"

    field = Element(handle=object(), name="Search", class_name="Ui::InputField",
                    rect=Rect(left=10, top=10, right=200, bottom=40))
    c = _Stub(field=field)
    c._window = _Win()
    assert asyncio.run(c._open_chat_by_keyboard("SavedMessages")) is True
    assert c.typed_text == ["Saved Messages"]  # canonicalised before typing
    assert c.SHORTCUTS["escape"] not in c.typed_keys  # Esc would close the chat


def test_multiline_text_uses_shift_enter_never_plain_enter():
    c = _Stub(field=None)
    assert asyncio.run(c._type_text_safe("line one\nline two")) is True
    assert c.typed_text == ["line one", "line two"]
    assert c.typed_keys == [c.SHORTCUTS["new_line"]]
