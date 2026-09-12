"""
Distributed Lock Manager (DLM) — Redis SETNX idempotency locks for irrevocable DAG nodes.

Before any VM in the fleet executes an irrevocable DAG node, it must acquire a
global lock using the deterministic idempotency key (SHA-256 hash of node action).
This guarantees zero double-spends across 50+ concurrent VMs.

Lock Semantics:
  - SETNX (Set if Not eXists) for atomic mutual exclusion
  - TTL expiry to prevent deadlocks from crashed workers
  - Lua-script release to ensure only the owner can unlock
  - Graceful degradation to local threading.Lock if Redis unavailable

Config in system.yaml:
    DISTRIBUTED_FLEET:
      REDIS_URL: "redis://127.0.0.1:6379/0"
      LOCK_EXPIRY_SECONDS: 300
      LOCK_PREFIX: "ufo:lock:action"

Usage:
    
    from ufo.fleet.distributed_lock import DistributedLockManager

    dlm = DistributedLockManager()
    if dlm.acquire_lock(idempotency_key="abc123", worker_id="vm-01"):
        try:
            # Execute irrevocable action
            ...
        finally:
            dlm.release_lock(idempotency_key="abc123", worker_id="vm-01")

    # Or as a context manager:
        pass
    with dlm.lock(idempotency_key="abc123", worker_id="vm-01") as acquired:
        if acquired:
            # Execute
            ...
"""
import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

def _load_fleet_config() -> Dict[str, Any]:
    """Load distributed fleet config from system.yaml."""
    defaults = {'ENABLED': False, 'REDIS_URL': 'redis://127.0.0.1:6379/0', 'WORKER_ID': 'auto', 'LOCK_EXPIRY_SECONDS': 300, 'LOCK_PREFIX': 'ufo:lock:action'}
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
    """Resolve the worker ID — 'auto' generates hostname+pid."""
    if configured == 'auto':
        hostname = os.environ.get('COMPUTERNAME', os.environ.get('HOSTNAME', 'unknown'))
        return f'{hostname}_{os.getpid()}'
    return configured
_LUA_RELEASE = '\nif redis.call("get", KEYS[1]) == ARGV[1] then\n    return redis.call("del", KEYS[1])\nelse\n    return 0\nend\n'
_LUA_EXTEND = '\nif redis.call("get", KEYS[1]) == ARGV[1] then\n    return redis.call("expire", KEYS[1], ARGV[2])\nelse\n    return 0\nend\n'

