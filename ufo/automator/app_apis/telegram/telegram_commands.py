"""Telegram Commands - exported for UFO automator."""

from ufo.automator.app_apis.telegram.telegram_receiver import (
    ClickElementCommand,
    OpenChatCommand,
    PressKeyCommand,
    ReadMessagesCommand,
    SearchChatsCommand,
    SendMessageCommand,
    SendMultilineMessageCommand,
    TakeScreenshotCommand,
    TypeTextCommand,
)

__all__ = [
    "SendMessageCommand",
    "OpenChatCommand",
    "SearchChatsCommand",
    "ReadMessagesCommand",
    "ClickElementCommand",
    "TypeTextCommand",
    "PressKeyCommand",
    "TakeScreenshotCommand",
    "SendMultilineMessageCommand",
]
