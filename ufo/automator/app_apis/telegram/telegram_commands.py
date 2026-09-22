"""Telegram Commands - exported for UFO automator."""

from ufo.automator.app_apis.telegram.telegram_receiver import (
    SendMessageCommand,
    OpenChatCommand,
    SearchChatsCommand,
    ReadMessagesCommand,
    ClickElementCommand,
    TypeTextCommand,
    PressKeyCommand,
    TakeScreenshotCommand,
    SendMultilineMessageCommand,
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