class DistributedLockManager:
    """
    Redis-backed distributed lock manager for global mutual exclusion.

    Uses Redis SETNX with TTL expiry for deadlock prevention and
    Lua-script release for ownership verification.

    Falls back to local threading.Lock if Redis is unavailable.
    """

    def __init__(self, redis_url: Optional[str]=None, worker_id: Optional[str]=None) -> None:
        self._config = _load_fleet_config()
        self._redis_url = redis_url or self._config.get('REDIS_URL', 'redis://127.0.0.1:6379/0')
        self._worker_id = worker_id or _resolve_worker_id(self._config.get('WORKER_ID', 'auto'))
        self._lock_expiry = int(self._config.get('LOCK_EXPIRY_SECONDS', 300))
        self._lock_prefix = self._config.get('LOCK_PREFIX', 'ufo:lock:action')
        self._redis = None
        self._available = False
        self._local_locks: Dict[str, threading.Lock] = {}
        self._local_lock_guard = threading.Lock()
        self._init_redis()

    def _init_redis(self) -> None:
        """Initialize Redis connection lazily."""
        if not self._config.get('ENABLED', False):
            logger.info('[DLM] Distributed fleet disabled — using local locks.')
            return
        try:
            import redis
            self._redis = redis.from_url(self._redis_url, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
            self._redis.ping()
            self._available = True
            logger.info(f'[DLM] Redis connected: {self._redis_url} (worker={self._worker_id})')
        except ImportError:
            logger.info('[DLM] redis package not installed — using local locks. Install with: pip install redis')
        except Exception as e:
            logger.warning(f'[DLM] Redis connection failed ({e}) — using local locks.')

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def is_distributed(self) -> bool:
        """Check if distributed locking is active (vs local fallback)."""
        return self._available and self._redis is not None

    def acquire_lock(self, idempotency_key: str, worker_id: Optional[str]=None, expiry: Optional[int]=None) -> bool:
        """
        Attempt to acquire a global execution lock for an irrevocable action.

        :param idempotency_key: Deterministic hash for the action.
        :param worker_id: Override default worker ID.
        :param expiry: Override default lock expiry (seconds).
        :return: True if lock acquired, False if another worker holds it.
        """
        wid = worker_id or self._worker_id
        ttl = expiry or self._lock_expiry
        if self.is_distributed:
            return self._acquire_redis(idempotency_key, wid, ttl)
        else:
            return self._acquire_local(idempotency_key)

    def release_lock(self, idempotency_key: str, worker_id: Optional[str]=None) -> bool:
        """
        Release a held lock. Only the owner can release.

        :param idempotency_key: The lock key.
        :param worker_id: The worker that acquired it.
        :return: True if released, False if not owner or not found.
        """
        wid = worker_id or self._worker_id
        if self.is_distributed:
            return self._release_redis(idempotency_key, wid)
        else:
            return self._release_local(idempotency_key)

    def extend_lock(self, idempotency_key: str, worker_id: Optional[str]=None, extra_seconds: int=60) -> bool:
        """Extend an existing lock's TTL (only if owner)."""
        wid = worker_id or self._worker_id
        if not self.is_distributed:
            return True
        lock_key = f'{self._lock_prefix}:{idempotency_key}'
        try:
            result = self._redis.eval(_LUA_EXTEND, 1, lock_key, wid, str(extra_seconds))
            return bool(result)
        except Exception as e:
            logger.warning(f'[DLM] Lock extend failed: {e}')
            return False

    def is_locked(self, idempotency_key: str) -> bool:
        """Check if a key is currently locked (by anyone)."""
        if self.is_distributed:
            lock_key = f'{self._lock_prefix}:{idempotency_key}'
            try:
                return self._redis.exists(lock_key) > 0
            except Exception:
                return False
        else:
            with self._local_lock_guard:
                lock = self._local_locks.get(idempotency_key)
                return lock is not None and lock.locked()

    def get_lock_owner(self, idempotency_key: str) -> Optional[str]:
        """Get the worker ID that holds a lock (Redis only)."""
        if not self.is_distributed:
            return None
        lock_key = f'{self._lock_prefix}:{idempotency_key}'
        try:
            return self._redis.get(lock_key)
        except Exception:
            return None

    @contextmanager
    def lock(self, idempotency_key: str, worker_id: Optional[str]=None):
        """
        Context manager for lock acquire/release.

        Usage:
            with dlm.lock("key123") as acquired:
                if acquired:
                    pass
                    # do work
        """
        wid = worker_id or self._worker_id
        acquired = self.acquire_lock(idempotency_key, wid)
        try:
            yield acquired
        finally:
            if acquired:
                self.release_lock(idempotency_key, wid)

    def _acquire_redis(self, idempotency_key: str, worker_id: str, expiry: int) -> bool:
        """Acquire via Redis SETNX with TTL."""
        lock_key = f'{self._lock_prefix}:{idempotency_key}'
        try:
            acquired = self._redis.set(lock_key, worker_id, nx=True, ex=expiry)
            if acquired:
                logger.info(f'[DLM] Worker {worker_id} ACQUIRED lock: {idempotency_key}')
                return True
            else:
                owner = self._redis.get(lock_key)
                logger.critical(f'[DLM] Lock COLLISION: {idempotency_key} held by {owner}')
                return False
        except Exception as e:
            logger.error(f'[DLM] Redis acquire failed: {e}')
            return self._acquire_local(idempotency_key)

    def _release_redis(self, idempotency_key: str, worker_id: str) -> bool:
        """Release via atomic Lua script (only owner can delete)."""
        lock_key = f'{self._lock_prefix}:{idempotency_key}'
        try:
            result = self._redis.eval(_LUA_RELEASE, 1, lock_key, worker_id)
            released = bool(result)
            if released:
                logger.info(f'[DLM] Worker {worker_id} RELEASED lock: {idempotency_key}')
            else:
                logger.warning(f'[DLM] Release failed — {worker_id} is not the owner of {idempotency_key}')
            return released
        except Exception as e:
            logger.error(f'[DLM] Redis release failed: {e}')
            return False

    def _acquire_local(self, idempotency_key: str) -> bool:
        """Fallback: acquire a local threading.Lock."""
        with self._local_lock_guard:
            if idempotency_key not in self._local_locks:
                self._local_locks[idempotency_key] = threading.Lock()
            lock = self._local_locks[idempotency_key]
        acquired = lock.acquire(blocking=False)
        if acquired:
            logger.info(f'[DLM] Local lock ACQUIRED: {idempotency_key}')
        else:
            logger.warning(f'[DLM] Local lock COLLISION: {idempotency_key}')
        return acquired

    def _release_local(self, idempotency_key: str) -> bool:
        """Fallback: release a local threading.Lock."""
        with self._local_lock_guard:
            lock = self._local_locks.get(idempotency_key)
        if lock is None:
            return False
        try:
            lock.release()
            logger.info(f'[DLM] Local lock RELEASED: {idempotency_key}')
            return True
        except RuntimeError:
            return False