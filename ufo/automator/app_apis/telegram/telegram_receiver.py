"""Telegram Receiver - UFO automator integration."""

import asyncio
from typing import Any, Dict, Optional
from ufo.automator.app_apis.basic import ReceiverBasic, CommandBasic
from ufo.automator.app_apis.telegram.telegram_gui import TelegramGUIController, ChatItem, Message
from ufo.automation.desktop import DesktopAutomation


class TelegramReceiver(ReceiverBasic):
    """Telegram Desktop receiver for UFO automator."""
    
    _command_registry: Dict[str, type] = {}
    
    def __init__(
        self, 
        app_root_name: str, 
        process_name: str,
        desktop: Optional[DesktopAutomation] = None
    ):
        super().__init__()
        self.app_root_name = app_root_name
        self.process_name = process_name
        self._controller = TelegramGUIController(desktop)
        self._initialized = False
    
    async def initialize(self) -> bool:
        """Initialize connection to Telegram Desktop."""
        if not self._initialized:
            self._initialized = await self._controller.connect()
        return self._initialized
    
    @property
    def controller(self) -> TelegramGUIController:
        return self._controller
    
    @property
    def type_name(self) -> str:
        return "TelegramGUI"
    
    def get_supported_commands(self) -> list:
        """Get list of supported command names."""
        return list(self._command_registry.keys())
    
    async def cleanup(self) -> None:
        """Clean up resources."""
        await self._controller.close()
        self._initialized = False


# ==================== Commands ====================

@TelegramReceiver.register
class SendMessageCommand(CommandBasic):
    """Send a message to a Telegram chat."""
    
    @classmethod
    def name(cls) -> str:
        return "send_message"
    
    async def execute(self) -> Dict[str, Any]:
        """Execute send message command.
        
        Params:
            text: Message text to send
            chat_name: Optional chat name to switch to first
        """
        receiver = self.receiver
        if not isinstance(receiver, TelegramReceiver):
            return {"success": False, "error": "Invalid receiver"}
        
        text = self.params.get("text", "")
        chat_name = self.params.get("chat_name")
        
        if not text:
            return {"success": False, "error": "No message text provided"}
        
        await receiver.initialize()
        success = await receiver.controller.send_message(text, chat_name)
        
        return {"success": success, "text": text, "chat": chat_name}


@TelegramReceiver.register
class OpenChatCommand(CommandBasic):
    """Open a specific chat by name."""
    
    @classmethod
    def name(cls) -> str:
        return "open_chat"
    
    async def execute(self) -> Dict[str, Any]:
        """Execute open chat command.
        
        Params:
            chat_name: Name of chat to open
        """
        receiver = self.receiver
        if not isinstance(receiver, TelegramReceiver):
            return {"success": False, "error": "Invalid receiver"}
        
        chat_name = self.params.get("chat_name", "")
        
        if not chat_name:
            return {"success": False, "error": "No chat name provided"}
        
        await receiver.initialize()
        success = await receiver.controller.open_chat(chat_name)
        
        return {"success": success, "chat": chat_name}


@TelegramReceiver.register
class SearchChatsCommand(CommandBasic):
    """Search for chats."""
    
    @classmethod
    def name(cls) -> str:
        return "search_chats"
    
    async def execute(self) -> Dict[str, Any]:
        """Execute search chats command.
        
        Params:
            query: Search query
        """
        receiver = self.receiver
        if not isinstance(receiver, TelegramReceiver):
            return {"success": False, "error": "Invalid receiver"}
        
        query = self.params.get("query", "")
        
        if not query:
            return {"success": False, "error": "No search query provided"}
        
        await receiver.initialize()
        chats = await receiver.controller.search_chats(query)
        
        return {
            "success": True, 
            "query": query, 
            "chats": [{"name": c.name} for c in chats]
        }


@TelegramReceiver.register
class ReadMessagesCommand(CommandBasic):
    """Read recent messages from current chat."""
    
    @classmethod
    def name(cls) -> str:
        return "read_messages"
    
    async def execute(self) -> Dict[str, Any]:
        """Execute read messages command.
        
        Params:
            count: Number of messages to read (default 10)
        """
        receiver = self.receiver
        if not isinstance(receiver, TelegramReceiver):
            return {"success": False, "error": "Invalid receiver"}
        
        count = self.params.get("count", 10)
        
        await receiver.initialize()
        messages = await receiver.controller.read_recent_messages(count)
        
        return {
            "success": True,
            "count": len(messages),
            "messages": [
                {"sender": m.sender, "text": m.text, "time": m.timestamp, "outgoing": m.is_outgoing}
                for m in messages
            ]
        }


