"""Telegram Desktop GUI automation for UFO.

Provides hybrid automation combining:
- UIA for chat list navigation (works reliably)
- Keyboard shortcuts for message input/sending (bypasses missing UIA controls)  
- Visual grounding fallback for element detection
- Autonomous goal execution with persistent memory
- Skill learning and saving for bot operations
"""

from ufo.automator.app_apis.telegram.telegram_gui import (
    TelegramGUIController,
    ChatItem,
    Message,
)
from ufo.automator.app_apis.telegram.telegram_receiver import (
    TelegramReceiver,
)
from ufo.automator.app_apis.telegram.telegram_memory import (
    TelegramMemory,
    ChatState,
    GoalState,
)
from ufo.automator.app_apis.telegram.telegram_goals import (
    GoalExecutor,
    ExecutionConfig,
)
from ufo.automator.app_apis.telegram.telegram_skill import (
    BotSkill,
    InteractionPattern,
    FailureMode,
    ConversationLearner,
    load_bot_skill_with_conversation,
)
from ufo.automator.app_apis.telegram.telegram_agent import (
    AutonomousTelegramAgent,
)
from ufo.automator.app_apis.telegram.telegram_verifier import (
    TelegramVerifier,
    VerificationResult,
)
from ufo.automator.app_apis.telegram.telegram_lockout import (
    ScreenLockout,
)
from ufo.automator.app_apis.telegram.telegram_privacy import (
    PrivacyRedactor,
    RedactionResult,
    ERROR_KEYWORDS,
)

__all__ = [
    # GUI
    "TelegramGUIController",
    "ChatItem",
    "Message",
    "TelegramReceiver",
    # Memory
    "TelegramMemory",
    "ChatState",
    "GoalState",
    # Goals
    "GoalExecutor",
    "ExecutionConfig",
    # Skills
    "BotSkill",
    "InteractionPattern",
    "FailureMode",
    # Agent
    "AutonomousTelegramAgent",
    # Verification
    "TelegramVerifier",
    "VerificationResult",
    # Lockout
    "ScreenLockout",
    # Privacy
    "PrivacyRedactor",
    "RedactionResult",
    "ERROR_KEYWORDS",
    # Conversation learning (privacy-first)
    "ConversationLearner",
    "load_bot_skill_with_conversation",
]
