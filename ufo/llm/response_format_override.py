"""Per-call override of the agent response format.

Agent services pin ``response_format`` to the HostAgent/AppAgent schema. Side
calls that need a different JSON shape (e.g. goal verification) set this
override for the duration of one request.
"""
import contextlib
import contextvars
from collections.abc import Iterator
from typing import Any

_override: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "ufo_response_format_override", default=None
)


def current() -> dict[str, Any] | None:
    return _override.get()


@contextlib.contextmanager
def response_format(fmt: dict[str, Any]) -> Iterator[None]:
    token = _override.set(fmt)
    try:
        yield
    finally:
        _override.reset(token)
