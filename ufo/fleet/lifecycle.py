"""
Graceful Shutdown & Lifecycle Hook — Safe fleet termination during rolling deploys.

When CI/CD pushes an update and restarts the fleet (docker stop, VM restart,
service manager stop), an agent must NOT be killed while interacting with a
financial portal. This module ensures:

  1. SIGTERM/SIGINT is caught immediately
  2. No new tasks are accepted from the queue
  3. The current workflow runs to completion (or a safe checkpoint)
  4. Distributed locks are released
  5. Process exits cleanly with code 0

Windows Compatibility:
  Windows doesn't have SIGTERM. We handle:
    - signal.SIGINT (Ctrl+C)
    - signal.SIGBREAK (Ctrl+Break, if available)
    - win32api.SetConsoleCtrlHandler (service stop, logoff, shutdown)

Config in system.yaml:
    LIFECYCLE:
      MAX_DRAIN_SECONDS: 300      # Max time to wait for workflow completion
      FORCE_KILL_AFTER: 600       # Hard kill if drain exceeds this

Usage:
    from ufo.fleet.lifecycle import GracefulKiller


    killer = GracefulKiller(dispatcher=my_dispatcher)

    while not killer.should_shutdown:
        task = dispatcher.fetch_next_workflow()
        if task:
            killer.register_active_workflow(task["workflow_id"])
            try:
                process(task)
            finally:
                killer.clear_active_workflow()

    # After the loop, wait_for_safe_exit handles cleanup
    await killer.wait_for_safe_exit()
"""
import logging
import os
import signal
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional
logger = logging.getLogger(__name__)

def _load_lifecycle_config() -> Dict[str, Any]:
    """Load lifecycle config from system.yaml."""
    defaults = {'MAX_DRAIN_SECONDS': 300, 'FORCE_KILL_AFTER': 600}
    try:
        from ufo.config.config_loader import get_ufo_config
        cfg = get_ufo_config()
        lc = getattr(cfg.system, 'lifecycle', None)
        if lc and isinstance(lc, dict):
            defaults.update({k: v for k, v in lc.items() if v is not None})
    except Exception:
        pass
    return defaults

