"""Autonomous goal execution engine for Telegram automaton.

Provides:
- Goal decomposition into milestone steps
- Autonomous execution loop with error recovery
- Rate limiting for long-running tasks
- Progress checkpointing and resume capability
- Per-message verification with screenshots
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ufo.automator.app_apis.telegram.telegram_memory import (
    ChatState,
    GoalState,
    TelegramMemory,
)

logger = logging.getLogger(__name__)


@dataclass
class ExecutionConfig:
    """Configuration for autonomous execution."""
    # Rate limiting
    min_delay_seconds: float = 2.0
    max_delay_seconds: float = 10.0
    max_messages_per_hour: int = 60
    # Error recovery
    max_retries_per_action: int = 3
    retry_backoff_seconds: float = 5.0
    cooldown_after_failure_seconds: float = 30.0
    # Checkpointing
    checkpoint_interval: int = 10  # messages between checkpoints
    # Goal execution
    max_cycles: int = 0  # 0 = unlimited


class GoalExecutor:
    """Executes long-running goals against Telegram bots autonomously."""

    def __init__(
        self,
        memory: TelegramMemory,
        controller=None,
        config: Optional[ExecutionConfig] = None,
        verifier=None,
    ):
        """Initialize the goal executor.

        Args:
            memory: Persistent memory store for state and checkpoints.
            controller: Optional TelegramGUIController for sending messages.
            config: Execution configuration.
            verifier: Optional TelegramVerifier for screenshot verification.
        """
        self._memory = memory
        self._controller = controller
        self._config = config or ExecutionConfig()
        self._verifier = verifier
        if self._verifier is not None and self._controller is not None:
            self._verifier.set_controller(controller)
        self._running = False
        self._paused = False
        self._cancelled = False
        self._current_goal: Optional[GoalState] = None
        self._message_timestamps: List[float] = []
        # Callbacks
        self._on_progress: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        self._on_goal_complete: Optional[Callable] = None
        # Verification stats
        self._verified_sends = 0
        self._failed_verifications = 0

    # ==================== Goal Management ====================

    def create_goal(self, goal_id: str, description: str, milestones: List[str]) -> GoalState:
        """Create a new goal with milestones.

        Args:
            goal_id: Unique goal identifier.
            description: Human-readable goal description.
            milestones: List of milestone descriptions.

        Returns:
            The created GoalState.
        """
        milestone_dicts = [
            {
                "index": i,
                "description": m,
                "status": "pending",
                "completed_at": None,
            }
            for i, m in enumerate(milestones)
        ]
        goal = GoalState(
            goal_id=goal_id,
            description=description,
            status="pending",
            current_milestone=milestones[0] if milestones else "",
            milestones=milestone_dicts,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        self._memory.save_goal(goal)
        return goal

    def load_goal(self, goal_id: str) -> Optional[GoalState]:
        """Load a goal from memory."""
        return self._memory.load_goal(goal_id)

    def list_goals(self) -> Dict[str, GoalState]:
        """List all goals in memory."""
        return self._memory.load_all_goals()

    # ==================== Rate Limiting ====================

    async def _check_rate_limit(self) -> None:
        """Enforce rate limits by sleeping if needed (stop-interruptible)."""
        now = datetime.now().timestamp()
        # Remove timestamps older than 1 hour
        self._message_timestamps = [
            ts for ts in self._message_timestamps if now - ts < 3600
        ]
        if len(self._message_timestamps) >= self._config.max_messages_per_hour:
            oldest = self._message_timestamps[0]
            wait = oldest + 3600 - now
            if wait > 0:
                logger.info(f"Rate limit reached, sleeping {wait:.0f}s")
                if not await self._sleep_interruptible(wait):
                    return  # cancelled
                self._message_timestamps = [
                    ts for ts in self._message_timestamps if now + wait - ts < 3600
                ]

    async def _sleep_interruptible(self, seconds: float) -> bool:
        """Sleep for ``seconds``, waking early if STOP (cancel) is requested.

        Returns False immediately when cancelled - making ESC stop respond
        within ~0.2s even during long waits. Returns True when the full
        duration elapsed without cancellation.
        """
        end = time.time() + seconds
        while True:
            if self._cancelled:
                return False
            remaining = end - time.time()
            if remaining <= 0:
                return not self._cancelled
            await asyncio.sleep(min(0.2, remaining))

    async def _random_delay(self) -> None:
        """Apply randomized delay between messages (stop-interruptible)."""
        delay = random.uniform(
            self._config.min_delay_seconds, self._config.max_delay_seconds
        )
        await self._sleep_interruptible(delay)

    # ==================== Autonomous Execution ====================

    async def execute_goal(
        self,
        goal_id: str,
        chat_name: str,
        message_template: str,
        total_messages: int,
        chat_state: Optional[ChatState] = None,
    ) -> Dict[str, Any]:
        """Execute a goal autonomously.

        Args:
            goal_id: Goal identifier (creates if doesn't exist).
            chat_name: Target chat for messages.
            message_template: Template with {n} placeholder for counter.
            total_messages: Total number of messages to send.
            chat_state: Optional ChatState to track.

        Returns:
            Summary dict with results.
        """
        goal = self.load_goal(goal_id)
        if goal is None:
            goal = self.create_goal(
                goal_id,
                f"Send {total_messages} messages to {chat_name}",
                [
                    f"Initialize chat {chat_name}",
                    f"Send {total_messages} messages",
                    "Complete goal and archive results",
                ],
            )

        # Resume from checkpoint
        starting_index = goal.progress.get("messages_sent", 0) + 1
        if starting_index > 1:
            logger.info(f"Resuming goal {goal_id} from message {starting_index}")

        goal.status = "running"
        self._memory.save_goal(goal)

        self._running = True
        self._cancelled = False
        self._paused = False

        try:
            for n in range(starting_index, total_messages + 1):
                if self._cancelled:
                    goal.status = "cancelled"
                    goal.last_error = "Stopped by human (ESC) - automation aborted"
                    self._memory.save_goal(goal)
                    break

                while self._paused:
                    if self._cancelled:
                        break
                    await asyncio.sleep(0.2)
                if self._cancelled:
                    goal.status = "cancelled"
                    goal.last_error = "Stopped by human (ESC) - automation aborted"
                    self._memory.save_goal(goal)
                    break

                # Rate limit check (stop-interruptible)
                if self._cancelled:
                    break
                await self._check_rate_limit()
                if self._cancelled:
                    break

                message_text = message_template.format(n=n, idx=n - 1)

                # Pre-send verification (screenshot of current state)
                if self._verifier is not None:
                    await self._verifier.verify_before_send(n, goal_id)

                success = await self._send_with_retry(
                    chat_name, message_text, chat_state
                )

                # Post-send verification (screenshot confirming send)
                if self._verifier is not None:
                    verify_result = await self._verifier.verify_after_send(
                        n, message_text, goal_id
                    )
                    if verify_result.success:
                        self._verified_sends += 1
                    else:
                        self._failed_verifications += 1
                        logger.warning(
                            f"Message {n} verification issue: {verify_result.reasoning}"
                        )

                if success:
                    goal.messages_sent = n
                    self._message_timestamps.append(datetime.now().timestamp())
                    if chat_state:
                        chat_state.completed_cycles += 1
                        self._memory.save_chat_state(chat_state)
                else:
                    goal.messages_failed += 1
                    goal.last_error = f"Failed to send message {n}"
                    # Capture failure evidence
                    if self._verifier is not None:
                        await self._verifier.capture_screenshot(
                            label=f"FAILURE_msg_{n}",
                            goal_id=goal_id,
                        )
                    if goal.messages_failed > 3:
                        goal.status = "failed"
                        self._memory.save_goal(goal)
                        break

                # Checkpoint
                if n % self._config.checkpoint_interval == 0:
                    goal.progress["messages_sent"] = n
                    goal.progress["verified_sends"] = self._verified_sends
                    goal.progress["failed_verifications"] = self._failed_verifications
                    self._memory.save_goal(goal)
                    logger.info(f"Checkpoint: {n}/{total_messages} messages sent")
                    # Progress verification screenshot
                    if self._verifier is not None:
                        await self._verifier.verify_goal_progress(goal_id, n)
                    if self._on_progress:
                        self._on_progress(goal)

                # Random delay between messages
                await self._random_delay()

            if goal.status not in ("failed", "paused", "cancelled"):
                goal.status = "completed"
                goal.progress["messages_sent"] = goal.messages_sent
                goal.progress["verified_sends"] = self._verified_sends
                goal.progress["failed_verifications"] = self._failed_verifications
                self._memory.save_goal(goal)
                # Final verification screenshot
                if self._verifier is not None:
                    await self._verifier.capture_screenshot(
                        label="goal_completed",
                        goal_id=goal_id,
                    )
                for milestone in goal.milestones:
                    milestone["status"] = "completed"
                    milestone["completed_at"] = datetime.now().isoformat()
                self._memory.save_goal(goal)
                if self._on_goal_complete:
                    self._on_goal_complete(goal)

            return {
                "goal_id": goal_id,
                "status": goal.status,
                "messages_sent": goal.messages_sent,
                "messages_failed": goal.messages_failed,
                "verified_sends": self._verified_sends,
                "failed_verifications": self._failed_verifications,
                "chat": chat_name,
            }

        except Exception as e:
            goal.status = "failed"
            goal.last_error = str(e)
            self._memory.save_goal(goal)
            if self._on_error:
                self._on_error(e)
            raise
        finally:
            self._running = False

    async def _send_with_retry(
        self, chat_name: str, message: str, chat_state: Optional[ChatState] = None
    ) -> bool:
        """Send a message with retry logic (stop-interruptible).

        Checks for STOP between every attempt and during backoff so the
        ESC hotkey halts the current send within ~0.2s.
        """
        if self._controller is None:
            logger.error("No controller available for message sending")
            return False

        for attempt in range(self._config.max_retries_per_action):
            if self._cancelled:
                return False
            try:
                success = await self._controller.send_message(message, chat_name)
                if success:
                    if chat_state:
                        chat_state.failures = 0
                    return True
                else:
                    logger.warning(
                        f"Message send failed (attempt {attempt + 1})"
                    )
            except Exception as e:
                logger.warning(f"Message exception (attempt {attempt + 1}): {e}")

            if attempt < self._config.max_retries_per_action - 1:
                backoff = self._config.retry_backoff_seconds * (2 ** attempt)
                logger.info(f"Backing off {backoff}s before retry")
                # Interruptible backoff - ESC aborts immediately
                if not await self._sleep_interruptible(backoff):
                    return False
                # Try to reconnect (unless stopping)
                if self._cancelled:
                    return False
                if self._controller and not self._controller.is_connected:
                    await self._controller.connect()

        if chat_state:
            chat_state.failures += 1
            self._memory.save_chat_state(chat_state)
        return False

    # ==================== Control ====================

    def stop(self) -> None:
        """Immediately stop execution (used by STOP hotkey)."""
        self.cancel()

    def set_controller(self, controller) -> None:
        """Set the Telegram GUI controller."""
        self._controller = controller
        if self._verifier is not None:
            self._verifier.set_controller(controller)

    def set_verifier(self, verifier) -> None:
        """Set the Telegram verifier for screenshot-based verification."""
        self._verifier = verifier
        if verifier is not None and self._controller is not None:
            verifier.set_controller(self._controller)

    def set_progress_callback(self, callback: Callable) -> None:
        """Set callback for progress updates."""
        self._on_progress = callback

    def set_error_callback(self, callback: Callable) -> None:
        """Set callback for error notifications."""
        self._on_error = callback

    def set_complete_callback(self, callback: Callable) -> None:
        """Set callback for goal completion."""
        self._on_goal_complete = callback

    def pause(self) -> None:
        """Pause autonomous execution."""
        self._paused = True
        logger.info("Goal execution paused")

    def resume(self) -> None:
        """Resume autonomous execution."""
        self._paused = False
        logger.info("Goal execution resumed")

    def cancel(self) -> None:
        """Cancel autonomous execution."""
        self._cancelled = True
        logger.info("Goal execution cancelled")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused
