"""Persistent memory and state for Telegram automaton.

This module provides durable storage for:
- Conversation state (which chats, last message IDs/positions)
- Learned operational knowledge (bot responses, commands, protocols)
- Goal progress tracking (checkpointing for long-running tasks)
- Error history and recovery strategies

Uses SQLite for durability so state survives process restarts.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime


@dataclass
class ChatState:
    """Persistent state for a chat being automated."""
    chat_name: str
    op_name: str
    last_message_id: Optional[int] = None
    total_known_messages: int = 0
    bot_name: Optional[str] = None
    bot_commands: List[str] = field(default_factory=list)
    extraction_patterns: List[str] = field(default_factory=list)
    daily_quota: Optional[int] = None
    failures: int = 0
    completed_cycles: int = 0
    learned_handlers: Dict[str, str] = field(default_factory=dict)


@dataclass
class GoalState:
    """Persistent state for a long-running goal."""
    goal_id: str
    description: str
    status: str = "pending"  # pending | running | completed | failed | paused
    current_milestone: str = ""
    milestones: List[Dict[str, Any]] = field(default_factory=list)
    progress: Dict[str, Any] = field(default_factory=dict)
    messages_sent: int = 0
    messages_failed: int = 0
    created_at: str = ""
    updated_at: str = ""
    last_error: str = ""


class TelegramMemory:
    """SQLite-backed persistent memory for the Telegram automaton."""

    def __init__(self, db_path: str = "ufo_skill_state/telegram_memory.db"):
        """Initialize memory store at db_path."""
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_states (
                    chat_name TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS goals (
                    goal_id TEXT PRIMARY KEY,
                    goal_json TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    # ==================== Chat State ====================

    def save_chat_state(self, chat_state: ChatState) -> None:
        """Save or update a chat state."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO chat_states (chat_name, state_json) VALUES (?, ?)",
                (chat_state.chat_name, json.dumps(asdict(chat_state), default=str)),
            )

    def load_chat_state(self, chat_name: str) -> Optional[ChatState]:
        """Load a chat state, or None if not present."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT state_json FROM chat_states WHERE chat_name = ?", (chat_name,)
            ).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        return ChatState(**data)

    def load_all_chat_states(self) -> Dict[str, ChatState]:
        """Load all chat states keyed by chat name."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT chat_name, state_json FROM chat_states").fetchall()
        result = {}
        for chat_name, state_json in rows:
            data = json.loads(state_json)
            result[chat_name] = ChatState(**data)
        return result

    def delete_chat_state(self, chat_name: str) -> None:
        """Delete a chat state."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM chat_states WHERE chat_name = ?", (chat_name,))

    # ==================== Goal State ====================

    def save_goal(self, goal: GoalState) -> None:
        """Save or update goal state."""
        goal.updated_at = datetime.now().isoformat()
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO goals (goal_id, goal_json) VALUES (?, ?)",
                (goal.goal_id, json.dumps(asdict(goal), default=str)),
            )

    def load_goal(self, goal_id: str) -> Optional[GoalState]:
        """Load a goal state, or None if not present."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT goal_json FROM goals WHERE goal_id = ?", (goal_id,)
            ).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        return GoalState(**data)

    def load_all_goals(self) -> Dict[str, GoalState]:
        """Load all goals keyed by goal id."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT goal_id, goal_json FROM goals").fetchall()
        result = {}
        for goal_id, goal_json in rows:
            data = json.loads(goal_json)
            result[goal_id] = GoalState(**data)
        return result

    # ==================== Knowledge ====================

    def set_knowledge(self, key: str, value: Any) -> None:
        """Store a knowledge key-value pair."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO knowledge (key, value, updated_at) VALUES (?, ?, ?)",
                (key, json.dumps(value, default=str), datetime.now().isoformat()),
            )

    def get_knowledge(self, key: str, default: Any = None) -> Any:
        """Retrieve a knowledge value."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT value FROM knowledge WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return default
        return json.loads(row[0])

    def get_all_knowledge(self) -> Dict[str, Any]:
        """Retrieve all knowledge as a dict."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT key, value FROM knowledge").fetchall()
        return {key: json.loads(value) for key, value in rows}

    def delete_knowledge(self, key: str) -> None:
        """Delete a knowledge entry."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM knowledge WHERE key = ?", (key,))
