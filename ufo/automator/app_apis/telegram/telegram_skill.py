"""Telegram bot skill system.

Captures complete operational knowledge of a Telegram bot:
- Bot identity and commands
- Message formats and protocols
- Learned interaction patterns
- Success/failure history
- Extraction patterns for bot responses

Skills are stored as JSON files and can be loaded for future autonomous
operation.

Skill file structure (JSON):
{
    "skill_name": string,
    "bot_name": string,
    "chat_name": string,
    "created_at": ISO timestamp,
    "version": int,
    "bot_commands": [string],
    "command_usage": {command_name: usage_count},
    "interaction_patterns": [
        {
            "pattern": string (command),
            "expected_response": string (description),
            "success_count": int,
            "failure_count": int,
        }
    ],
    "extraction_patterns": [string regex patterns],
    "learned_facts": {key: value},
    "failure_modes": [
        {
            "error": string (description),
            "recovery": string (action to recover),
            "frequency": int,
        }
    ],
    "best_practices": [string],
}
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ufo.automator.app_apis.telegram.telegram_privacy import PrivacyRedactor

logger = logging.getLogger(__name__)

# Default location for skills directory
SKILLS_DIR = Path("ufo_skill_state/skills")


@dataclass
class InteractionPattern:
    """Learned pattern for interacting with a bot."""
    pattern: str                    # The command/message pattern
    expected_response: str = ""     # Expected bot response description
    success_count: int = 0
    failure_count: int = 0
    last_used: str = ""
    notes: str = ""


@dataclass
class FailureMode:
    """Known failure mode and recovery strategy."""
    error: str
    recovery: str
    frequency: int = 0


@dataclass
class BotSkill:
    """Complete operational knowledge of a Telegram bot."""
    skill_name: str
    bot_name: str
    chat_name: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    version: int = 1
    bot_commands: List[str] = field(default_factory=list)
    command_usage: Dict[str, int] = field(default_factory=dict)
    interaction_patterns: List[InteractionPattern] = field(default_factory=list)
    extraction_patterns: List[str] = field(default_factory=list)
    learned_facts: Dict[str, Any] = field(default_factory=dict)
    failure_modes: List[FailureMode] = field(default_factory=list)
    best_practices: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert skill to dictionary for serialization."""
        return {
            "skill_name": self.skill_name,
            "bot_name": self.bot_name,
            "chat_name": self.chat_name,
            "created_at": self.created_at,
            "version": self.version,
            "bot_commands": self.bot_commands,
            "command_usage": self.command_usage,
            "interaction_patterns": [
                {
                    "pattern": p.pattern,
                    "expected_response": p.expected_response,
                    "success_count": p.success_count,
                    "failure_count": p.failure_count,
                    "last_used": p.last_used,
                    "notes": p.notes,
                }
                for p in self.interaction_patterns
            ],
            "extraction_patterns": self.extraction_patterns,
            "learned_facts": self.learned_facts,
            "failure_modes": [
                {
                    "error": f.error,
                    "recovery": f.recovery,
                    "frequency": f.frequency,
                }
                for f in self.failure_modes
            ],
            "best_practices": self.best_practices,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotSkill":
        """Create skill from dictionary."""
        skill = cls(
            skill_name=data.get("skill_name", ""),
            bot_name=data.get("bot_name", ""),
            chat_name=data.get("chat_name", ""),
            created_at=data.get("created_at", ""),
            version=data.get("version", 1),
            bot_commands=data.get("bot_commands", []),
            command_usage=data.get("command_usage", {}),
            extraction_patterns=data.get("extraction_patterns", []),
            learned_facts=data.get("learned_facts", {}),
            best_practices=data.get("best_practices", []),
        )
        skill.interaction_patterns = [
            InteractionPattern(
                pattern=p["pattern"],
                expected_response=p.get("expected_response", ""),
                success_count=p.get("success_count", 0),
                failure_count=p.get("failure_count", 0),
                last_used=p.get("last_used", ""),
                notes=p.get("notes", ""),
            )
            for p in data.get("interaction_patterns", [])
        ]
        skill.failure_modes = [
            FailureMode(
                error=f["error"],
                recovery=f.get("recovery", ""),
                frequency=f.get("frequency", 0),
            )
            for f in data.get("failure_modes", [])
        ]
        return skill

    # ==================== Learning ====================

    def success_rate(self) -> float:
        """Calculate overall success rate of interactions."""
        total_success = sum(p.success_count for p in self.interaction_patterns)
        total_all = sum(p.success_count + p.failure_count for p in self.interaction_patterns)
        if total_all == 0:
            return 0.0
        return total_success / total_all

    def record_command_success(self, command: str) -> None:
        """Record a successful command usage."""
        self.command_usage[command] = self.command_usage.get(command, 0) + 1
        # Update or create interaction pattern
        for pattern in self.interaction_patterns:
            if pattern.pattern == command:
                pattern.success_count += 1
                pattern.last_used = datetime.now().isoformat()
                return
        self.interaction_patterns.append(
            InteractionPattern(
                pattern=command,
                success_count=1,
                last_used=datetime.now().isoformat(),
            )
        )

    def record_command_failure(self, command: str, error: str) -> None:
        """Record a failed command with error."""
        for pattern in self.interaction_patterns:
            if pattern.pattern == command:
                pattern.failure_count += 1
                pattern.notes = f"Last error: {error}"
                return
        self.interaction_patterns.append(
            InteractionPattern(
                pattern=command,
                failure_count=1,
                notes=f"Last error: {error}",
            )
        )

    def add_failure_mode(self, error: str, recovery: str) -> None:
        """Add or update a failure mode with recovery strategy."""
        for mode in self.failure_modes:
            if mode.error == error:
                mode.recovery = recovery
                mode.frequency += 1
                return
        self.failure_modes.append(FailureMode(error=error, recovery=recovery))

    def add_fact(self, key: str, value: Any) -> None:
        """Store a learned fact about the bot."""
        self.learned_facts[key] = value

    def add_best_practice(self, practice: str) -> None:
        """Add a best practice note."""
        if practice not in self.best_practices:
            self.best_practices.append(practice)

    def add_extraction_pattern(self, pattern: str) -> None:
        """Add a regex pattern for extracting data from bot responses."""
        if pattern not in self.extraction_patterns:
            self.extraction_patterns.append(pattern)

    # ==================== Persistence ====================

    def save(self, skills_dir: Path = SKILLS_DIR) -> Path:
        """Save skill to disk as JSON.

        Returns:
            Path to saved file.
        """
        skills_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{self.skill_name}.json"
        filepath = skills_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info(f"Skill saved to {filepath}")
        return filepath

    @classmethod
    def load(cls, skill_name: str, skills_dir: Path = SKILLS_DIR) -> Optional["BotSkill"]:
        """Load a skill from disk, or None if not present."""
        filepath = skills_dir / f"{skill_name}.json"
        if not filepath.exists():
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def list_available(cls, skills_dir: Path = SKILLS_DIR) -> List[str]:
        """List all available skill names."""
        if not skills_dir.exists():
            return []
        return [p.stem for p in skills_dir.glob("*.json")]

    def summary(self) -> str:
        """Generate a human-readable summary of the skill."""
        lines = [
            f"Skill: {self.skill_name} (v{self.version})",
            f"Bot: {self.bot_name} in chat '{self.chat_name}'",
            f"Created: {self.created_at}",
            f"Commands: {', '.join(self.bot_commands) if self.bot_commands else 'none learned'}",
            f"Total interactions: {sum(p.success_count + p.failure_count for p in self.interaction_patterns)}",
            f"Success rate: {sum(p.success_count for p in self.interaction_patterns)}/{sum(p.success_count + p.failure_count for p in self.interaction_patterns) if sum(p.success_count + p.failure_count for p in self.interaction_patterns) > 0 else 0}",
            f"Learned facts: {len(self.learned_facts)}",
            f"Failure modes: {len(self.failure_modes)}",
            f"Best practices: {len(self.best_practices)}",
        ]
        return "\n".join(lines)


# ==================== Conversation Import (privacy-first) ====================

# Structural navigation button labels (never message content) - allowed to be
# recorded as UI structure, everything else stays redacted.
STRUCTURAL_BUTTONS = {
    "next page", "previous", "1 / 999999", "next", "prev", "back",
    "refresh", "刷新", "下一页", "上一页", "返回",
}


def _flatten_text(text) -> str:
    """Flatten a Telegram text entity list into a plain string."""
    if isinstance(text, list):
        out = []
        for part in text:
            if isinstance(part, dict):
                out.append(part.get("text", ""))
            else:
                out.append(str(part))
        return "".join(out)
    return str(text or "")


class ConversationLearner:
    """Learns a bot's operational PATTERNS from a Telegram Desktop export.

    SAFETY/DESIGN: the "context brain" is cut off - this class NEVER stores,
    returns, or reasons about the actual content of any message.

    What it learns (patterns only):
    - Command SHAPES: slash_command | short_phrase | numeric_list | menu_choice
      (which kinds of inputs appear, and how often) - never the text itself.
    - Response TYPES: menu | input_prompt | content_list | error | rate_limit
      | file | plain - never the body.
    - Transitions: menu_choice -> input_prompt -> numeric_list -> content_list
      (the abstract protocol graph the agent should expect).
    - Error type: ONLY the matched error KEYWORD (fail/error/sold out/...) and
      a generic recovery strategy - never the full error sentence.
    - Timing/rate behavior: recommended delays between requests.

    NO message text, command text, or response body is retained in the skill
    or in any output dict.
    """

    def __init__(self, redactor: Optional[PrivacyRedactor] = None):
        self.redactor = redactor or PrivacyRedactor()

    # ==================== Public ====================

    def learn_from_file(self, path: str, skill: BotSkill) -> Dict[str, Any]:
        """Learn patterns from a Telegram Desktop JSON export. (No content reads.)"""
        import json
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}

        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict) and "messages" in data:
            messages = data["messages"]
            if data.get("name"):
                skill.bot_name = str(data["name"])
            skill.learned_facts["_chat_label"] = str(data.get("name", ""))[:60]
        elif isinstance(data, list):
            messages = data
        else:
            return {"error": "Unrecognized conversation format"}

        return self.learn_from_messages(messages, skill)

    def learn_from_messages(self, messages: List[Dict], skill: BotSkill) -> Dict[str, Any]:
        """Learn abstract patterns from a list of message dicts."""
        stats = {
            "messages_scanned": len(messages),
            "command_patterns": {},
            "response_patterns": {},
            "transitions": {},
            "error_keywords": {},
            "rate_limits": 0,
            "button_structures": 0,
        }

        from collections import Counter
        user_pattern_counter: Counter = Counter()
        bot_pattern_counter: Counter = Counter()
        transition_counter: Counter = Counter()
        error_kw_counter: Counter = Counter()

        prev_user_pattern = None
        prev_bot_pattern = None

        for m in messages:
            from_id = str(m.get("from_id", ""))
            text = _flatten_text(m.get("text", "")).strip()
            is_bot = bool(from_id and not from_id.startswith("user"))

            if not text:
                continue
            if text.startswith("["):
                # File/entity placeholder -> pattern: file_message
                if is_bot:
                    bot_pattern_counter["file_message"] += 1
                continue

            if is_bot:
                pattern, error_kw = self._bot_pattern(text)
                bot_pattern_counter[pattern] += 1
                if error_kw:
                    error_kw_counter[error_kw] += 1
                if pattern == "rate_limit":
                    stats["rate_limits"] += 1
                    self._apply_delay_learning(text, skill)
                buttons = m.get("inline_bot_buttons") or m.get("reply_markup")
                if buttons:
                    stats["button_structures"] += 1
                if prev_user_pattern:
                    key = f"{prev_user_pattern} -> {pattern}"
                    transition_counter[key] += 1
                prev_bot_pattern = pattern
            else:
                pattern = self._user_pattern(text)
                user_pattern_counter[pattern] += 1
                if prev_bot_pattern:
                    key = f"{prev_bot_pattern} -> {pattern}"
                    transition_counter[key] += 1
                prev_user_pattern = pattern

        # Store ONLY abstract patterns/transitions - no content whatsoever
        skill.learned_facts["protocol"] = {
            "user_command_shapes": dict(user_pattern_counter),
            "bot_response_types": dict(bot_pattern_counter),
            "transitions": dict(transition_counter.most_common(40)),
            "error_signature_keywords": dict(error_kw_counter),
        }
        # Best practices: protocol shape notes (no content)
        for pattern, count in user_pattern_counter.most_common():
            if count >= 3:
                skill.add_best_practice(f"Frequent user input shape: {pattern} (x{count})")
        delay = skill.learned_facts.get("recommended_delay_between_requests_seconds")
        if delay:
            skill.add_best_practice(f"Respect ~{delay}s wait after rate-limit responses")

        stats["command_patterns"] = dict(user_pattern_counter)
        stats["response_patterns"] = dict(bot_pattern_counter)
        stats["transitions"] = dict(transition_counter.most_common(20))
        stats["error_keywords"] = dict(error_kw_counter)

        skill.version += 1
        return stats

    # ==================== Pattern classifiers (text -> shape only) ====================

    def _user_pattern(self, text: str) -> str:
        """Classify a user message into an abstract shape (never return text)."""
        t = text.strip()
        if not t:
            return "empty"
        if t.startswith("/"):
            return "slash_command"
        # All-numeric content (e.g. IDs, bins)
        t_clean = t.replace("\n", " ").replace(",", " ").strip()
        if t_clean and all(part.isdigit() for part in t_clean.split()):
            return "numeric_list" if ("\n" in t or len(t_clean.split()) > 2) else "single_number"
        if len(t) <= 40 and "\n" not in t:
            return "short_phrase"
        if "\n" in t:
            return "multiline_text"
        return "long_phrase"

    def _bot_pattern(self, text: str) -> tuple:
        """Classify a bot response into (abstract pattern, error_keyword|None).

        NEVER returns message content.
        """
        low = text.lower()
        # Error detection - keyword ONLY, never the sentence
        if self._looks_like_rate_limit(text):
            return "rate_limit", self._match_kw(text)
        for kw in self.redactor._keywords:
            if kw.lower() in low:
                return "error", kw
        if "choose option" in low or "请选择操作" in low or "select the correct command" in low:
            return "menu", None
        if "enter" in low or "请输入" in low or "输入" in low or "Please enter" in low:
            return "input_prompt", None
        if "list of cards" in low or "卡" in text or "list" in low:
            return "content_list", None
        if text.startswith("🔥"):
            return "news_bulletin", None
        return "plain_response", None

    def _match_kw(self, text: str) -> Optional[str]:
        low = text.lower()
        for kw in self.redactor._keywords:
            if kw.lower() in low:
                return kw
        return None

    def _looks_like_rate_limit(self, text: str) -> bool:
        low = text.lower()
        return any(k in low for k in (
            "wait", "please wait", "too many", "rate limit", "10 seconds",
            "10秒", "耐心等待", "请等待", "try later", "稍后",
        ))

    def _apply_delay_learning(self, text: str, skill: BotSkill) -> None:
        """Record ONLY the numeric delay - never the sentence."""
        import re
        match = re.search(r"(\d+)\s*(?:秒|s|second|sec)", text, re.IGNORECASE)
        delay = int(match.group(1)) if match else 10
        skill.learned_facts["recommended_delay_between_requests_seconds"] = delay


def load_bot_skill_with_conversation(
    skill_name: str,
    conversation_path: str,
    bot_name: str = "",
    chat_name: str = "",
    skills_dir: Path = SKILLS_DIR,
) -> BotSkill:
    """Create/load a skill and learn from a conversation export (privacy-first)."""
    skill = BotSkill.load(skill_name, skills_dir=skills_dir)
    if skill is None:
        skill = BotSkill(
            skill_name=skill_name,
            bot_name=bot_name,
            chat_name=chat_name,
        )
    learner = ConversationLearner()
    learner.learn_from_file(conversation_path, skill)
    skill.save(skills_dir)
    return skill
