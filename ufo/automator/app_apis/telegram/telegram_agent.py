"""Autonomous Telegram agent.

Orchestrates the complete autonomous operation:
- Manages skills (learned operational knowledge)
- Executes long-running goals with checkpointing
- Learns from interactions and updates skills
- Self-recovery from failures
- Screenshot verification of every operation
- Operates without human intervention

The agent can:
1. Study a bot's behavior (learn commands, responses, protocols)
2. Execute goals (send 100s of messages) autonomously
3. Verify every action with screenshot evidence
4. Update skills with new learnings
5. Resume from checkpoints after interruptions
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ufo.automator.app_apis.telegram.telegram_gui import TelegramGUIController
from ufo.automator.app_apis.telegram.telegram_goals import GoalExecutor, ExecutionConfig
from ufo.automator.app_apis.telegram.telegram_memory import ChatState, TelegramMemory
from ufo.automator.app_apis.telegram.telegram_skill import BotSkill, SKILLS_DIR, ConversationLearner
from ufo.automator.app_apis.telegram.telegram_verifier import TelegramVerifier
from ufo.automator.app_apis.telegram.telegram_lockout import ScreenLockout
from ufo.automator.app_apis.telegram.telegram_privacy import PrivacyRedactor

logger = logging.getLogger(__name__)


class AutonomousTelegramAgent:
    """Fully autonomous Telegram agent with learning, verification, and goal execution.

    Supports a full-screen lockout mode: while active, the machine is visually
    and interactively locked (ESC=stop, P=pause) so the AI can drive Telegram
    with zero chance of human interference.
    """

    def __init__(
        self,
        controller: Optional[TelegramGUIController] = None,
        memory: Optional[TelegramMemory] = None,
        config: Optional[ExecutionConfig] = None,
        enable_verification: bool = True,
        verifier: Optional[TelegramVerifier] = None,
    ):
        """Initialize the autonomous agent.

        Args:
            controller: TelegramGUI controller for GUI automation.
            memory: Memory store for state persistence.
            config: Execution config for goal execution.
            enable_verification: Whether to verify operations with screenshots.
            verifier: Optional custom verifier instance.
        """
        self._controller = controller
        self._memory = memory or TelegramMemory()
        self._verifier = verifier or (
            TelegramVerifier(controller=controller) if enable_verification else None
        )
        self._executor = GoalExecutor(
            memory=self._memory,
            controller=controller,
            config=config,
            verifier=self._verifier,
        )
        self._current_skill: Optional[BotSkill] = None
        self._lockout: Optional[ScreenLockout] = None
        self._privacy_redactor: Optional[PrivacyRedactor] = PrivacyRedactor()

    # ==================== Skill Management ====================

    def create_skill(
        self,
        skill_name: str,
        bot_name: str,
        chat_name: str,
    ) -> BotSkill:
        """Create a new skill for a bot."""
        skill = BotSkill(
            skill_name=skill_name,
            bot_name=bot_name,
            chat_name=chat_name,
        )
        self._current_skill = skill
        skill.save()
        return skill

    def load_skill(self, skill_name: str) -> Optional[BotSkill]:
        """Load an existing skill."""
        skill = BotSkill.load(skill_name)
        if skill:
            self._current_skill = skill
        return skill

    def list_skills(self) -> List[str]:
        """List available skills."""
        return BotSkill.list_available()

    def save_current_skill(self) -> None:
        """Save the current skill to disk."""
        if self._current_skill:
            self._current_skill.save()

    # ==================== Privacy-first conversation learning ====================

    def learn_patterns_from_conversation(
        self,
        conversation_path: str,
        skill_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Learn a bot's operational PATTERNS from a Telegram export file.

        PRIVACY: the "context brain" is cut off. This reads NO message
        content - it classifies each message into an abstract shape
        (slash_command / short_phrase / numeric_list / menu / error / ...),
        learns the protocol transitions, error signature keywords, and
        recommended delays, then discards the text entirely.

        Note: this is a synchronous file-parse operation (no UI interaction).

        Args:
            conversation_path: Path to a Telegram Desktop JSON export.
            skill_name: Optional skill to create/load (defaults to bot name).

        Returns:
            Abstract statistics (never message content).
        """
        learner = ConversationLearner()

        if skill_name:
            skill = self.load_skill(skill_name)
            if skill is None:
                skill = self.create_skill(skill_name, "unknown", "")
        else:
            skill = self._current_skill or BotSkill(
                skill_name="imported-conversation",
                bot_name="unknown",
                chat_name="",
            )

        stats = learner.learn_from_file(conversation_path, skill)
        self._current_skill = skill
        self.save_current_skill()
        return stats

    # ==================== Learning ====================

    async def study_bot(
        self,
        skill: BotSkill,
        num_probe_messages: int = 3,
    ) -> Dict[str, Any]:
        """Study a bot's behavior by sending probe messages.

        PRIVACY POLICY: bot responses are NEVER read for context. Only
        responses that classify as errors (fail/error/sorry/unable/...) may
        be read and stored as recovery guidance in the skill.

        Learns:
        - Whether standard commands are acknowledged (probe success/failure)
        - Error responses ONLY (recovery behavior)

        Args:
            skill: The skill to update with learnings.
            num_probe_messages: Number of probe messages to send.

        Returns:
            Summary of learnings (no message content).
        """
        if not self._controller:
            return {"error": "No controller available"}
        if not skill.chat_name:
            return {"error": "Skill has no chat_name - cannot probe without target"}

        learnings = {
            "probes_sent": 0,
            "responses_observed": 0,
            "commands_discovered": 0,
            "errors_learned": 0,
            "messages_redacted": 0,
        }

        # Probe with common commands
        probe_commands = ["/start", "/help", "help", "hi"]
        for command in probe_commands[:num_probe_messages]:
            try:
                success = await self._controller.send_message(
                    command, skill.chat_name
                )
                if success:
                    learnings["probes_sent"] += 1
                    skill.record_command_success(command)
                    learnings["commands_discovered"] += 1
                else:
                    skill.record_command_failure(command, "send failed")
                await asyncio.sleep(3)  # Wait for bot response
            except Exception as e:
                # Exception text is operational, not message content
                skill.record_command_failure(command, str(e))
                skill.add_failure_mode(str(e), "Retry later or check bot online status")

        # Extract learned facts from controller state
        if skill.success_rate() > 0.5:
            skill.add_best_practice(
                f"Bot {skill.bot_name} responds to standard commands"
            )

        self.save_current_skill()
        return learnings

    async def learn_from_interaction(
        self,
        skill: BotSkill,
        command: str,
        success: bool,
        error: str = "",
    ) -> None:
        """Update skill with a single interaction result."""
        if success:
            skill.record_command_success(command)
        else:
            skill.record_command_failure(command, error)
            if error:
                skill.add_failure_mode(error, "Retry with backoff")
        skill.version += 1
        self.save_current_skill()

    # ==================== Goal Execution ====================

    async def execute_repeated_messages(
        self,
        goal_id: str,
        chat_name: str,
        message_template: str,
        total_messages: int,
        skill: Optional[BotSkill] = None,
    ) -> Dict[str, Any]:
        """Execute a long-running goal of sending repeated messages.

        Args:
            goal_id: Unique goal identifier.
            chat_name: Target chat name.
            message_template: Template with {n} for message number.
            total_messages: Total messages to send.
            skill: Optional skill to update during execution.

        Returns:
            Execution summary.
        """
        if not self._controller:
            await self._ensure_controller()

        # Load or create chat state
        chat_state = self._memory.load_chat_state(chat_name)
        if chat_state is None:
            chat_state = ChatState(chat_name=chat_name, op_name="repeated_messages")
            self._memory.save_chat_state(chat_state)

        # Attach skill for learning during execution
        self._current_skill = skill
        self._executor.set_controller(self._controller)

        # Execute the goal
        result = await self._executor.execute_goal(
            goal_id=goal_id,
            chat_name=chat_name,
            message_template=message_template,
            total_messages=total_messages,
            chat_state=chat_state,
        )

        # Update skill with execution results
        if skill and result["status"] == "completed":
            skill.add_best_practice(
                f"Successfully completed goal: {result['messages_sent']} messages to {chat_name}"
            )
            self.save_current_skill()

        return result

    async def _ensure_controller(self) -> None:
        """Ensure a GUI controller is available."""
        if self._controller is None:
            from ufo.automation.factory import get_desktop_automation

            desktop = get_desktop_automation("Telegram.exe")
            self._controller = TelegramGUIController(desktop)
            await self._controller.connect()
            self._executor.set_controller(self._controller)
            if self._verifier is not None:
                self._verifier.set_controller(self._controller)
            # Attach lockout (if any) to the controller for locked-mode input
            if self._lockout is not None:
                self._controller.set_lockout(self._lockout)

    # ==================== Lockout ====================

    async def acquire_lockout(
        self, message: str = "AUTOMATION IN PROGRESS", countdown: int = 5
    ) -> bool:
        """Acquire the full-screen lockout (5s countdown, ESC=stop, P=pause).

        While locked, the machine is unusable to the user - the AI can drive
        Telegram with confidence nothing human will interfere.

        Returns:
            True if lockout acquired (safe to run), False if the user pressed
            ESC during the countdown or the overlay failed to start.
        """
        if self._lockout is None:
            self._lockout = ScreenLockout(
                on_stop=self.cancel,
                on_pause=self._on_lockout_pause,
            )
        if self._controller is not None:
            self._controller.set_lockout(self._lockout)
        acquired = await self._lockout.acquire(message=message, countdown=countdown)
        if acquired and self._controller is not None:
            self._controller.set_lockout(self._lockout)
        return acquired

    async def release_lockout(self) -> None:
        """Release the lockout and return control to the user."""
        if self._lockout is not None:
            await self._lockout.release()
            if self._controller is not None:
                self._controller.set_lockout(None)

    def _on_lockout_pause(self, paused: bool) -> None:
        """Handle user pressing P on the lockout overlay."""
        if paused:
            self._executor.pause()
            logger.info("Lockout: user paused automation")
        else:
            self._executor.resume()
            logger.info("Lockout: user resumed automation")

    @property
    def is_locked(self) -> bool:
        return self._lockout is not None and self._lockout.is_locked

    # ==================== Autonomous Operation ====================

    async def run_autonomous_goal(
        self,
        goal_id: str,
        chat_name: str,
        message_template: str,
        total_messages: int,
        skill_name: Optional[str] = None,
        lockout: bool = False,
        lockout_countdown: int = 5,
    ) -> Dict[str, Any]:
        """Run a goal fully autonomously without human intervention.

        Handles:
        1. Skill loading/creation
        2. Controller connection
        3. Lockout (optional): full-screen overlay + 5s countdown, machine
           locked to the user (ESC=stop, P=pause) while the AI works
        4. Goal resumption from checkpoints
        5. Error recovery
        6. Skill updating
        7. Verification with screenshots

        Args:
            goal_id: Goal identifier.
            chat_name: Target chat.
            message_template: Message template with {n}.
            total_messages: Total messages to send.
            skill_name: Optional skill name to load.
            lockout: Acquire the full-screen lockout first (recommended).
            lockout_countdown: Seconds to count down before locking.

        Returns:
            Complete execution summary. If the user pressed ESC during
            countdown, returns {"status": "cancelled", ...}.
        """
        # Load or create skill
        if skill_name:
            skill = self.load_skill(skill_name)
            if skill is None:
                skill = self.create_skill(skill_name, "unknown", chat_name)
        else:
            skill = None

        # Connect controller if needed
        if not self._controller or not self._controller.is_connected:
            await self._ensure_controller()

        # Acquire lockout (optional but recommended for full control)
        locked = False
        if lockout:
            locked = await self.acquire_lockout(countdown=lockout_countdown)
            if not locked:
                return {
                    "goal_id": goal_id,
                    "status": "cancelled",
                    "reason": "User pressed ESC during countdown - automation aborted",
                    "messages_sent": 0,
                    "messages_failed": 0,
                    "chat": chat_name,
                }

        try:
            # Only safe to proceed if we own the machine (locked) or if the
            # user has agreed to no-lockout mode (foreground guard still active)
            # Live progress on the lockout card while running
            if locked and self._lockout is not None:
                user_progress = self._executor._on_progress

                def _live_progress(goal):
                    try:
                        self._lockout.update_status(
                            f"Sent {goal.messages_sent} messages "
                            f"(failed: {goal.messages_failed})"
                        )
                    except Exception:
                        pass
                    if user_progress:
                        try:
                            user_progress(goal)
                        except Exception:
                            pass

                self._executor.set_progress_callback(_live_progress)

            result = await self.execute_repeated_messages(
                goal_id=goal_id,
                chat_name=chat_name,
                message_template=message_template,
                total_messages=total_messages,
                skill=skill,
            )

            # If user pressed ESC mid-run, mark cancelled
            if locked and self._lockout is not None and self._lockout.stopped:
                result["status"] = "cancelled"
                result["reason"] = "User pressed ESC - automation stopped by human"

            # Save final skill state
            self.save_current_skill()
            return result
        finally:
            # ALWAYS release the lockout when done/aborted - even if it was
            # acquired but acquisition returned False (user opted out of the
            # countdown), so the machine is never left locked.
            if self._lockout is not None:
                await self.release_lockout()

    def pause(self) -> None:
        """Pause autonomous execution."""
        self._executor.pause()

    def resume(self) -> None:
        """Resume autonomous execution."""
        self._executor.resume()

    def cancel(self) -> None:
        """Cancel autonomous execution."""
        self._executor.cancel()

    @property
    def is_running(self) -> bool:
        return self._executor.is_running

    @property
    def current_skill(self) -> Optional[BotSkill]:
        return self._current_skill

    def set_progress_callback(self, callback) -> None:
        """Set callback for progress updates."""
        self._executor.set_progress_callback(callback)

    def set_error_callback(self, callback) -> None:
        """Set callback for errors."""
        self._executor.set_error_callback(callback)

    def set_complete_callback(self, callback) -> None:
        """Set callback for goal completion."""
        self._executor.set_complete_callback(callback)

    # ==================== Verification ====================

    @property
    def verifier(self) -> Optional[TelegramVerifier]:
        """Get the verifier for screenshot-based checks."""
        return self._verifier

    async def take_screenshot(
        self, label: str = "", goal_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Take a screenshot at any moment for verification.

        Args:
            label: Descriptive label for the screenshot.
            goal_id: Optional goal for evidence organization.

        Returns:
            Dict with screenshot info and saved path.
        """
        if self._verifier is None:
            return {"success": False, "error": "Verification disabled"}
        # Ensure controller is available first
        if self._controller is None or not self._controller.is_connected:
            await self._ensure_controller()
        screenshot, path = await self._verifier.capture_screenshot(
            label=label, goal_id=goal_id
        )
        if screenshot is None:
            return {"success": False, "error": "Screenshot capture failed"}
        return {
            "success": True,
            "size": len(screenshot),
            "saved_path": str(path) if path else None,
            "label": label,
            "goal_id": goal_id,
        }

    def list_evidence(self, goal_id: Optional[str] = None) -> List[Path]:
        """List verification evidence files.

        Args:
            goal_id: Optional goal filter.

        Returns:
            List of evidence file paths.
        """
        if self._verifier is None:
            return []
        return self._verifier.list_evidence(goal_id)

    async def verify_current_state(self) -> Dict[str, Any]:
        """Verify current state of the Telegram window.

        Returns:
            Verification result dict.
        """
        if self._verifier is None:
            return {"success": False, "error": "Verification disabled"}
        # Ensure controller is available first
        if self._controller is None or not self._controller.is_connected:
            await self._ensure_controller()
        result = await self._verifier.verify_window_present()
        return {
            "success": result.success,
            "reasoning": result.reasoning,
        }
