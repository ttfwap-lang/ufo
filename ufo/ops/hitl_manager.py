"""
HITL Manager — Agent-side listener for human operator decisions.

When the DAG Engine halts for human review (e.g., Swarm Auditor low-confidence,
DLQ escalation), this module subscribes to a Redis Pub/Sub channel and blocks
until a human operator sends a resolution via the Control Plane API.

Supports both:
  - Async mode: Uses redis.asyncio for integration with async DAG loops
  - Sync mode: Uses threading + redis for synchronous DAG execution

Resolution Types:
  - APPROVE: Resume DAG execution from the paused node
  - ABORT: Terminate the workflow, finalize to DLQ
  - MANUAL_REWIRE: Replace the current node's action with operator-provided payload

Config in system.yaml:
    CONTROL_PLANE:
      REDIS_URL: "redis://127.0.0.1:6379/0"

Usage (sync):
    from ufo.ops.hitl_manager import HITLManager


    hitl = HITLManager()
    resolution = hitl.wait_for_resolution(
        workflow_id="wf_123",
        timeout_minutes=15,
    )
    if resolution["decision"] == "APPROVE":
        pass
        # Resume execution
    elif resolution["decision"] == "ABORT":
        pass
        # Terminate

Usage (async):
    resolution = await hitl.async_wait_for_resolution("wf_123", timeout_minutes=15)
"""
import json
import logging
import threading
import time
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

def _load_hitl_config() -> Dict[str, Any]:
    """Load HITL config."""
    defaults = {'REDIS_URL': 'redis://127.0.0.1:6379/0', 'DEFAULT_TIMEOUT_MINUTES': 15}
    try:
        from ufo.config.config_loader import get_ufo_config
        cfg = get_ufo_config()
        cp = getattr(cfg.system, 'control_plane', None)
        if cp and isinstance(cp, dict):
            defaults['REDIS_URL'] = cp.get('REDIS_URL', defaults['REDIS_URL'])
        df = getattr(cfg.system, 'distributed_fleet', None)
        if df and isinstance(df, dict):
            defaults['REDIS_URL'] = df.get('REDIS_URL', defaults['REDIS_URL'])
    except Exception:
        pass
    return defaults

