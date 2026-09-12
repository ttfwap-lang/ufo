"""
UFO 24/7 Event Daemon — Event-driven background runner for headless operation.

Replaces naive while-True polling with an efficient event-driven loop.
The HostAgent only wakes when a valid trigger occurs:
  - File drop (watchdog filesystem monitor)
  - HTTP webhook (external CI/CD or BankFidelity triggers)
  - Scheduled cron (periodic tasks)
  - Manual queue push

Zero-CPU sleep: uses threading.Event / queue.Queue blocking, which
yields the CPU completely while waiting.

Config in system.yaml:
    FLEET_DAEMON:
      ENABLED: false
      HEARTBEAT_INTERVAL_SECONDS: 60
      MAX_CONCURRENT_WORKFLOWS: 1
      WEBHOOK_PORT: 8765
      ALLOWED_TRIGGER_TYPES:
        - file_drop
        - webhook
        - scheduled
        - manual

Usage:
    
    from ufo.fleet.event_daemon import UFOEventDaemon

    daemon = UFOEventDaemon()
    daemon.submit_event({
        "event_type": "manual",
        "instructions": "Open Excel and summarize the quarterly report",
        "is_irrevocable": False,
    })
    daemon.start()  # Blocks — runs until stop() is called
"""
import logging
import os
import queue
import signal
import threading
import time
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field
logger = logging.getLogger(__name__)

class DaemonEvent(BaseModel):
    """An event that triggers a HostAgent workflow."""
    event_type: str = Field(..., description='Trigger type: file_drop, webhook, scheduled, manual')
    instructions: str = Field(..., description='The user intent / task description')
    is_irrevocable: bool = Field(default=False, description='If true, force DAG mode')
    source: str = Field(default='unknown', description='Where the event came from')
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)

class DaemonStats(BaseModel):
    """Daemon operational statistics."""
    is_running: bool = False
    uptime_seconds: float = 0.0
    events_processed: int = 0
    events_failed: int = 0
    events_pending: int = 0
    current_workflow: Optional[str] = None

def _load_daemon_config() -> Dict[str, Any]:
    """Load daemon config from system.yaml."""
    defaults = {'ENABLED': False, 'HEARTBEAT_INTERVAL_SECONDS': 60, 'MAX_CONCURRENT_WORKFLOWS': 1, 'WEBHOOK_PORT': 8765, 'ALLOWED_TRIGGER_TYPES': ['file_drop', 'webhook', 'scheduled', 'manual']}
    try:
        from ufo.config.config_loader import get_ufo_config
        cfg = get_ufo_config()
        fd_cfg = getattr(cfg.system, 'fleet_daemon', None)
        if fd_cfg and isinstance(fd_cfg, dict):
            defaults.update({k: v for k, v in fd_cfg.items() if v is not None})
    except Exception:
        pass
    return defaults

