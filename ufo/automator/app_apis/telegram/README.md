# Autonomous Telegram Automation - Privacy-First Edition

Long-running autonomous Telegram operations with:
- **Privacy-first message handling** (context brain cut off)
- Skill learning from bot patterns (never message content)
- Full-screen modal lockout with configurable hotkeys
- Screenshot verification of every operation
- Checkpointing + resume for 100s of repeated messages

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│              AutonomousTelegramAgent                       │
│  Orchestrates skill + goal + verification + privacy       │
├──────────────────────────────────────────────────────────┤
│  ┌───────────────┐  ┌──────────────────────────────────┐  │
│  │ GoalExecutor   │  │ TelegramMemory (SQLite)          │  │
│  │ rate limit     │  │ chat/goal checkpoints            │  │
│  │ interruptible  │  │ resume after restarts            │  │
│  └───────────────┘  └──────────────────────────────────┘  │
│  ┌───────────────┐  ┌──────────────────────────────────┐  │
│  │ BotSkill       │  │ TelegramGUIController            │  │
│  │ patterns only  │  │ title-independent connect        │  │
│  │ JSON saved     │  │ REAL chat-row clicks (no search) │  │
│  └───────────────┘  └──────────────────────────────────┘  │
│  ┌───────────────┐  ┌──────────────────────────────────┐  │
│  │ TelegramVerifier│ │ ScreenLockout (modal + hotkeys)   │  │
│  │ screenshots    │ │ ESC/P (or any key combo)          │  │
│  └───────────────┘  └──────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐    │
│  │ PrivacyRedactor  ←  EVERY message read passes here  │    │
│  └────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

## 🔒 Privacy Architecture (Cut-Off Context Brain)

Every message read goes through `PrivacyRedactor`:

| Message Type | Handling |
|--------------|----------|
| Normal content | **NEVER read/stored** - replaced with `[REDACTED]` |
| Chat previews | Always redacted (chat name metadata only) |
| Verification logs | `message_text` NEVER logged |
| Skill storage | Only abstract patterns (shapes/types/transitions) |
| **Error messages** | May be read - only to learn recovery behavior |

**Error-trigger keywords** (57+ incl. English + Chinese):
`fail, error, failed, sorry, unable, cannot, denied, declined, timeout, retry, blocked, invalid, insufficient, wrong, incorrect, unsupported, not found, problem, issue, broken, rate limit, sold out, no results, please try again, 失败, 错误, 无法, 不能, 拒绝, 重试, 超时, 余额不足, 未找到, 无效, 耐心等待, 卖完...`

### Pattern-Only Learning (`ConversationLearner`)

When learning from a conversation export, the learner:
1. Classifies each message into an **abstract shape** (content discarded):
   - User: `slash_command | short_phrase | numeric_list | single_number | multiline_text`
   - Bot: `menu | input_prompt | content_list | error | rate_limit | plain_response`
2. Learns the **protocol graph** (transitions):
   `menu → short_phrase → input_prompt → numeric_list → error → ...`
3. Records **error signature keywords** only (never the sentence)
4. Records **recommended delays** after rate-limit responses
5. **Retains zero message text** - verified by test: `"Check Status"`, `"12345"`, `"status summary"` all absent from the saved skill

## 🔑 Configurable Lockout Hotkeys

Any key/virtual-key combo can be used (defaults ESC/P):

```python
from ufo.automator.app_apis.telegram import ScreenLockout

lockout = ScreenLockout(
    stop_key=0x70,            # F1 = Stop
    pause_key=0x71,           # F2 = Pause/Resume
    stop_key_label="F1",
    pause_key_label="F2",
)
# ESC 0x1B, P 0x50, F1 0x70, F2 0x71, Ctrl+... via GetAsyncKeyState
```

The lockout is:
- **Modal**: small centered card, rest of screen slightly dimmed (automation stays visible)
- **Input-blocking**: clicks/keys are swallowed; ESC/P work globally via polling
- **Stop interrupts instantly**: executor checks cancellation every ~0.2s (even mid-retry/backoff)

## 🎯 Real Conversation Navigation (no search box)

Chats open by **clicking the real sidebar row** (like a human):
1. Resolve the sidebar list (`Dialogs::InnerWidget`) fresh each time
2. Walk visible rows; match chat name as first token
3. `click_input()` on the real row
4. Scroll and re-search if not visible
5. Verify the click landed (window-state screenshot hash diff)
6. Ctrl+F search only as a last fallback

**Title-independent connect**: Telegram retitles its window with the active
chat name (e.g. `whale cc 3 - (3631)`), so the window is resolved by
**process name + class**, never by title.

## Usage

### Autonomous goal with lockout + verification

```python
import asyncio
from ufo.automator.app_apis.telegram import AutonomousTelegramAgent, ExecutionConfig

async def main():
    agent = AutonomousTelegramAgent(config=ExecutionConfig(
        min_delay_seconds=3.0,
        max_delay_seconds=15.0,
        max_messages_per_hour=40,
        checkpoint_interval=20,
    ))

    result = await agent.run_autonomous_goal(
        goal_id="daily-op-2026-09-23",
        chat_name="Saved Messages",
        message_template="daily check {n}",
        total_messages=500,
        lockout=True,          # modal + hotkeys
        lockout_countdown=5,   # 5s warning before start
    )
    print(result)

asyncio.run(main())
```

### Pattern learning from a conversation export (privacy-first)

```python
agent = AutonomousTelegramAgent()
stats = agent.learn_patterns_from_conversation(
    "telegram_export.json",
    skill_name="my-bot-patterns",
)
print(stats)  # abstract shapes/transitions only - no content
```

## Storage Layout

```
ufo_skill_state/
├── telegram_memory.db          # SQLite: chats, goals, checkpoints
├── evidence/goal_<id>/         # verification screenshots
└── skills/<skill>.json         # patterns only - never message content
```

## Safety Guarantees

1. **Privacy**: message content is never read/stored/learned (errors excepted)
2. **Input safety**: never types unless Telegram owns foreground (or lockout active)
3. **Instant stop**: interruptible waits + global hotkey polling (~0.2s response)
4. **Checkpointing**: resume after any crash/stop without losing progress
5. **Rate limits**: configurable hourly caps + randomized delays
6. **Visibility**: automation runs visibly on screen; user watches live progress
