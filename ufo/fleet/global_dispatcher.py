"""
Global Fleet Dispatcher — Redis-backed distributed job queue for fleet workers.

Replaces the local queue.Queue from event_daemon.py (Ticket 5) with a
Redis-backed distributed queue. VMs act as consumer workers, popping tasks
off a shared Redis list using BRPOPLPUSH (atomic fetch + backup).

Atomic Handoff Pattern:
  1. Worker calls fetch_next_workflow() → BRPOPLPUSH atomically moves task
     from the global queue to a worker-specific processing list
  2. If the worker crashes, the task stays in the processing list (not lost)
  3. On success, mark_workflow_complete() removes it from the processing list
  4. FleetWatchdog detects dead workers and triages orphaned tasks to DLQ

Config in system.yaml:
    DISTRIBUTED_FLEET:
      REDIS_URL: "redis://127.0.0.1:6379/0"
      QUEUE_NAME: "ufo:queue:bankfidelity_tasks"
      FETCH_TIMEOUT_SECONDS: 5

Usage:
    from ufo.fleet.global_dispatcher import GlobalDispatcher


    dispatcher = GlobalDispatcher()
    task = dispatcher.fetch_next_workflow()
    if task:
        try:
            process(task)
            dispatcher.mark_workflow_complete(task["workflow_id"])
        except Exception:
            dispatcher.mark_workflow_failed(task["workflow_id"])
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

def _load_dispatcher_config() -> Dict[str, Any]:
    """Load dispatcher config from system.yaml."""
    defaults = {'ENABLED': False, 'REDIS_URL': 'redis://127.0.0.1:6379/0', 'WORKER_ID': 'auto', 'QUEUE_NAME': 'ufo:queue:bankfidelity_tasks', 'DLQ_QUEUE': 'ufo:queue:dlq', 'FETCH_TIMEOUT_SECONDS': 5}
    try:
        from ufo.config.config_loader import get_ufo_config
        cfg = get_ufo_config()
        df = getattr(cfg.system, 'distributed_fleet', None)
        if df and isinstance(df, dict):
            defaults.update({k: v for k, v in df.items() if v is not None})
    except Exception:
        pass
    return defaults

def _resolve_worker_id(configured: str) -> str:
    """Resolve worker ID."""
    if configured == 'auto':
        hostname = os.environ.get('COMPUTERNAME', os.environ.get('HOSTNAME', 'unknown'))
        return f'{hostname}_{os.getpid()}'
    return configured

class GlobalDispatcher:
    """
    Redis-backed distributed job queue for multi-VM fleet operation.

    Workers fetch tasks atomically using BRPOPLPUSH, which moves the task
    to a worker-specific processing list in a single atomic operation.
    This ensures no task is lost even if the worker crashes immediately
    after fetching.
    """

    def __init__(self, redis_url: Optional[str]=None, worker_id: Optional[str]=None) -> None:
        self._config = _load_dispatcher_config()
        self._redis_url = redis_url or self._config.get('REDIS_URL')
        self._worker_id = worker_id or _resolve_worker_id(self._config.get('WORKER_ID', 'auto'))
        self._queue_name = self._config.get('QUEUE_NAME', 'ufo:queue:bankfidelity_tasks')
        self._dlq_queue = self._config.get('DLQ_QUEUE', 'ufo:queue:dlq')
        self._fetch_timeout = int(self._config.get('FETCH_TIMEOUT_SECONDS', 5))
        self._processing_queue = f'ufo:queue:processing:{self._worker_id}'
        self._redis = None
        self._available = False
        self._current_raw: Optional[str] = None
        self._init_redis()

    def _init_redis(self) -> None:
        """Initialize Redis connection."""
        if not self._config.get('ENABLED', False):
            return
        try:
            import redis as redis_lib
            self._redis = redis_lib.from_url(self._redis_url, decode_responses=True, socket_connect_timeout=5, socket_timeout=max(self._fetch_timeout + 2, 10))
            self._redis.ping()
            self._available = True
            logger.info(f'[Dispatcher] Connected: {self._redis_url} (worker={self._worker_id}, queue={self._queue_name})')
        except ImportError:
            logger.info('[Dispatcher] redis not installed — dispatcher disabled.')
        except Exception as e:
            logger.warning(f'[Dispatcher] Redis connection failed: {e}')

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def is_available(self) -> bool:
        return self._available

    def fetch_next_workflow(self) -> Optional[Dict[str, Any]]:
        """
        Atomically pop a task from the global queue and move it to this
        worker's processing queue.

        Uses BRPOPLPUSH pattern:
          - Blocks for FETCH_TIMEOUT_SECONDS waiting for a task
          - Atomically moves the task to the processing list
          - If worker crashes, task remains in processing list (not lost)

        :return: Parsed task dict, or None if no task available.
        """
        if not self._available:
            return None
        try:
            raw_task = self._redis.brpoplpush(self._queue_name, self._processing_queue, timeout=self._fetch_timeout)
            if raw_task is None:
                return None
            self._current_raw = raw_task
            task_data = json.loads(raw_task)
            workflow_id = task_data.get('workflow_id', 'unknown')
            logger.info(f"[Dispatcher] Worker {self._worker_id} acquired workflow '{workflow_id}'")
            task_data['_fetched_by'] = self._worker_id
            task_data['_fetched_at'] = time.time()
            return task_data
        except json.JSONDecodeError as e:
            logger.error(f'[Dispatcher] Invalid JSON in queue: {e}')
            return None
        except Exception as e:
            logger.error(f'[Dispatcher] Fetch failed: {e}')
            return None

    def mark_workflow_complete(self, workflow_id: str, raw_payload: Optional[str]=None) -> bool:
        """
        Remove the completed task from the processing queue.

        :param workflow_id: The workflow identifier.
        :param raw_payload: The raw JSON string. Uses cached if not provided.
        :return: True if removed.
        """
        if not self._available:
            return False
        payload = raw_payload or self._current_raw
        if not payload:
            logger.warning(f'[Dispatcher] No payload to clear for {workflow_id}')
            return False
        try:
            removed = self._redis.lrem(self._processing_queue, 1, payload)
            if removed:
                logger.info(f"[Dispatcher] Workflow '{workflow_id}' cleared from processing.")
            else:
                logger.warning(f"[Dispatcher] Workflow '{workflow_id}' not found in processing queue.")
            self._current_raw = None
            return bool(removed)
        except Exception as e:
            logger.error(f'[Dispatcher] Complete marking failed: {e}')
            return False

    def mark_workflow_failed(self, workflow_id: str, error: str='', raw_payload: Optional[str]=None) -> bool:
        """
        Move a failed task from processing queue to DLQ.

        :param workflow_id: The workflow identifier.
        :param error: Error description.
        :param raw_payload: The raw JSON string.
        :return: True if moved to DLQ.
        """
        if not self._available:
            return False
        payload = raw_payload or self._current_raw
        if not payload:
            return False
        try:
            dlq_entry = json.dumps({'original_task': json.loads(payload), 'workflow_id': workflow_id, 'failed_by': self._worker_id, 'failed_at': time.time(), 'error': error})
            pipe = self._redis.pipeline()
            pipe.lpush(self._dlq_queue, dlq_entry)
            pipe.lrem(self._processing_queue, 1, payload)
            pipe.execute()
            self._current_raw = None
            logger.warning(f"[Dispatcher] Workflow '{workflow_id}' moved to DLQ.")
            return True
        except Exception as e:
            logger.error(f'[Dispatcher] DLQ move failed: {e}')
            return False

    def submit_workflow(self, task: Dict[str, Any]) -> bool:
        """
        Push a new task to the global queue for any worker to pick up.

        :param task: Task dict with at least 'workflow_id' and 'instructions'.
        :return: True if submitted.
        """
        if not self._available:
            return False
        try:
            task.setdefault('workflow_id', f'wf_{int(time.time())}')
            task.setdefault('submitted_at', time.time())
            raw = json.dumps(task)
            self._redis.lpush(self._queue_name, raw)
            logger.info(f"[Dispatcher] Workflow '{task['workflow_id']}' submitted to queue.")
            return True
        except Exception as e:
            logger.error(f'[Dispatcher] Submit failed: {e}')
            return False

    def get_queue_depth(self) -> int:
        """Get the number of pending tasks in the global queue."""
        if not self._available:
            return 0
        try:
            return self._redis.llen(self._queue_name)
        except Exception:
            return 0

    def get_processing_count(self) -> int:
        """Get the number of tasks currently being processed by this worker."""
        if not self._available:
            return 0
        try:
            return self._redis.llen(self._processing_queue)
        except Exception:
            return 0

    def get_dlq_depth(self) -> int:
        """Get the number of tasks in the DLQ."""
        if not self._available:
            return 0
        try:
            return self._redis.llen(self._dlq_queue)
        except Exception:
            return 0