class GracefulKiller:
    """
    OS signal handler for graceful agent shutdown.

    Catches termination signals and coordinates a clean exit:
      1. Stops accepting new tasks
      2. Waits for active workflow to complete
      3. Releases distributed locks
      4. Exits with code 0

    Thread-safe — signal handlers run on the main thread, but the
    should_shutdown flag is checked from worker threads.
    """

    def __init__(self, dispatcher: Any=None, max_drain_seconds: Optional[int]=None, force_kill_after: Optional[int]=None, on_shutdown: Optional[Callable[[], None]]=None) -> None:
        """
        :param dispatcher: GlobalDispatcher or UFOEventDaemon instance.
                          Must have stop_accepting_tasks() or stop() method.
        :param max_drain_seconds: Max time to wait for active workflow.
        :param force_kill_after: Hard kill timeout.
        :param on_shutdown: Optional callback invoked when shutdown begins.
        """
        self._config = _load_lifecycle_config()
        self._dispatcher = dispatcher
        self._max_drain = max_drain_seconds or int(self._config.get('MAX_DRAIN_SECONDS', 300))
        self._force_kill = force_kill_after or int(self._config.get('FORCE_KILL_AFTER', 600))
        self._on_shutdown = on_shutdown
        self._kill_now = False
        self._shutdown_requested_at: Optional[float] = None
        self._active_workflow_id: Optional[str] = None
        self._active_workflow_safe = threading.Event()
        self._active_workflow_safe.set()
        self._lock = threading.Lock()
        self._bind_signals()

    @property
    def should_shutdown(self) -> bool:
        """Check if shutdown has been requested. Use in the main worker loop."""
        return self._kill_now

    @property
    def active_workflow_id(self) -> Optional[str]:
        """The currently executing workflow, if any."""
        return self._active_workflow_id

    @property
    def seconds_since_shutdown_request(self) -> float:
        """Seconds elapsed since shutdown was first requested."""
        if self._shutdown_requested_at is None:
            return 0.0
        return time.monotonic() - self._shutdown_requested_at

    def register_active_workflow(self, workflow_id: str) -> None:
        """
        Mark a workflow as actively executing.
        Shutdown will block until this workflow completes.
        """
        with self._lock:
            self._active_workflow_id = workflow_id
            self._active_workflow_safe.clear()
            logger.debug(f'[Lifecycle] Active workflow registered: {workflow_id}')

    def clear_active_workflow(self) -> None:
        """
        Mark the active workflow as complete.
        If shutdown is pending, this unblocks the exit.
        """
        with self._lock:
            wf_id = self._active_workflow_id
            self._active_workflow_id = None
            self._active_workflow_safe.set()
            if wf_id:
                logger.debug(f'[Lifecycle] Workflow completed: {wf_id}')
            if self._kill_now:
                logger.info('[Lifecycle] Workflow cleared during shutdown — process may now exit.')

    def _bind_signals(self) -> None:
        """Bind OS termination signals to our graceful handler."""
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
        except (OSError, ValueError):
            pass
        if hasattr(signal, 'SIGTERM'):
            try:
                signal.signal(signal.SIGTERM, self._handle_signal)
            except (OSError, ValueError):
                pass
        if hasattr(signal, 'SIGBREAK'):
            try:
                signal.signal(signal.SIGBREAK, self._handle_signal)
            except (OSError, ValueError):
                pass
        try:
            import win32api
            win32api.SetConsoleCtrlHandler(self._win32_ctrl_handler, True)
            logger.debug('[Lifecycle] Win32 console control handler registered.')
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f'[Lifecycle] Win32 handler registration failed: {e}')

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle termination signal."""
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        logger.warning(f'[Lifecycle] Termination signal received: {sig_name}. Initiating graceful shutdown...')
        self._initiate_shutdown()

    def _win32_ctrl_handler(self, ctrl_type: int) -> bool:
        """Windows console control handler callback."""
        logger.warning(f'[Lifecycle] Windows control event {ctrl_type}. Initiating graceful shutdown...')
        self._initiate_shutdown()
        return True

    def _initiate_shutdown(self) -> None:
        """Begin the shutdown sequence."""
        if self._kill_now:
            logger.critical('[Lifecycle] Second termination signal! Force killing...')
            os._exit(1)
        self._kill_now = True
        self._shutdown_requested_at = time.monotonic()
        if self._on_shutdown:
            try:
                self._on_shutdown()
            except Exception as e:
                logger.error(f'[Lifecycle] Shutdown callback failed: {e}')
        self._stop_dispatcher()
        if self._active_workflow_id:
            logger.warning(f"[Lifecycle] Active workflow '{self._active_workflow_id}' in progress. Waiting up to {self._max_drain}s for completion...")
        else:
            logger.info('[Lifecycle] No active workflow. Ready to exit.')

    def _stop_dispatcher(self) -> None:
        """Signal the dispatcher to stop accepting new work."""
        if self._dispatcher is None:
            return
        for method_name in ('stop_accepting_tasks', 'stop', 'shutdown'):
            method = getattr(self._dispatcher, method_name, None)
            if callable(method):
                try:
                    method()
                    logger.info(f'[Lifecycle] Dispatcher stopped via {method_name}()')
                    return
                except Exception as e:
                    logger.warning(f'[Lifecycle] Dispatcher.{method_name}() failed: {e}')
        for attr_name in ('_accepting', 'accepting', 'running'):
            if hasattr(self._dispatcher, attr_name):
                try:
                    setattr(self._dispatcher, attr_name, False)
                    logger.info(f"[Lifecycle] Dispatcher flag '{attr_name}' set to False")
                    return
                except Exception:
                    pass
        logger.warning('[Lifecycle] Could not stop dispatcher — no compatible interface found.')

    async def wait_for_safe_exit(self) -> None:
        """
        Async version: Wait for the active workflow to complete, then exit.

        Call this from the main async worker loop after should_shutdown is True.
        """
        import asyncio
        if not self._kill_now:
            return
        start = time.monotonic()
        while not self._active_workflow_safe.is_set():
            elapsed = time.monotonic() - start
            if elapsed > self._force_kill:
                logger.critical(f"[Lifecycle] Force kill timeout ({self._force_kill}s) exceeded! Killing workflow '{self._active_workflow_id}'.")
                break
            if elapsed > self._max_drain:
                logger.error(f"[Lifecycle] Drain timeout ({self._max_drain}s) exceeded. Workflow '{self._active_workflow_id}' still running.")
            await asyncio.sleep(1.0)
        self._release_locks()
        logger.critical('[Lifecycle] Graceful shutdown complete. Exiting with code 0.')
        sys.exit(0)

    def wait_for_safe_exit_sync(self) -> None:
        """
        Sync version: Block until the active workflow completes, then exit.
        """
        if not self._kill_now:
            return
        safe = self._active_workflow_safe.wait(timeout=self._force_kill)
        if not safe:
            logger.critical(f'[Lifecycle] Force kill timeout ({self._force_kill}s) exceeded!')
        self._release_locks()
        logger.critical('[Lifecycle] Graceful shutdown complete. Exiting with code 0.')
        sys.exit(0)

    def _release_locks(self) -> None:
        """Release any distributed locks held by this worker."""
        try:
            from ufo.fleet.distributed_lock import DistributedLockManager
            lock_mgr = DistributedLockManager()
            if hasattr(lock_mgr, 'release_all'):
                lock_mgr.release_all()
                logger.info('[Lifecycle] Distributed locks released.')
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f'[Lifecycle] Lock release failed: {e}')

    def get_status(self) -> Dict[str, Any]:
        """Get current lifecycle status for telemetry/dashboard."""
        return {'shutdown_requested': self._kill_now, 'shutdown_requested_at': self._shutdown_requested_at, 'seconds_draining': self.seconds_since_shutdown_request, 'active_workflow': self._active_workflow_id, 'max_drain_seconds': self._max_drain, 'force_kill_after': self._force_kill}
_default_killer: Optional[GracefulKiller] = None

def get_lifecycle_manager(dispatcher: Any=None, **kwargs: Any) -> GracefulKiller:
    """Get or create the default lifecycle manager singleton."""
    global _default_killer
    if _default_killer is None:
        _default_killer = GracefulKiller(dispatcher=dispatcher, **kwargs)
    return _default_killer