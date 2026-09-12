"""
Fleet Health Watchdog — Heartbeat monitor and orphaned-task triage.

Runs as a lightweight background thread (or standalone process) that:
  1. Each worker reports a heartbeat every N seconds to Redis
  2. The watchdog scans all registered heartbeats
  3. If a worker misses its heartbeat window, it is declared dead
  4. Orphaned tasks in the dead worker's processing queue are triaged to DLQ
     (NOT re-queued, because we don't know the OS state the VM died in)
  5. Fires DLQ webhook alert for human operator notification

Config in system.yaml:
    DISTRIBUTED_FLEET:
      HEARTBEAT_KEY: "ufo:fleet:heartbeats"
      HEARTBEAT_INTERVAL_SECONDS: 10
      WATCHDOG_TIMEOUT_SECONDS: 30
      DLQ_QUEUE: "ufo:queue:dlq"

Usage:
    # Worker side — start heartbeat reporter:
        pass
    from ufo.fleet.health_watchdog import WorkerHeartbeat

    heartbeat = WorkerHeartbeat(worker_id="vm-01")
    heartbeat.start()  # Background thread

    # Watchdog side — monitor fleet health:
        pass
    from ufo.fleet.health_watchdog import FleetWatchdog

    watchdog = FleetWatchdog()
    watchdog.start()  # Blocks — runs until stopped
"""
import json
import logging
import os
import signal
import threading
import time
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

def _load_watchdog_config() -> Dict[str, Any]:
    """Load watchdog config from system.yaml."""
    defaults = {'ENABLED': False, 'REDIS_URL': 'redis://127.0.0.1:6379/0', 'HEARTBEAT_KEY': 'ufo:fleet:heartbeats', 'HEARTBEAT_INTERVAL_SECONDS': 10, 'WATCHDOG_TIMEOUT_SECONDS': 30, 'DLQ_QUEUE': 'ufo:queue:dlq', 'WORKER_ID': 'auto'}
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

class WorkerHeartbeat:
    """
    Background thread that periodically reports this worker's liveness
    to a Redis hash. The FleetWatchdog reads these heartbeats.
    """

    def __init__(self, worker_id: Optional[str]=None, redis_url: Optional[str]=None) -> None:
        self._config = _load_watchdog_config()
        self._worker_id = worker_id or _resolve_worker_id(self._config.get('WORKER_ID', 'auto'))
        self._redis_url = redis_url or self._config.get('REDIS_URL')
        self._hb_key = self._config.get('HEARTBEAT_KEY', 'ufo:fleet:heartbeats')
        self._interval = int(self._config.get('HEARTBEAT_INTERVAL_SECONDS', 10))
        self._redis = None
        self._available = False
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._init_redis()

    def _init_redis(self) -> None:
        """Connect to Redis."""
        if not self._config.get('ENABLED', False):
            return
        try:
            import redis
            self._redis = redis.from_url(self._redis_url, decode_responses=True, socket_connect_timeout=5)
            self._redis.ping()
            self._available = True
        except Exception as e:
            logger.warning(f'[Heartbeat] Redis unavailable: {e}')

    def start(self) -> Optional[threading.Thread]:
        """Start the heartbeat reporter as a daemon thread."""
        if not self._available:
            logger.info('[Heartbeat] Redis unavailable — heartbeat disabled.')
            return None
        if self._running:
            return self._thread
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name=f'heartbeat-{self._worker_id}')
        self._thread.start()
        logger.info(f"[Heartbeat] Started for worker '{self._worker_id}' (interval={self._interval}s)")
        return self._thread

    def stop(self) -> None:
        """Stop the heartbeat reporter."""
        self._running = False
        self._stop_event.set()
        logger.info(f"[Heartbeat] Stopped for worker '{self._worker_id}'")

    def beat(self) -> bool:
        """Send a single heartbeat (manual trigger)."""
        if not self._available:
            return False
        try:
            self._redis.hset(self._hb_key, self._worker_id, str(int(time.time())))
            return True
        except Exception as e:
            logger.warning(f'[Heartbeat] Beat failed: {e}')
            return False

    def _heartbeat_loop(self) -> None:
        """Background loop that sends heartbeats periodically."""
        while self._running and (not self._stop_event.is_set()):
            try:
                self._redis.hset(self._hb_key, self._worker_id, str(int(time.time())))
            except Exception as e:
                logger.warning(f'[Heartbeat] Failed: {e}')
            self._stop_event.wait(timeout=self._interval)

