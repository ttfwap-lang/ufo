"""open_chat() must not call a successful navigation a failure.

Telegram retitles the window asynchronously when a chat becomes active. The old
verification took ONE sample at a fixed +0.8 s after the click or after Enter in
the search fallback, and if the title had not caught up yet it reported failure.

Observed on 2026-09-26: validate_all.py printed

    [open_chat] search for 'Saved Messages' did not open it
    3. Real chat-row click navigation: False

while the window title afterwards read 'Saved Messages - (2600)'. The chat WAS
open; the check simply sampled before the title updated. That false negative is
not cosmetic: send_message() aborts when open_chat() reports False, so a message
send would have failed against a correctly opened chat.

These tests drive _await_title_match() with a title that only becomes correct
after several reads, which is exactly the condition the live run could not be
relied on to produce - whether Telegram has already retitled depends on what a
previous run left open. Making the delay explicit is what makes the race
testable instead of something you hope to catch.

This file is deliberately ASCII-only: the live title contains U+200E and U+2013,
and writing those literally corrupted the file (they became U+FFFD), so they are
built with chr() below instead.
"""

from __future__ import annotations

import time

from ufo.automator.app_apis.telegram.telegram_gui import TelegramGUIController

LRM = chr(0x200E)   # left-to-right mark Telegram puts at the front of titles
EN_DASH = chr(0x2013)

# The exact title read off a live window, built without literal non-ASCII.
REAL_TITLE = LRM + "Saved Messages " + EN_DASH + " (2600)"
OTHER_TITLE = "Telegram (2600)"


class _SlowRetitleWindow:
    """A window whose title only becomes correct after `delay_reads` reads."""

    def __init__(self, delay_reads: int, final_title: str, other_title: str) -> None:
        self._reads = 0
        self._delay = delay_reads
        self._final = final_title
        self._other = other_title

    @property
    def name(self) -> str:
        self._reads += 1
        return self._other if self._reads <= self._delay else self._final


def _controller(window) -> TelegramGUIController:
    """Build a bare controller: only what _await_title_match touches."""
    controller = TelegramGUIController.__new__(TelegramGUIController)

    async def _no_op_fresh() -> None:
        return None

    controller._ensure_window_fresh = _no_op_fresh
    controller._window = window
    return controller


async def test_poll_wins_a_race_a_single_sample_would_lose() -> None:
    """Title correct only after 5 reads: one sample would have said 'not open'."""
    window = _SlowRetitleWindow(
        delay_reads=5, final_title=REAL_TITLE, other_title=OTHER_TITLE
    )
    # precondition: the first read - the only one the old code performed - misses
    assert window.name != REAL_TITLE

    controller = _controller(window)
    started = time.monotonic()
    result = await controller._await_title_match(
        "Saved Messages", budget=2.0, interval=0.02
    )
    elapsed = time.monotonic() - started

    assert result is True, "a navigation that landed must not be reported as failed"
    # it must have actually polled, not passed on the first sample
    assert elapsed >= 0.05, f"returned after {elapsed:.3f}s - no polling happened"


async def test_poll_returns_immediately_when_already_open() -> None:
    """No needless delay when the title is already right."""
    window = _SlowRetitleWindow(
        delay_reads=0, final_title=REAL_TITLE, other_title=OTHER_TITLE
    )
    controller = _controller(window)

    started = time.monotonic()
    assert await controller._await_title_match(
        "Saved Messages", budget=2.0, interval=0.02
    ) is True
    assert time.monotonic() - started < 0.1


async def test_poll_gives_up_when_the_chat_really_is_absent() -> None:
    """Bounded: a missing chat still fails, promptly and on the same criteria."""
    # Neither title contains the target, so this can only ever miss.
    window = _SlowRetitleWindow(
        delay_reads=10_000,          # never becomes correct within the budget
        final_title=OTHER_TITLE,
        other_title=OTHER_TITLE,
    )
    controller = _controller(window)

    started = time.monotonic()
    result = await controller._await_title_match(
        "Saved Messages", budget=0.3, interval=0.05
    )
    elapsed = time.monotonic() - started

    assert result is False
    assert 0.3 <= elapsed < 1.5, f"budget not respected: {elapsed:.3f}s"


async def test_poll_accepts_the_real_title_shape() -> None:
    """The live title carries U+200E at the front and an en dash, not a hyphen.

    NFKC strips neither, so the matcher - and therefore the poll - has to
    tolerate them, or verification fails on a title that is plainly correct.
    """
    assert LRM in REAL_TITLE and EN_DASH in REAL_TITLE
    assert "-" not in REAL_TITLE, "the real separator is an en dash, not a hyphen"

    window = _SlowRetitleWindow(
        delay_reads=2, final_title=REAL_TITLE, other_title=OTHER_TITLE
    )
    controller = _controller(window)

    assert await controller._await_title_match(
        "Saved Messages", budget=1.0, interval=0.02
    ) is True