@TelegramReceiver.register
class ClickElementCommand(CommandBasic):
    """Click a UI element in Telegram (via UIA or visual)."""
    
    @classmethod
    def name(cls) -> str:
        return "click_element"
    
    async def execute(self) -> Dict[str, Any]:
        """Execute click element command.
        
        Params:
            element_type: Type of element ("chat_item", "send_button", "attach", "search", etc.)
            chat_name: Optional chat name for chat_item
        """
        receiver = self.receiver
        if not isinstance(receiver, TelegramReceiver):
            return {"success": False, "error": "Invalid receiver"}
        
        element_type = self.params.get("element_type", "")
        chat_name = self.params.get("chat_name")
        
        await receiver.initialize()
        
        if element_type == "chat_item" and chat_name:
            success = await receiver.controller.open_chat(chat_name)
            return {"success": success, "element": element_type, "chat": chat_name}
        
        # Visual grounding fallback
        success = await receiver.controller.click_visual(element_type)
        return {"success": success, "element": element_type}


@TelegramReceiver.register
class TypeTextCommand(CommandBasic):
    """Type text into Telegram (message input, search, etc.)."""
    
    @classmethod
    def name(cls) -> str:
        return "type_text"
    
    async def execute(self) -> Dict[str, Any]:
        """Execute type text command.
        
        Params:
            text: Text to type
            target: Target area ("message_input", "search", "current_focus")
        """
        receiver = self.receiver
        if not isinstance(receiver, TelegramReceiver):
            return {"success": False, "error": "Invalid receiver"}
        
        text = self.params.get("text", "")
        target = self.params.get("target", "message_input")
        
        if not text:
            return {"success": False, "error": "No text provided"}
        
        await receiver.initialize()
        controller = receiver.controller
        
        if target == "search":
            await controller._type_keys_safe(controller.SHORTCUTS["search"])
            await asyncio.sleep(0.2)
            await controller._type_keys_safe(text)
        elif target == "message_input":
            await controller._type_keys_safe(controller.SHORTCUTS["focus_input"])
            await asyncio.sleep(0.2)
            await controller._type_keys_safe(text)
        else:
            # Current focus
            await controller._type_keys_safe(text)
        
        return {"success": True, "text": text, "target": target}


@TelegramReceiver.register
class PressKeyCommand(CommandBasic):
    """Press a keyboard shortcut in Telegram."""
    
    @classmethod
    def name(cls) -> str:
        return "press_key"
    
    async def execute(self) -> Dict[str, Any]:
        """Execute press key command.
        
        Params:
            key: Shortcut name from SHORTCUTS dict, or raw key sequence
        """
        receiver = self.receiver
        if not isinstance(receiver, TelegramReceiver):
            return {"success": False, "error": "Invalid receiver"}
        
        key = self.params.get("key", "")
        
        if not key:
            return {"success": False, "error": "No key provided"}
        
        await receiver.initialize()
        controller = receiver.controller
        
        # Map shortcut name to key sequence
        key_sequence = controller.SHORTCUTS.get(key, key)
        
        await controller._type_keys_safe(key_sequence)
        
        return {"success": True, "key": key, "sequence": key_sequence}


@TelegramReceiver.register
class TakeScreenshotCommand(CommandBasic):
    """Take screenshot of Telegram window."""
    
    @classmethod
    def name(cls) -> str:
        return "screenshot"
    
    async def execute(self) -> Dict[str, Any]:
        """Execute screenshot command."""
        receiver = self.receiver
        if not isinstance(receiver, TelegramReceiver):
            return {"success": False, "error": "Invalid receiver"}
        
        await receiver.initialize()
        screenshot = await receiver.controller.take_screenshot()
        
        return {"success": True, "size": len(screenshot), "format": "PNG"}


@TelegramReceiver.register
class SendMultilineMessageCommand(CommandBasic):
    """Send a multi-line message to Telegram."""
    
    @classmethod
    def name(cls) -> str:
        return "send_multiline_message"
    
    async def execute(self) -> Dict[str, Any]:
        """Execute send multiline message command.
        
        Params:
            lines: List of message lines
            chat_name: Optional chat name to switch to first
        """
        receiver = self.receiver
        if not isinstance(receiver, TelegramReceiver):
            return {"success": False, "error": "Invalid receiver"}
        
        lines = self.params.get("lines", [])
        chat_name = self.params.get("chat_name")
        
        if not lines:
            return {"success": False, "error": "No message lines provided"}
        
        await receiver.initialize()
        success = await receiver.controller.send_multiline_message(lines)
        
        return {"success": success, "lines": lines, "chat": chat_name}


# Export command classes
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