class FleetWatchdog:
    """
    Monitors fleet worker heartbeats and triages orphaned tasks.

    When a worker misses its heartbeat window (WATCHDOG_TIMEOUT_SECONDS),
    the watchdog:
      1. Declares the worker dead
      2. Moves all tasks from the dead worker's processing queue to DLQ
      3. Fires DLQ webhook alert for operator notification
      4. Removes the dead worker from the heartbeat registry
    """

    def __init__(self, redis_url: Optional[str]=None) -> None:
        self._config = _load_watchdog_config()
        self._redis_url = redis_url or self._config.get('REDIS_URL')
        self._hb_key = self._config.get('HEARTBEAT_KEY', 'ufo:fleet:heartbeats')
        self._timeout = int(self._config.get('WATCHDOG_TIMEOUT_SECONDS', 30))
        self._dlq_queue = self._config.get('DLQ_QUEUE', 'ufo:queue:dlq')
        self._scan_interval = min(self._timeout // 3, 10)
        self._redis = None
        self._available = False
        self._running = False
        self._stop_event = threading.Event()
        self._init_redis()

    def _init_redis(self) -> None:
        """Connect to Redis."""
        if not self._config.get('ENABLED', False):
            return
        try:
            import redis
            self._redis = redis.from_url(self._redis_url, decode_responses=True, socket_connect_timeout=5)
            self._redis.ping()
            self._available = True
        except Exception as e:
            logger.warning(f'[Watchdog] Redis unavailable: {e}')

    def start(self) -> None:
        """Start the fleet health monitor. Blocks until stop() is called."""
        if not self._available:
            logger.error('[Watchdog] Redis not available — cannot monitor fleet.')
            return
        self._running = True
        self._stop_event.clear()
        logger.info(f'[Watchdog] Fleet health monitor active. Timeout={self._timeout}s, scan every {self._scan_interval}s.')
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except (OSError, ValueError):
            pass
        while self._running and (not self._stop_event.is_set()):
            try:
                self._scan_heartbeats()
            except Exception as e:
                logger.error(f'[Watchdog] Scan error: {e}')
            self._stop_event.wait(timeout=self._scan_interval)
        logger.info('[Watchdog] Monitor stopped.')

    def start_background(self) -> threading.Thread:
        """Start in a background thread."""
        thread = threading.Thread(target=self.start, daemon=True, name='fleet-watchdog')
        thread.start()
        return thread

    def stop(self) -> None:
        """Stop the watchdog."""
        self._running = False
        self._stop_event.set()

    def _scan_heartbeats(self) -> None:
        """Check all worker heartbeats and triage dead workers."""
        workers = self._redis.hgetall(self._hb_key)
        now = int(time.time())
        dead_workers = []
        for worker_id, last_beat_str in workers.items():
            try:
                last_beat = int(last_beat_str)
            except (ValueError, TypeError):
                last_beat = 0
            silence = now - last_beat
            if silence > self._timeout:
                logger.critical(f"[Watchdog] Worker '{worker_id}' FLATLINED! Last heartbeat {silence}s ago (timeout={self._timeout}s).")
                dead_workers.append(worker_id)
        for dead_id in dead_workers:
            self._recover_orphaned_tasks(dead_id)
            self._redis.hdel(self._hb_key, dead_id)
            logger.info(f"[Watchdog] Removed dead worker '{dead_id}' from registry.")

    def _recover_orphaned_tasks(self, dead_worker_id: str) -> int:
        """
        Move all tasks from the dead worker's processing queue to DLQ.

        Tasks are NOT re-queued because we don't know the OS state the VM
        died in — the action might have been partially executed (e.g., half
        a wire transfer). Orphans go to DLQ for human operator triage.

        :param dead_worker_id: The dead worker's ID.
        :return: Number of orphaned tasks triaged.
        """
        processing_queue = f'ufo:queue:processing:{dead_worker_id}'
        try:
            orphans = self._redis.lrange(processing_queue, 0, -1)
            if not orphans:
                logger.info(f"[Watchdog] No orphaned tasks for worker '{dead_worker_id}'.")
                return 0
            logger.warning(f"[Watchdog] Found {len(orphans)} orphaned tasks from worker '{dead_worker_id}'.")
            triaged = 0
            for raw_task in orphans:
                try:
                    dlq_entry = json.dumps({'original_task': json.loads(raw_task) if isinstance(raw_task, str) else raw_task, 'orphaned_from': dead_worker_id, 'triaged_at': time.time(), 'reason': 'worker_flatlined'})
                    pipe = self._redis.pipeline()
                    pipe.lpush(self._dlq_queue, dlq_entry)
                    pipe.lrem(processing_queue, 1, raw_task)
                    pipe.execute()
                    triaged += 1
                    logger.error(f"[Watchdog] Orphan triaged to DLQ from worker '{dead_worker_id}'.")
                except Exception as e:
                    logger.error(f'[Watchdog] Failed to triage orphan: {e}')
            self._fire_alert(dead_worker_id, triaged)
            return triaged
        except Exception as e:
            logger.error(f"[Watchdog] Orphan recovery failed for '{dead_worker_id}': {e}")
            return 0

    def _fire_alert(self, dead_worker_id: str, orphan_count: int) -> None:
        """Fire DLQ alert via the existing DLQ webhook infrastructure."""
        try:
            from ufo.resilience.dlq_manager import DeadLetterQueueManager
            dlq = DeadLetterQueueManager()
            dlq.capture_failure(task_id=f'ORPHAN_{dead_worker_id}', error_chain=f"Worker '{dead_worker_id}' flatlined. {orphan_count} orphaned tasks triaged to DLQ.", metadata={'dead_worker_id': dead_worker_id, 'orphan_count': orphan_count, 'event': 'worker_flatlined'})
        except Exception as e:
            logger.error(f'[Watchdog] DLQ alert failed: {e}')

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle OS signals for graceful shutdown."""
        logger.info(f'[Watchdog] Received signal {signum}. Shutting down.')
        self.stop()

    def get_fleet_status(self) -> Dict[str, Any]:
        """Get current status of all fleet workers."""
        if not self._available:
            return {'error': 'Redis not available'}
        try:
            workers = self._redis.hgetall(self._hb_key)
            now = int(time.time())
            status = {}
            for worker_id, last_beat_str in workers.items():
                last_beat = int(last_beat_str)
                silence = now - last_beat
                processing_queue = f'ufo:queue:processing:{worker_id}'
                active_tasks = self._redis.llen(processing_queue)
                status[worker_id] = {'last_heartbeat': last_beat, 'silence_seconds': silence, 'alive': silence <= self._timeout, 'active_tasks': active_tasks}
            return {'workers': status, 'total_workers': len(status), 'alive_workers': sum((1 for w in status.values() if w['alive'])), 'dead_workers': sum((1 for w in status.values() if not w['alive']))}
        except Exception as e:
            return {'error': str(e)}
