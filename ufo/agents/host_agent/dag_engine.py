# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
HostAgent DAG Engine — Pydantic v2 schemas, topological sorter, and self-healing
state machine for dynamic task decomposition and execution.

Provides:
  - DAGNode: Individual task node with status, dependencies, and irrevocable flag
  - TaskAction: Typed action descriptor (click, type, hotkey, wait, audit)
  - ExecutionGraph: Full DAG with topological ordering, dependency tracking,
    and dynamic recovery node injection for self-healing
  - RecoveryPlan: Diagnostic context for failed nodes

Usage:
    from ufo.agents.host_agent.dag_engine import (
        DAGNode, TaskAction, ExecutionGraph, NodeStatus
    )

    graph = ExecutionGraph(workflow_id="task_001")
    graph.add_node(DAGNode(
        node_id="open_notepad",
        description="Open Notepad application",
        action=TaskAction(action_type="hotkey", target_app="explorer.exe", payload="win+r"),
    ))
"""

import hashlib
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NodeStatus(str, Enum):
    """Execution state of a DAG node."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"       # Frozen by self-healing loop
    RECOVERY = "RECOVERY"     # Recovery node in progress


class ActionType(str, Enum):
    """Supported action categories."""
    CLICK = "click"
    TYPE = "type"
    HOTKEY = "hotkey"
    WAIT = "wait"
    SCROLL = "scroll"
    DRAG = "drag"
    AUDIT = "audit"           # Irrevocable action requiring security gating
    NAVIGATE = "navigate"     # Inter-app window switching


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class TaskAction(BaseModel):
    """Describes a single UI automation action."""
    action_type: str = Field(
        ...,
        description="Action category: click, type, hotkey, wait, scroll, drag, audit, navigate",
    )
    target_app: str = Field(
        ...,
        description="Target process name or window title",
    )
    target_control: Optional[Dict[str, Any]] = Field(
        None,
        description="UIA identification selector or bounding box coordinates",
    )
    payload: Optional[str] = Field(
        None,
        description="Text to input, key sequence, or URL to navigate to",
    )


class RecoveryPlan(BaseModel):
    """Diagnostic context captured when a node fails, used to generate recovery nodes."""
    recovery_description: str = Field(
        ...,
        description="What the recovery node should attempt to do",
    )
    error_trace: str = Field(
        default="",
        description="Exception traceback from the failed execution",
    )
    diagnostic_screenshot: Optional[str] = Field(
        None,
        description="Path to screenshot captured at failure time",
    )
    uia_tree_snapshot: Optional[str] = Field(
        None,
        description="Serialized pruned UIA tree at failure time",
    )
    reasoning_response: Optional[str] = Field(
        None,
        description="Diagnostic response from REASONING_AGENT (o3/Gemini)",
    )


class DAGNode(BaseModel):
    """A single node in the execution DAG."""
    node_id: str = Field(..., description="Unique node identifier")
    description: str = Field(..., description="Human-readable task description")
    action: TaskAction = Field(..., description="The action to execute")
    dependencies: List[str] = Field(
        default_factory=list,
        description="List of node_ids that must complete before this node",
    )
    status: NodeStatus = Field(
        default=NodeStatus.PENDING,
        description="Current execution state",
    )
    is_irrevocable: bool = Field(
        default=False,
        description="If True, requires security audit before execution",
    )
    idempotency_key: Optional[str] = Field(
        None,
        description="Deterministic SHA-256 hash for irrevocable action deduplication",
    )
    retry_count: int = Field(default=0, description="Current retry attempt")
    max_retries: int = Field(default=2, description="Maximum retry attempts")
    recovery_plan: Optional[RecoveryPlan] = Field(
        None,
        description="Diagnostic context if this node failed and needs recovery",
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp of node creation",
    )

    def generate_idempotency_key(self) -> str:
        """
        Generate a deterministic SHA-256 idempotency key for this node.
        Key is invariant across retries — based on node_id + action + target.
        """
        raw_key = (
            f"{self.node_id}_"
            f"{self.action.action_type}_"
            f"{self.action.target_app}_"
            f"{self.action.payload or ''}"
        )
        self.idempotency_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        return self.idempotency_key


# ---------------------------------------------------------------------------
# Execution Graph
# ---------------------------------------------------------------------------

