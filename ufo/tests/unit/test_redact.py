"""Secrets never reach logs: redact helper, logging filter, FileWriter, transport errors."""
import asyncio
import logging

import pytest

from ufo.utils.redact import RedactingFilter, redact

TOKEN = "0123456789abcdef" * 3  # fake 48-hex token


@pytest.mark.parametrize(
    "text, leaked",
    [
        (f"ws://localhost:5001/ws?token={TOKEN}", TOKEN),
        (f"ws://h/ws?a=1&token={TOKEN}&b=2", TOKEN),
        ('{"server_url": "ws://localhost:5001/ws?token=' + TOKEN + '"}', TOKEN),
        ("api_key: sk-abcdef123456", "sk-abcdef123456"),
        ('"X-API-Key": "k3y-value-123"', "k3y-value-123"),
        ("Authorization: Bearer abcdefghijklmnop", "abcdefghijklmnop"),
    ],
)
def test_redact_masks_secrets(text, leaked):
    out = redact(text)
    assert leaked not in out and "***" in out


def test_redact_keeps_normal_text_and_non_strings():
    assert redact("open notepad and type hello") == "open notepad and type hello"
    assert redact(42) == 42 and redact(None) is None
    assert redact("ws://localhost:5001/ws&b=2?a=1").endswith("?a=1")


def test_logging_filter_masks_message_and_args(caplog):
    log = logging.getLogger("redact-test")
    handler_filter = RedactingFilter()
    record = log.makeRecord("redact-test", logging.ERROR, __file__, 1,
                            "Failed to connect to %s", (f"ws://x/ws?token={TOKEN}",), None)
    handler_filter.filter(record)
    assert TOKEN not in record.getMessage()


def test_file_writer_redacts(tmp_path):
    from ufo.module.basic import FileWriter

    path = tmp_path / "request.log"
    FileWriter(str(path)).write('{"server_url": "ws://localhost:5001/ws?token=' + TOKEN + '"}')
    assert TOKEN not in path.read_text(encoding="utf-8")


def test_transport_connection_error_does_not_leak_token():
    from ufo.aip.transport.websocket import WebSocketTransport

    transport = WebSocketTransport()
    with pytest.raises(ConnectionError) as info:
        asyncio.run(transport.connect(f"ws://127.0.0.1:9/ws?token={TOKEN}"))
    assert TOKEN not in str(info.value) and "token=***" in str(info.value)