class HITLManager:
    """
    Agent-side listener for human-in-the-loop decisions.

    When a workflow is paused for human review, subscribes to a Redis
    Pub/Sub channel and blocks until the operator sends a resolution.
    """

    def __init__(self, redis_url: Optional[str]=None) -> None:
        self._config = _load_hitl_config()
        self._redis_url = redis_url or self._config.get('REDIS_URL')
        self._default_timeout = int(self._config.get('DEFAULT_TIMEOUT_MINUTES', 15))
        self._redis = None
        self._available = False
        self._init_redis()

    def _init_redis(self) -> None:
        """Initialize sync Redis connection."""
        try:
            import redis
            self._redis = redis.from_url(self._redis_url, decode_responses=True, socket_connect_timeout=5)
            self._redis.ping()
            self._available = True
        except Exception as e:
            logger.warning(f'[HITL] Redis unavailable: {e}')

    def wait_for_resolution(self, workflow_id: str, timeout_minutes: Optional[int]=None, context: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
        """
        Block until a human operator sends a decision for this workflow.

        If no decision arrives within timeout, returns an automatic ABORT
        to prevent resource deadlock.

        :param workflow_id: The workflow awaiting human input.
        :param timeout_minutes: Max wait time. None uses default (15 min).
        :param context: Optional context about why HITL was triggered.
        :return: Resolution dict with 'decision', 'operator_id', etc.
        """
        timeout = (timeout_minutes or self._default_timeout) * 60
        channel = f'ufo:hitl:response:{workflow_id}'
        logger.critical(f"[HITL] Workflow '{workflow_id}' HALTED. Awaiting human operator on channel '{channel}' (timeout={timeout // 60} min)...")
        if not self._available:
            return self._local_fallback(workflow_id, timeout)
        self._register_waiting(workflow_id, context)
        pending = self._check_pending_resolution(workflow_id)
        if pending:
            self._unregister_waiting(workflow_id)
            return pending
        pubsub = self._redis.pubsub()
        pubsub.subscribe(channel)
        try:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=min(remaining, 5.0))
                if message and message['type'] == 'message':
                    try:
                        resolution = json.loads(message['data'])
                        logger.info(f"[HITL] Resolution received for '{workflow_id}': {resolution.get('decision', 'UNKNOWN')}")
                        self._unregister_waiting(workflow_id)
                        return resolution
                    except json.JSONDecodeError:
                        logger.warning(f"[HITL] Invalid JSON in resolution: {message['data']}")
                if time.monotonic() % 10 < 5:
                    pending = self._check_pending_resolution(workflow_id)
                    if pending:
                        self._unregister_waiting(workflow_id)
                        return pending
            logger.error(f"[HITL] TIMEOUT: No operator responded for workflow '{workflow_id}' within {timeout // 60} minutes.")
            self._unregister_waiting(workflow_id)
            return {'decision': 'ABORT', 'reason': 'hitl_timeout', 'timeout_minutes': timeout // 60, 'operator_id': 'SYSTEM'}
        finally:
            try:
                pubsub.unsubscribe(channel)
                pubsub.close()
            except Exception:
                pass

    async def async_wait_for_resolution(self, workflow_id: str, timeout_minutes: Optional[int]=None, context: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
        """
        Async version — uses redis.asyncio for non-blocking wait.
        """
        timeout = (timeout_minutes or self._default_timeout) * 60
        channel = f'ufo:hitl:response:{workflow_id}'
        logger.critical(f"[HITL] Workflow '{workflow_id}' HALTED (async). Awaiting operator on '{channel}'...")
        try:
            import asyncio
            import redis.asyncio as aioredis
            r = aioredis.from_url(self._redis_url, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.subscribe(channel)
            self._register_waiting(workflow_id, context)
            try:
                async with asyncio.timeout(timeout):
                    async for message in pubsub.listen():
                        if message['type'] == 'message':
                            try:
                                resolution = json.loads(message['data'])
                                logger.info(f"[HITL] Resolution received (async): {resolution.get('decision', 'UNKNOWN')}")
                                self._unregister_waiting(workflow_id)
                                return resolution
                            except json.JSONDecodeError:
                                continue
            except asyncio.TimeoutError:
                logger.error(f"[HITL] TIMEOUT (async): No response for '{workflow_id}' within {timeout // 60} minutes.")
                self._unregister_waiting(workflow_id)
                return {'decision': 'ABORT', 'reason': 'hitl_timeout', 'operator_id': 'SYSTEM'}
            finally:
                await pubsub.unsubscribe(channel)
                await r.aclose()
        except ImportError:
            logger.warning('[HITL] redis.asyncio not available — using sync fallback.')
            return self.wait_for_resolution(workflow_id, timeout_minutes, context)

    def request_human_review(self, workflow_id: str, reason: str, screenshot_path: Optional[str]=None, dag_state: Optional[Dict[str, Any]]=None) -> bool:
        """
        Signal that a workflow needs human review.

        Pushes metadata to Redis so the Control Plane API can display it,
        and optionally creates a DLQ snapshot.

        :param workflow_id: The workflow needing review.
        :param reason: Why human review is needed.
        :param screenshot_path: Current screenshot for context.
        :param dag_state: Current DAG state.
        :return: True if request was registered.
        """
        if not self._available:
            logger.warning('[HITL] Cannot request review — Redis unavailable.')
            return False
        try:
            review_data = {'workflow_id': workflow_id, 'reason': reason, 'requested_at': time.time(), 'status': 'awaiting_operator'}
            if dag_state:
                review_data['dag_state'] = dag_state
            key = f'ufo:hitl:review:{workflow_id}'
            self._redis.setex(key, 3600, json.dumps(review_data))
            self._redis.lpush('ufo:hitl:pending_reviews', json.dumps(review_data))
            logger.info(f"[HITL] Review requested for '{workflow_id}': {reason}")
            if screenshot_path:
                try:
                    from ufo.resilience.dlq_manager import DeadLetterQueueManager
                    dlq = DeadLetterQueueManager()
                    dlq.capture_failure(task_id=f'HITL_{workflow_id}', error_chain=f'HITL escalation: {reason}', dag_state=dag_state, screenshots={'current': screenshot_path})
                except Exception:
                    pass
            return True
        except Exception as e:
            logger.error(f'[HITL] Review request failed: {e}')
            return False

    def _register_waiting(self, workflow_id: str, context: Optional[Dict[str, Any]]=None) -> None:
        """Mark this workflow as waiting for HITL resolution."""
        if not self._available:
            return
        try:
            info = {'workflow_id': workflow_id, 'waiting_since': time.time(), 'context': context or {}}
            self._redis.setex(f'ufo:hitl:waiting:{workflow_id}', 3600, json.dumps(info))
        except Exception:
            pass

    def _unregister_waiting(self, workflow_id: str) -> None:
        """Remove the waiting marker."""
        if not self._available:
            return
        try:
            self._redis.delete(f'ufo:hitl:waiting:{workflow_id}')
        except Exception:
            pass

    def _check_pending_resolution(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Check if a resolution was queued before we subscribed."""
        if not self._available:
            return None
        try:
            key = f'ufo:hitl:pending:{workflow_id}'
            data = self._redis.get(key)
            if data:
                self._redis.delete(key)
                return json.loads(data)
        except Exception:
            pass
        return None

    def _local_fallback(self, workflow_id: str, timeout_seconds: float) -> Dict[str, Any]:
        """
        Local fallback when Redis is unavailable.
        Uses a threading.Event that external code can signal.
        """
        logger.warning(f"[HITL] No Redis — local fallback. Workflow '{workflow_id}' will auto-ABORT after {timeout_seconds}s.")
        event = threading.Event()
        event.wait(timeout=timeout_seconds)
        return {'decision': 'ABORT', 'reason': 'no_redis_hitl_timeout', 'operator_id': 'SYSTEM'}