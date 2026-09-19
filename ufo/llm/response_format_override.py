"""Per-call override of the agent response format.

Agent services pin ``response_format`` to the HostAgent/AppAgent schema. Side
calls that need a different JSON shape (e.g. goal verification) set this
override for the duration of one request.
"""
import contextlib
import contextvars
from typing import Any, Dict, Iterator, Optional

_override: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "ufo_response_format_override", default=None
)


def current() -> Optional[Dict[str, Any]]:
    return _override.get()


@contextlib.contextmanager
def response_format(fmt: Dict[str, Any]) -> Iterator[None]:
    token = _override.set(fmt)
    try:
        yield
    finally:
        _override.reset(token)