class ExecutionGraph(BaseModel):
    """
    Full DAG for a HostAgent workflow.

    Supports:
      - Topological ordering of executable nodes
      - Dependency-aware status tracking
      - Dynamic recovery node injection (self-healing)
      - Downstream dependency freezing on failure
    """
    workflow_id: str = Field(..., description="Unique workflow identifier")
    nodes: Dict[str, DAGNode] = Field(
        default_factory=dict,
        description="All nodes in the DAG, keyed by node_id",
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp of graph creation",
    )

    def add_node(self, node: DAGNode) -> None:
        """
        Add a node to the DAG.
        Auto-generates idempotency key for irrevocable nodes.
        """
        if node.is_irrevocable and not node.idempotency_key:
            node.generate_idempotency_key()
        self.nodes[node.node_id] = node

    def get_executable_nodes(self) -> List[DAGNode]:
        """
        Returns all nodes whose dependencies are strictly COMPLETED
        and whose status is PENDING (ready to run).
        """
        executable = []
        for node in self.nodes.values():
            if node.status != NodeStatus.PENDING:
                continue
            deps_met = all(
                self.nodes[dep_id].status == NodeStatus.COMPLETED
                for dep_id in node.dependencies
                if dep_id in self.nodes
            )
            if deps_met:
                executable.append(node)
        return executable

    def freeze_downstream(self, failed_node_id: str) -> List[str]:
        """
        Freeze (BLOCK) all nodes that transitively depend on the failed node.
        Returns the list of blocked node_ids.

        This prevents downstream tasks from executing with stale/invalid state
        while recovery is in progress.
        """
        blocked: List[str] = []
        # Find all nodes that depend on the failed node (direct + transitive)
        to_check = [failed_node_id]
        visited = set()

        while to_check:
            current = to_check.pop()
            if current in visited:
                continue
            visited.add(current)

            for node in self.nodes.values():
                if current in node.dependencies and node.node_id not in visited:
                    if node.status == NodeStatus.PENDING:
                        node.status = NodeStatus.BLOCKED
                        blocked.append(node.node_id)
                        logger.info(
                            f"Froze downstream node '{node.node_id}' "
                            f"(depends on failed '{failed_node_id}')"
                        )
                    to_check.append(node.node_id)

        return blocked

    def unfreeze_downstream(self, node_id: str) -> List[str]:
        """
        Unfreeze (restore to PENDING) all BLOCKED nodes that depended on the
        given node, now that it has been recovered.
        """
        unfrozen: List[str] = []
        for node in self.nodes.values():
            if node.status == NodeStatus.BLOCKED:
                # Check if all dependencies are now COMPLETED or PENDING
                can_unfreeze = all(
                    self.nodes.get(dep, DAGNode(
                        node_id="", description="", action=TaskAction(
                            action_type="wait", target_app=""
                        )
                    )).status in (NodeStatus.COMPLETED, NodeStatus.PENDING)
                    for dep in node.dependencies
                )
                if can_unfreeze:
                    node.status = NodeStatus.PENDING
                    unfrozen.append(node.node_id)
                    logger.info(f"Unfroze node '{node.node_id}' after recovery")
        return unfrozen

    def inject_recovery_node(
        self,
        failed_node_id: str,
        recovery_action: TaskAction,
        recovery_description: str = "",
        error_trace: str = "",
    ) -> DAGNode:
        """
        Dynamically rewire the DAG on failure:

        1. Creates an ephemeral recovery node
        2. Sets recovery node dependencies to match the failed node's pre-conditions
        3. Makes the failed node depend on the recovery node (so it re-executes after recovery)
        4. Freezes downstream dependencies
        5. Resets the failed node to PENDING

        :param failed_node_id: The node_id that failed
        :param recovery_action: The action to perform for recovery
        :param recovery_description: Human-readable recovery description
        :param error_trace: Exception traceback for diagnostics
        :return: The created recovery DAGNode
        """
        failed_node = self.nodes[failed_node_id]

        # Generate recovery node ID
        recovery_node_id = f"RECOVERY_{failed_node_id}_{int(time.time())}"

        # Build recovery description
        if not recovery_description:
            recovery_description = (
                f"Auto-recovery for '{failed_node.description}'. "
                f"Dismiss any error dialogs or popups and restore the application "
                f"to a stable state."
            )

        # Create recovery node
        recovery_node = DAGNode(
            node_id=recovery_node_id,
            description=recovery_description,
            action=recovery_action,
            dependencies=list(failed_node.dependencies),  # Same pre-conditions
            status=NodeStatus.PENDING,
            is_irrevocable=False,
            recovery_plan=RecoveryPlan(
                recovery_description=recovery_description,
                error_trace=error_trace,
            ),
        )

        # Add recovery node to graph
        self.add_node(recovery_node)

        # Rewire: failed node now depends on recovery completing first
        if recovery_node_id not in failed_node.dependencies:
            failed_node.dependencies.append(recovery_node_id)
        failed_node.status = NodeStatus.PENDING
        failed_node.retry_count += 1

        # Freeze downstream
        frozen = self.freeze_downstream(failed_node_id)

        logger.info(
            f"Injected recovery node '{recovery_node_id}' for failed "
            f"'{failed_node_id}'. Froze {len(frozen)} downstream nodes."
        )

        return recovery_node

    def mark_completed(self, node_id: str) -> None:
        """Mark a node as completed and unfreeze any downstream blocked nodes."""
        if node_id in self.nodes:
            self.nodes[node_id].status = NodeStatus.COMPLETED
            self.unfreeze_downstream(node_id)

    def mark_failed(self, node_id: str) -> None:
        """Mark a node as failed."""
        if node_id in self.nodes:
            self.nodes[node_id].status = NodeStatus.FAILED

    def mark_running(self, node_id: str) -> None:
        """Mark a node as running."""
        if node_id in self.nodes:
            self.nodes[node_id].status = NodeStatus.RUNNING

    @property
    def is_complete(self) -> bool:
        """Check if all nodes have reached a terminal state."""
        return all(
            node.status in (NodeStatus.COMPLETED, NodeStatus.FAILED)
            for node in self.nodes.values()
        )

    @property
    def has_failures(self) -> bool:
        """Check if any nodes are in FAILED state."""
        return any(
            node.status == NodeStatus.FAILED
            for node in self.nodes.values()
        )

    def summary(self) -> Dict[str, Any]:
        """Return a summary of the current graph state."""
        status_counts: Dict[str, int] = {}
        for node in self.nodes.values():
            status_counts[node.status.value] = status_counts.get(node.status.value, 0) + 1
        return {
            "workflow_id": self.workflow_id,
            "total_nodes": len(self.nodes),
            "status_counts": status_counts,
            "is_complete": self.is_complete,
            "has_failures": self.has_failures,
        }