class UFOEventDaemon:
    """
    24/7 event-driven daemon for headless UFO operation.

    Architecture:
      - Main loop blocks on queue.get() → zero CPU while idle
      - Heartbeat thread logs health at configurable intervals
      - Accepts events via submit_event() or webhook_trigger()
      - Routes to OrchestratorRouter for DAG/ReAct selection
      - Enforces budget checks via CostTracker before each workflow
    """

    def __init__(self) -> None:
        self._config = _load_daemon_config()
        self._event_queue: queue.Queue = queue.Queue()
        self._is_running = False
        self._start_time: float = 0.0
        self._stats_processed = 0
        self._stats_failed = 0
        self._current_workflow: Optional[str] = None
        self._stop_event = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._workflow_handler: Optional[Callable] = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self, workflow_handler: Optional[Callable]=None) -> None:
        """
        Start the daemon. Blocks until stop() is called.

        :param workflow_handler: Optional callback(DaemonEvent) -> None.
                                 If not provided, uses _default_handler.
        """
        if self._is_running:
            logger.warning('[Daemon] Already running.')
            return
        self._is_running = True
        self._start_time = time.monotonic()
        self._stop_event.clear()
        self._workflow_handler = workflow_handler
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except (OSError, ValueError):
            pass
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name='ufo-heartbeat')
        self._heartbeat_thread.start()
        logger.info(f"[Daemon] UFO 24/7 Event Daemon started. Waiting for events on queue. Heartbeat every {self._config['HEARTBEAT_INTERVAL_SECONDS']}s.")
        try:
            self._event_loop()
        finally:
            self._is_running = False
            logger.info('[Daemon] Event loop terminated.')

    def start_background(self, workflow_handler: Optional[Callable]=None) -> threading.Thread:
        """
        Start the daemon in a background thread (non-blocking).

        :param workflow_handler: Optional callback for processing events.
        :return: The daemon thread.
        """
        thread = threading.Thread(target=self.start, args=(workflow_handler,), daemon=True, name='ufo-daemon')
        thread.start()
        return thread

    def stop(self) -> None:
        """Signal the daemon to stop gracefully."""
        logger.info('[Daemon] Stop signal received.')
        self._is_running = False
        self._stop_event.set()
        self._event_queue.put(None)

    def submit_event(self, event: Dict[str, Any]) -> bool:
        """
        Submit an event to the daemon's processing queue.

        :param event: Event dict with at least 'event_type' and 'instructions'.
        :return: True if accepted, False if rejected.
        """
        event_type = event.get('event_type', 'unknown')
        allowed = self._config.get('ALLOWED_TRIGGER_TYPES', [])
        if allowed and event_type not in allowed:
            logger.warning(f"[Daemon] Rejected event type '{event_type}'. Allowed: {allowed}")
            return False
        try:
            parsed = DaemonEvent(**event)
            self._event_queue.put(parsed)
            logger.info(f"[Daemon] Event queued: type={parsed.event_type}, instructions='{parsed.instructions[:60]}...'")
            return True
        except Exception as e:
            logger.error(f'[Daemon] Failed to parse event: {e}')
            return False

    def webhook_trigger(self, payload: Dict[str, Any]) -> bool:
        """
        Endpoint for CI/CD or external systems to trigger the agent.

        :param payload: Webhook payload with event details.
        :return: True if accepted.
        """
        payload.setdefault('event_type', 'webhook')
        payload.setdefault('source', 'external_webhook')
        return self.submit_event(payload)

    def _event_loop(self) -> None:
        """Main event processing loop. Blocks on queue — zero CPU while idle."""
        while self._is_running:
            try:
                event = self._event_queue.get(block=True, timeout=1.0)
                if event is None:
                    continue
                if not self._is_running:
                    break
                if not isinstance(event, DaemonEvent):
                    logger.warning(f'[Daemon] Invalid event type: {type(event)}')
                    continue
                self._process_event(event)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f'[Daemon] Unhandled error in event loop: {e}')
                self._stats_failed += 1

    def _process_event(self, event: DaemonEvent) -> None:
        """Process a single event through the workflow pipeline."""
        with self._lock:
            self._current_workflow = event.instructions[:80]
        logger.info(f"[Daemon] Processing event: type={event.event_type}, instructions='{event.instructions[:80]}...'")
        try:
            from ufo.telemetry.cost_tracker import CostTracker
            tracker = CostTracker.get_instance()
            if tracker.is_budget_exceeded():
                logger.critical('[Daemon] Budget exceeded — skipping workflow. Event will not be retried.')
                self._stats_failed += 1
                return
        except ImportError:
            pass
        try:
            if self._workflow_handler:
                self._workflow_handler(event)
            else:
                self._default_handler(event)
            self._stats_processed += 1
            logger.info('[Daemon] Workflow complete. Returning to sleep.')
        except Exception as e:
            self._stats_failed += 1
            logger.error(f'[Daemon] Workflow failed: {e}')
            try:
                from ufo.resilience.dlq_manager import DeadLetterQueueManager
                dlq = DeadLetterQueueManager()
                dlq.capture_failure(task_id=f'daemon_{int(event.timestamp)}', error_chain=str(e), metadata={'event_type': event.event_type, 'instructions': event.instructions})
            except Exception:
                pass
        finally:
            with self._lock:
                self._current_workflow = None

    def _default_handler(self, event: DaemonEvent) -> None:
        """Default event handler — routes through OrchestratorRouter."""
        try:
            from ufo.agents.host_agent.orchestrator_router import OrchestratorRouter
            router = OrchestratorRouter()
            result = router.execute_with_routing(user_intent=event.instructions, is_financial_routing=event.is_irrevocable)
            logger.info(f"[Daemon] Router result: mode={result.get('mode', 'unknown')}")
        except ImportError:
            logger.warning('[Daemon] OrchestratorRouter not available. Event logged but not processed.')

    def _heartbeat_loop(self) -> None:
        """Periodic heartbeat for health monitoring."""
        interval = self._config.get('HEARTBEAT_INTERVAL_SECONDS', 60)
        while self._is_running and (not self._stop_event.is_set()):
            self._stop_event.wait(timeout=interval)
            if not self._is_running:
                break
            uptime = time.monotonic() - self._start_time
            pending = self._event_queue.qsize()
            logger.info(f'[Daemon] Heartbeat — uptime={uptime:.0f}s, processed={self._stats_processed}, failed={self._stats_failed}, pending={pending}')

    def get_stats(self) -> DaemonStats:
        """Get current daemon statistics."""
        with self._lock:
            return DaemonStats(is_running=self._is_running, uptime_seconds=time.monotonic() - self._start_time if self._is_running else 0.0, events_processed=self._stats_processed, events_failed=self._stats_failed, events_pending=self._event_queue.qsize(), current_workflow=self._current_workflow)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle OS signals for graceful shutdown."""
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        logger.info(f'[Daemon] Received signal {sig_name}. Initiating shutdown.')
        self.stop()