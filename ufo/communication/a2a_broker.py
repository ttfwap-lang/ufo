# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Agent-to-Agent (A2A) Message Broker — Cross-agent data sharing for multi-app workflows.

When an AppAgent running Excel extracts a table, it publishes an AgentMessage
to the broker. A separate AppAgent running Chrome can subscribe to receive
that data without losing context.

Provides both synchronous (threading.Queue) and optional async (asyncio.Queue)
interfaces to match the mixed sync/async codebase.

Thread-safe singleton — all agents share the same broker instance.

Usage:
    from ufo.communication.a2a_broker import MessageBroker, AgentMessage

    broker = MessageBroker.get_instance()

    # Register agents
    broker.register_agent("excel_agent_1")
    broker.register_agent("chrome_agent_2")

    # Publish from Excel agent
    broker.publish(AgentMessage(
        source_agent="excel_agent_1",
        target_agent="chrome_agent_2",
        payload_type="extracted_table",
        data={"rows": [...], "columns": [...]},
    ))

    # Subscribe from Chrome agent (blocking, with timeout)
    msg = broker.subscribe("chrome_agent_2", timeout=10.0)
"""

import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class AgentMessage(BaseModel):
    """A message passed between agents via the broker."""
    source_agent: str = Field(..., description="Sending agent ID")
    target_agent: str = Field(..., description="Receiving agent ID")
    payload_type: str = Field(
        ..., description="Message type: extracted_table, auth_token, status_flag, etc."
    )
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
    correlation_id: str = Field(default="", description="For request/response pairing")


class BrokerStats(BaseModel):
    """Broker usage statistics."""
    registered_agents: int = 0
    total_published: int = 0
    total_consumed: int = 0
    total_dropped: int = 0
    pending_messages: Dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Message Broker (Singleton, Thread-Safe)
# ---------------------------------------------------------------------------

class MessageBroker:
    """
    Thread-safe in-memory message broker for cross-agent communication.

    Each registered agent gets a dedicated message queue. Publishers
    route messages to the target agent's queue. Subscribers block
    (with timeout) waiting for incoming messages.

    Singleton — use MessageBroker.get_instance() to get the shared instance.
    """

    _instance: Optional["MessageBroker"] = None
    _init_lock = threading.Lock()

    def __init__(self, max_queue_size: int = 100) -> None:
        self._queues: Dict[str, queue.Queue] = {}
        self._agents: Dict[str, Dict[str, Any]] = {}  # agent_id -> metadata
        self._lock = threading.Lock()
        self._max_queue_size = max_queue_size
        self._stats_published = 0
        self._stats_consumed = 0
        self._stats_dropped = 0

    @classmethod
    def get_instance(cls) -> "MessageBroker":
        """Get or create the singleton broker instance."""
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton (for testing)."""
        with cls._init_lock:
            cls._instance = None

    # -----------------------------------------------------------------------
    # Agent Registration
    # -----------------------------------------------------------------------

    def register_agent(
        self, agent_id: str, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Register an agent's mailbox.

        :param agent_id: Unique agent identifier.
        :param metadata: Optional metadata (process_name, role, etc.).
        """
        with self._lock:
            if agent_id not in self._queues:
                self._queues[agent_id] = queue.Queue(maxsize=self._max_queue_size)
                self._agents[agent_id] = metadata or {}
                logger.info(f"[Broker] Registered mailbox for '{agent_id}'")
            else:
                logger.debug(f"[Broker] Agent '{agent_id}' already registered.")

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent's mailbox and discard pending messages."""
        with self._lock:
            self._queues.pop(agent_id, None)
            self._agents.pop(agent_id, None)
            logger.info(f"[Broker] Unregistered mailbox for '{agent_id}'")

    def is_registered(self, agent_id: str) -> bool:
        """Check if an agent is registered."""
        return agent_id in self._queues

    def list_agents(self) -> List[str]:
        """List all registered agent IDs."""
        return list(self._queues.keys())

    # -----------------------------------------------------------------------
    # Publish / Subscribe
    # -----------------------------------------------------------------------

    def publish(self, message: AgentMessage) -> bool:
        """
        Publish a message to the target agent's queue.

        :param message: The message to deliver.
        :return: True if delivered, False if target not found or queue full.
        """
        target = message.target_agent

        with self._lock:
            if target not in self._queues:
                logger.warning(
                    f"[Broker] Target '{target}' not registered. "
                    f"Message from '{message.source_agent}' dropped."
                )
                self._stats_dropped += 1
                return False

            target_queue = self._queues[target]

        try:
            target_queue.put_nowait(message)
            self._stats_published += 1
            logger.debug(
                f"[Broker] Message routed: {message.source_agent} → "
                f"{target} (type={message.payload_type})"
            )
            return True
        except queue.Full:
            logger.warning(
                f"[Broker] Queue full for '{target}'. "
                f"Message from '{message.source_agent}' dropped."
            )
            self._stats_dropped += 1
            return False

    def subscribe(
        self, agent_id: str, timeout: float = 10.0
    ) -> Optional[AgentMessage]:
        """
        Subscribe (blocking) to receive the next message for this agent.

        :param agent_id: The agent's ID.
        :param timeout: Maximum seconds to wait.
        :return: AgentMessage or None on timeout.
        :raises ValueError: If agent is not registered.
        """
        with self._lock:
            if agent_id not in self._queues:
                raise ValueError(
                    f"Agent '{agent_id}' not registered. Call register_agent() first."
                )
            agent_queue = self._queues[agent_id]

        try:
            message = agent_queue.get(block=True, timeout=timeout)
            self._stats_consumed += 1
            logger.debug(
                f"[Broker] Message consumed by '{agent_id}' "
                f"(from={message.source_agent}, type={message.payload_type})"
            )
            return message
        except queue.Empty:
            return None

    def try_get(self, agent_id: str) -> Optional[AgentMessage]:
        """
        Non-blocking attempt to get a message.

        :param agent_id: The agent's ID.
        :return: AgentMessage or None if no message available.
        """
        with self._lock:
            if agent_id not in self._queues:
                return None
            agent_queue = self._queues[agent_id]

        try:
            message = agent_queue.get_nowait()
            self._stats_consumed += 1
            return message
        except queue.Empty:
            return None

    def peek(self, agent_id: str) -> int:
        """Check how many messages are pending for an agent."""
        with self._lock:
            if agent_id not in self._queues:
                return 0
            return self._queues[agent_id].qsize()

    # -----------------------------------------------------------------------
    # Broadcast
    # -----------------------------------------------------------------------

    def broadcast(
        self,
        source_agent: str,
        payload_type: str,
        data: Dict[str, Any],
        exclude: Optional[List[str]] = None,
    ) -> int:
        """
        Broadcast a message to ALL registered agents (except source and exclusions).

        :param source_agent: Sending agent ID.
        :param payload_type: Message type.
        :param data: Payload data.
        :param exclude: Agent IDs to exclude from broadcast.
        :return: Number of agents that received the message.
        """
        exclude_set = set(exclude or [])
        exclude_set.add(source_agent)

        delivered = 0
        for agent_id in self.list_agents():
            if agent_id in exclude_set:
                continue
            msg = AgentMessage(
                source_agent=source_agent,
                target_agent=agent_id,
                payload_type=payload_type,
                data=data,
            )
            if self.publish(msg):
                delivered += 1

        logger.info(
            f"[Broker] Broadcast from '{source_agent}': "
            f"delivered to {delivered} agents."
        )
        return delivered

    # -----------------------------------------------------------------------
    # Stats
    # -----------------------------------------------------------------------

    def get_stats(self) -> BrokerStats:
        """Get broker usage statistics."""
        pending = {}
        with self._lock:
            for agent_id, q in self._queues.items():
                pending[agent_id] = q.qsize()

        return BrokerStats(
            registered_agents=len(self._queues),
            total_published=self._stats_published,
            total_consumed=self._stats_consumed,
            total_dropped=self._stats_dropped,
            pending_messages=pending,
        )

    def drain_all(self) -> int:
        """Drain all queues (for shutdown). Returns total messages discarded."""
        total = 0
        with self._lock:
            for agent_id, q in self._queues.items():
                while not q.empty():
                    try:
                        q.get_nowait()
                        total += 1
                    except queue.Empty:
                        break
        logger.info(f"[Broker] Drained {total} messages from all queues.")
        return total
