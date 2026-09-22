"""Demo: Privacy-first autonomous Telegram operation.

Features demonstrated:
1. Lockout modal (5s countdown, ESC=stop, P=pause - any hotkey configurable)
2. Real conversation navigation (clicks sidebar rows, no search box)
3. Screenshot verification of every message
4. Pattern-only learning from a conversation export (privacy-first)
5. Persistent memory + checkpoint resume

Usage:
    python demo_autonomous_telegram.py --goal-id my-goal \
        --chat "Saved Messages" --message-template "ping {n}" --count 500
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from ufo.automator.app_apis.telegram import AutonomousTelegramAgent, ExecutionConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def progress_callback(goal):
    print(f"  Progress: {goal.messages_sent} sent (failed: {goal.messages_failed})")


def error_callback(error):
    print(f"  Error: {error}")


def complete_callback(goal):
    print(f"  Goal completed: {goal.messages_sent} messages sent!")


async def main():
    parser = argparse.ArgumentParser(description="Privacy-first autonomous Telegram")
    parser.add_argument("--goal-id", required=True, help="Goal identifier")
    parser.add_argument("--chat", required=True, help="Telegram chat name")
    parser.add_argument("--message-template", required=True,
                        help="Message template with {n} placeholder")
    parser.add_argument("--count", type=int, default=100, help="Total messages")
    parser.add_argument("--learn-from", default=None,
                        help="JSON conversation export to learn patterns from")
    parser.add_argument("--no-lockout", action="store_true",
                        help="Skip the lockout modal (not recommended)")
    parser.add_argument("--countdown", type=int, default=5,
                        help="Seconds to count down before locking")
    parser.add_argument("--stop-key-label", default="ESC", help="Label for stop hotkey")
    parser.add_argument("--pause-key-label", default="P", help="Label for pause hotkey")
    args = parser.parse_args()

    config = ExecutionConfig(
        min_delay_seconds=2.0,
        max_delay_seconds=10.0,
        max_messages_per_hour=60,
        checkpoint_interval=10,
    )
    agent = AutonomousTelegramAgent(config=config)

    agent.set_progress_callback(progress_callback)
    agent.set_error_callback(error_callback)
    agent.set_complete_callback(complete_callback)

    # Optional: learn patterns from a conversation export (privacy-first)
    if args.learn_from:
        stats = agent.learn_patterns_from_conversation(args.learn_from)
        print(f"Learned abstract patterns: {len(stats.get('transitions', {}))} transitions")
        print("  (message content is never read - patterns only)")

    print(f"Starting goal '{args.goal_id}' -> {args.chat} ({args.count} msgs)")
    print(f"  Lockout: {'ON' if not args.no_lockout else 'OFF'}"
          f" | stop={args.stop_key_label} | pause={args.pause_key_label}")

    result = await agent.run_autonomous_goal(
        goal_id=args.goal_id,
        chat_name=args.chat,
        message_template=args.message_template,
        total_messages=args.count,
        lockout=not args.no_lockout,
        lockout_countdown=args.countdown,
    )

    print("\nExecution complete:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    evidence = agent.list_evidence(args.goal_id)
    print(f"  Evidence screenshots: {len(evidence)}")


if __name__ == "__main__":
    asyncio.run(main())
